"""Batch-probe a sample of registry servers inside Docker sandboxes.

Selects locally-runnable candidates from the sampling frame (stdio transport,
npm/pypi package, no required env vars or arguments), launches each in an
isolated container (fresh filesystem, memory/cpu/pid caps, --init, auto-remove;
a named volume caches package downloads across runs), and appends one probe
result per server to data/probe_results.jsonl.

Usage:
  python run_batch.py --n 20 --seed 42 [--timeout 90] [--workers 4]
"""

import argparse
import json
import datetime as dt
import random
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mcpprobe  # noqa: E402
from mcpprobe import probe  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
FRAME = DATA / "frame_latest.jsonl"
OUT = DATA / "probe_results.jsonl"

CENSUS_LABEL = "mcpcensus=1"  # stamped on every container we start, so the
                              # reaper below can find ours and only ours
NODE_IMAGE = "node:22-slim"
UV_IMAGE = "ghcr.io/astral-sh/uv:python3.12-bookworm-slim"

# Substrings that mean "the Docker engine failed", not "the package/server failed".
# A prime/probe that dies for these reasons must NOT be recorded as install-error;
# it is a harness-environment fault and the server is retried once the engine heals.
DOCKER_ERR_SIGNS = (
    "cannot connect to the docker daemon",
    "error during connect",
    "500 internal server error",
    "the system cannot find the file specified",  # dead named pipe on Windows
    "is the docker daemon running",
    "docker daemon is not running",
    "request returned internal server error",
    "context deadline exceeded",
)


def is_docker_error(text: str) -> bool:
    t = (text or "").lower()
    return any(s in t for s in DOCKER_ERR_SIGNS)


def docker_healthy() -> bool:
    try:
        r = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                           capture_output=True, text=True, timeout=25)
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:  # noqa: BLE001
        return False


def wait_for_docker(max_wait: float = 600.0) -> bool:
    """Block until the engine answers again (up to max_wait). Used to ride out a
    transient engine crash without recording false failures."""
    import time
    waited = 0.0
    while waited < max_wait:
        if docker_healthy():
            return True
        time.sleep(10)
        waited += 10
    return False


def requires_input(items) -> bool:
    """True if any declared variable/argument is marked required with no default."""
    for it in items or []:
        if (it.get("isRequired") or it.get("required")) and it.get("default") is None:
            return True
    return False


def eligible_packages(server: dict):
    for p in server.get("packages") or []:
        if (p.get("transport") or {}).get("type") != "stdio":
            continue
        if p.get("registryType") not in ("npm", "pypi"):
            continue
        if requires_input(p.get("environmentVariables")):
            continue
        if requires_input(p.get("packageArguments")) or requires_input(p.get("runtimeArguments")):
            continue
        yield p


TEMPLATE = re.compile(r"\{[^}]+\}")


def render_args(items) -> list[str]:
    """Render registry-declared arguments the way a registry client would.

    The census originally used runtimeArguments and packageArguments only to
    exclude servers with required input, and never passed the rest at launch. A
    server whose entry says "run me with serve" was started bare, printed its help
    and exited, and was graded as failing to start. 523 servers declare arguments,
    and they completed a handshake at 27% against 63.5% for the rest.

    Rendering follows the registry's server.json reference: a positional argument
    contributes its value, or its default; a named argument contributes its name
    followed by its value, or by its default; an argument with neither is optional
    user input and is left out. A value that still holds an unresolved {template}
    after substituting variable defaults is also left out, since only a user can
    supply it. Repeated arguments are rendered once.
    """
    out = []
    for a in items or []:
        if not isinstance(a, dict):
            continue
        val = a.get("value")
        if val is None:
            val = a.get("default")
        if isinstance(val, str) and TEMPLATE.search(val):
            for name, var in (a.get("variables") or {}).items():
                if isinstance(var, dict) and var.get("default") is not None:
                    val = val.replace("{" + name + "}", str(var["default"]))
            if TEMPLATE.search(val):
                continue
        kind = a.get("type") or ("named" if a.get("name") else "positional")
        if kind == "named":
            if not a.get("name"):
                continue
            if val is None:
                continue
            out += [a["name"], str(val)]
        else:
            if val is None:
                continue
            out.append(str(val))
    return out


def _pkg_spec(pkg: dict) -> str:
    ident, version = pkg["identifier"], pkg.get("version")
    if pkg["registryType"] == "npm":
        return f"{ident}@{version}" if version else ident
    return f"{ident}=={version}" if version else ident


# `uvx <package>` requires the package's console-script name to equal the package
# name. When it does not, uv installs fine, refuses to launch, and names the
# scripts it *does* provide. npm has no analogue -- `npx -y <pkg>` resolves the
# binary from package.json -- so scoring these as server failures would bias PyPI
# runnability downward against npm for a purely packaging-convention reason. We
# parse uv's own hint and relaunch via `uvx --from <spec> <script>`.
UVX_NO_EXE = re.compile(r"An executable named `([^`]+)` is not provided by package `([^`]+)`")
UVX_AVAILABLE = re.compile(r"The following executables are available:(.*?)(?:Use `uvx|$)", re.S)


def stderr_text(res: dict) -> str:
    tail = res.get("stderr_tail") or []
    return "\n".join(tail) if isinstance(tail, list) else str(tail)


def uvx_entrypoint(text: str, identifier: str) -> str | None:
    """Resolve the real console-script name from uv's 'not provided' error.

    Returns None when the error is absent or uv named no alternative, so the
    caller falls through to the original (correctly recorded) failure.
    """
    if not text or not UVX_NO_EXE.search(text):
        return None
    m = UVX_AVAILABLE.search(text)
    if not m:
        return None
    names = [ln.strip(" \t-") for ln in m.group(1).splitlines()]
    names = [n for n in names if n and not n.startswith("Use `")]
    if not names:
        return None
    if len(names) == 1:
        return names[0]
    # Several scripts. Prefer an exact hyphen/underscore variant of the package
    # name, then a uniquely MCP-looking script, then the shortest candidate --
    # ambiguity is recorded so these can be audited rather than silently guessed.
    norm = identifier.replace("-", "_")
    for n in names:
        if n.replace("-", "_") == norm:
            return n
    mcpish = [n for n in names if "mcp" in n.lower()]
    if len(mcpish) == 1:
        return mcpish[0]
    return sorted(mcpish or names, key=len)[0]


# Isolation applied to EVERY container (install and probe). The install phase is
# the most dangerous moment -- npm postinstall / PyPI build scripts run arbitrary
# code with network on -- so it gets the same caps as probing, minus the network
# cut (installs need the registry). cap-drop ALL + no-new-privileges neuter
# privilege escalation; resource caps bound a hostile install.
HARDENING = [
    "--memory", "768m", "--cpus", "1", "--pids-limit", "256",
    "--security-opt", "no-new-privileges", "--cap-drop", "ALL",
]


def prime_cmd(pkg: dict) -> list[str]:
    """Online, hardened install-only pass that populates the shared cache volume."""
    base = ["docker", "run", "--rm", "--label", CENSUS_LABEL] + HARDENING
    if pkg["registryType"] == "npm":
        return base + ["-v", "mcpprobe-npm:/root/.npm", NODE_IMAGE,
                       "npm", "exec", "-y", f"--package={_pkg_spec(pkg)}", "--", "true"]
    return base + ["-v", "mcpprobe-uv:/root/.cache/uv", UV_IMAGE,
                   "uvx", "--from", _pkg_spec(pkg), "python", "-c", "0"]


def docker_cmd(pkg: dict, offline: bool = False, entrypoint: str | None = None,
               with_args: bool = True) -> list[str]:
    base = (["docker", "run", "--rm", "-i", "--init", "--label", CENSUS_LABEL]
            + HARDENING)
    if offline:
        base += ["--network", "none"]
    # The persistent package cache is only needed for the two-phase offline probe
    # (prime populates it, probe reads it offline). In online single-phase mode we
    # deliberately omit it so each --rm container is fully ephemeral and disk usage
    # stays flat -- essential for a full-ecosystem census on a fixed-size volume.
    cache = offline
    rt_args = render_args(pkg.get("runtimeArguments")) if with_args else []
    pk_args = render_args(pkg.get("packageArguments")) if with_args else []
    if pkg["registryType"] == "npm":
        run = (["npx", "-y"] + (["--offline"] if offline else []) + rt_args
               + [_pkg_spec(pkg)] + pk_args)
        vol = ["-v", "mcpprobe-npm:/root/.npm"] if cache else []
        return base + vol + [NODE_IMAGE] + run
    spec = _pkg_spec(pkg)
    launch = ["--from", spec, entrypoint] if entrypoint else [spec]
    run = ["uvx"] + (["--offline"] if offline else []) + rt_args + launch + pk_args
    vol = ["-v", "mcpprobe-uv:/root/.cache/uv"] if cache else []
    return base + vol + [UV_IMAGE] + run


def image_digests() -> dict:
    """Resolve each base image tag to its content digest.

    Tags move. Recording the digest is what lets a later run say whether it used
    the same image, and the first census recorded neither.
    """
    out = {}
    for image in (NODE_IMAGE, UV_IMAGE):
        try:
            r = subprocess.run(["docker", "image", "inspect", image, "--format",
                                "{{index .RepoDigests 0}}"],
                               capture_output=True, text=True, timeout=30)
            out[image] = r.stdout.strip() or None
        except Exception:  # noqa: BLE001
            out[image] = None
    return out


def harness_commit() -> str:
    """Git commit of the harness, stamped into every result for provenance."""
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=Path(__file__).resolve().parent, capture_output=True,
                             text=True, timeout=10)
        h = out.stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"],
                              cwd=Path(__file__).resolve().parent, capture_output=True,
                              text=True, timeout=10).stdout.strip()
        if h:
            return h + ("-dirty" if dirty else "")
    except Exception:  # noqa: BLE001
        pass
    # The census ran from a copy of the harness with no .git, which stamped every row
    # "unknown". Fall back to a content hash of the harness sources so a row can still
    # be matched to the exact code that produced it.
    import hashlib
    here = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for src in sorted(here.glob("*.py")):
        digest.update(src.name.encode())
        digest.update(src.read_bytes())
    return "sha256:" + digest.hexdigest()[:16]



def reap_orphans(max_age_s: float, stop: threading.Event, period_s: float = 60.0):
    """Kill containers that outlived their probe.

    When a step times out, subprocess kills the local `docker run` client, but the
    container goes on running on the daemon. Each one holds its full memory
    reservation, so across a full-ecosystem census they accumulate until the host
    runs out of memory and the kernel starts killing probes that would otherwise
    have succeeded -- which the analysis then reads as servers that failed to
    start. The first census was measured with this leak in place.

    The longest a container can legitimately live is the install budget plus the
    probe timeout, so anything older than `max_age_s` is an orphan whose verdict
    has already been written.
    """
    while not stop.wait(period_s):
        try:
            out = subprocess.run(
                ["docker", "ps", "-q", "--filter", f"label={CENSUS_LABEL}"],
                capture_output=True, text=True, timeout=30).stdout.split()
        except Exception:  # noqa: BLE001 - the reaper must never end the census
            continue
        now = dt.datetime.now(dt.timezone.utc)
        for cid in out:
            try:
                started = subprocess.run(
                    ["docker", "inspect", "-f", "{{.State.StartedAt}}", cid],
                    capture_output=True, text=True, timeout=30).stdout.strip()
                age = (now - dt.datetime.fromisoformat(started)).total_seconds()
                if age > max_age_s:
                    subprocess.run(["docker", "kill", cid], capture_output=True,
                                   timeout=30)
                    print(f"  reaped orphaned container {cid[:12]} "
                          f"({age / 60:.0f} min old)", flush=True)
            except Exception:  # noqa: BLE001
                continue


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--all", action="store_true",
                    help="probe every eligible server, ignoring --n and --offset")
    ap.add_argument("--offset", type=int, default=0,
                    help="skip first N shuffled candidates (avoids resampling prior batches)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--offline-probe", action="store_true",
                    help="two-phase: online install pass, then probe with --network=none")
    ap.add_argument("--skip-done", action="store_true",
                    help="skip servers already present in probe_results.jsonl (resume)")
    ap.add_argument("--only", default=None,
                    help="JSON list of server names; probe only these (a targeted "
                         "re-probe through the same code path as the census)")
    ap.add_argument("--out", default=None,
                    help="write results here instead of data/probe_results.jsonl")
    ap.add_argument("--no-args", action="store_true",
                    help="launch without registry-declared arguments, as the July "
                         "census did; for reproducing that run")
    args = ap.parse_args()

    global OUT
    if args.out:
        OUT = Path(args.out)

    # Twice the longest legitimate container life (install budget plus probe),
    # so a slow-but-live container is never taken for an orphan.
    stop_reaper = threading.Event()
    threading.Thread(target=reap_orphans,
                     args=(2 * (args.timeout + 120) + args.timeout, stop_reaper),
                     daemon=True).start()

    done_names: set[str] = set()
    if args.skip_done and OUT.exists():
        with OUT.open(encoding="utf-8") as f:
            done_names = {json.loads(l).get("server_name") for l in f}

    candidates = []
    with FRAME.open(encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            if entry["meta"].get("status") != "active":
                continue
            s = entry["server"]
            pkgs = list(eligible_packages(s))
            if pkgs:
                candidates.append({"name": s["name"], "version": s.get("version"),
                                   "pkg": pkgs[0]})
    if args.only:
        wanted = set(json.loads(Path(args.only).read_text(encoding="utf-8")))
        candidates = [c for c in candidates if c["name"] in wanted]
        print(f"restricted to {len(candidates)} of {len(wanted)} listed servers")
    print(f"eligible candidates in frame: {len(candidates)}")
    random.Random(args.seed).shuffle(candidates)
    if done_names:
        candidates = [c for c in candidates if c["name"] not in done_names]
        print(f"resume: {len(done_names)} already probed, {len(candidates)} remaining")
    sample = candidates if args.all else candidates[args.offset : args.offset + args.n]
    print(f"probing {len(sample)} servers")

    lock = threading.Lock()
    done = 0

    def run_one(c):
        # Retry the whole server up to 3 times if the DOCKER ENGINE (not the
        # package) fails, waiting for the engine to heal in between. This prevents
        # a transient engine crash from being mis-recorded as install-error.
        for attempt in range(3):
            primed = None
            if args.offline_probe:
                # Populate cache online (no probing), then measure fully offline so
                # no server code has network access during the conformance probe.
                proc = subprocess.run(prime_cmd(c["pkg"]), capture_output=True,
                                      text=True, timeout=args.timeout + 120)
                primed = proc.returncode == 0
                if not primed:
                    if is_docker_error(proc.stderr):
                        if wait_for_docker():
                            continue  # engine healed; retry this server
                        return {"_docker_dead": True, **_tag(c, primed)}
                    res = {"started": False, "handshake_ok": False,
                           "failure_class": "install-error",
                           "checks": [{"id": "server-initialize", "verdict": "fail",
                                       "detail": (proc.stderr or "")[-300:]}]}
                    res.update(_tag(c, primed))
                    return res
            res = probe(docker_cmd(c["pkg"], offline=args.offline_probe,
                                        with_args=not args.no_args), args.timeout)
            # A launch failure whose stderr looks like an engine fault is retried too.
            launch_err = next((ch for ch in res.get("checks", [])
                               if ch["id"] == "launch"), None)
            if launch_err and is_docker_error("\n".join(res.get("stderr_tail") or [])
                                              + launch_err.get("detail", "")):
                if wait_for_docker():
                    continue
                return {"_docker_dead": True, **_tag(c, primed)}
            # PyPI entrypoint recovery. The package installed but its console
            # script is not named after the package, so uv never launched it.
            # Relaunch once with the script uv itself named. Both outcomes are
            # stamped so the analysis can report the naive-convention yield and
            # the entrypoint-corrected yield separately.
            if not res.get("handshake_ok") and c["pkg"]["registryType"] == "pypi":
                ep = uvx_entrypoint(stderr_text(res), c["pkg"]["identifier"])
                if ep:
                    retry = probe(docker_cmd(c["pkg"], offline=args.offline_probe,
                                                 with_args=not args.no_args,
                                             entrypoint=ep), args.timeout)
                    retry["entrypoint_mismatch"] = True
                    retry["entrypoint_resolved"] = ep
                    retry["naive_handshake_ok"] = False
                    res = retry
            res.update(_tag(c, primed))
            return res
        # Exhausted retries with the engine still misbehaving.
        return {"_docker_dead": True, **_tag(c, None)}

    commit = harness_commit()
    digests = image_digests()
    run_started = dt.datetime.now(dt.timezone.utc).isoformat()

    def _tag(c, primed):
        """Provenance carried by every row, so a result can be traced to the code,
        the images and the settings that produced it."""
        return {"server_name": c["name"], "server_version": c["version"],
                "registry_type": c["pkg"]["registryType"],
                "identifier": c["pkg"]["identifier"], "primed": primed,
                "harness_commit": commit,
                "probe_condition": "offline" if args.offline_probe else "single-phase",
                "request_timeout_s": args.timeout,
                "max_frame_chars": mcpprobe.MAX_FRAME_CHARS,
                "image_digests": digests,
                # The July census launched without registry-declared arguments.
                # Recorded so the two launch conditions stay distinguishable.
                "launch_args": ([] if args.no_args else
                                render_args(c["pkg"].get("runtimeArguments"))
                                + render_args(c["pkg"].get("packageArguments"))),
                "run_started_at": run_started,
                "probed_at": dt.datetime.now(dt.timezone.utc).isoformat()}

    OUT.parent.mkdir(exist_ok=True)
    tdir = DATA / "transcripts"
    tdir.mkdir(exist_ok=True)

    def stash_transcript(res):
        """Move the raw JSON-RPC transcript to its own file; keep results lean."""
        tr = res.pop("transcript", None)
        if tr is None:
            return
        safe = (res.get("server_name") or "unknown").replace("/", "__")
        (tdir / f"{safe}.json").write_text(
            json.dumps({"harness_commit": res.get("harness_commit"),
                        "cmd": res.get("cmd"), "transcript": tr}, ensure_ascii=False),
            encoding="utf-8")

    dead_streak = 0
    with OUT.open("a", encoding="utf-8") as out, ThreadPoolExecutor(args.workers) as ex:
        futures = {ex.submit(run_one, c): c for c in sample}
        for fut in as_completed(futures):
            c = futures[fut]
            try:
                res = fut.result()
            except Exception as e:  # noqa: BLE001 - one bad server must not kill the batch
                res = {"server_name": c["name"], "identifier": c["pkg"]["identifier"],
                       "registry_type": c["pkg"]["registryType"], "batch_error": str(e)}
            with lock:
                # Engine-dead results are NOT recorded: they carry no information
                # about the server and would poison the dataset. Left unwritten,
                # --skip-done re-runs them next time. Abort if the engine is
                # persistently dead so we fail loudly instead of silently skipping.
                if res.get("_docker_dead"):
                    dead_streak += 1
                    print(f"[skip:{c['name']}] docker engine unavailable "
                          f"(streak {dead_streak})")
                    if dead_streak >= 15:
                        print("ABORT: docker engine persistently unavailable; "
                              "fix Docker then rerun with --skip-done to resume.")
                        break
                    continue
                dead_streak = 0
                stash_transcript(res)
                out.write(json.dumps(res, ensure_ascii=False) + "\n")
                out.flush()
                done += 1
                verdicts = {ch["id"]: ch["verdict"] for ch in res.get("checks", [])}
                print(f"[{done}/{len(sample)}] {c['name']}: "
                      f"handshake={res.get('handshake_ok')} {verdicts}")

    # Funnel summary
    results = [json.loads(l) for l in OUT.open(encoding="utf-8")]
    n = len(results)
    started = sum(1 for r in results if r.get("started"))
    hs = sum(1 for r in results if r.get("handshake_ok"))
    print(f"\nfunnel (cumulative in {OUT.name}): sampled={n} started={started} handshake={hs}")


if __name__ == "__main__":
    main()
