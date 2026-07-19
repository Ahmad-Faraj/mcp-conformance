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
import random
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcpprobe import probe  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
FRAME = DATA / "frame_latest.jsonl"
OUT = DATA / "probe_results.jsonl"

NODE_IMAGE = "node:22-slim"
UV_IMAGE = "ghcr.io/astral-sh/uv:python3.12-bookworm-slim"


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


def _pkg_spec(pkg: dict) -> str:
    ident, version = pkg["identifier"], pkg.get("version")
    if pkg["registryType"] == "npm":
        return f"{ident}@{version}" if version else ident
    return f"{ident}=={version}" if version else ident


def prime_cmd(pkg: dict) -> list[str]:
    """Online install-only pass that populates the shared cache volume."""
    if pkg["registryType"] == "npm":
        return ["docker", "run", "--rm", "-v", "mcpprobe-npm:/root/.npm", NODE_IMAGE,
                "npm", "exec", "-y", f"--package={_pkg_spec(pkg)}", "--", "true"]
    return ["docker", "run", "--rm", "-v", "mcpprobe-uv:/root/.cache/uv", UV_IMAGE,
            "uvx", "--from", _pkg_spec(pkg), "python", "-c", "0"]


def docker_cmd(pkg: dict, offline: bool = False) -> list[str]:
    base = [
        "docker", "run", "--rm", "-i", "--init",
        "--memory", "768m", "--cpus", "1", "--pids-limit", "256",
        "--security-opt", "no-new-privileges",
    ]
    if offline:
        base += ["--network", "none"]
    if pkg["registryType"] == "npm":
        run = ["npx", "-y"] + (["--offline"] if offline else []) + [_pkg_spec(pkg)]
        return base + ["-v", "mcpprobe-npm:/root/.npm", NODE_IMAGE] + run
    run = ["uvx"] + (["--offline"] if offline else []) + [_pkg_spec(pkg)]
    return base + ["-v", "mcpprobe-uv:/root/.cache/uv", UV_IMAGE] + run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--offset", type=int, default=0,
                    help="skip first N shuffled candidates (avoids resampling prior batches)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--offline-probe", action="store_true",
                    help="two-phase: online install pass, then probe with --network=none")
    ap.add_argument("--skip-done", action="store_true",
                    help="skip servers already present in probe_results.jsonl (resume)")
    args = ap.parse_args()

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
    print(f"eligible candidates in frame: {len(candidates)}")
    random.Random(args.seed).shuffle(candidates)
    if done_names:
        candidates = [c for c in candidates if c["name"] not in done_names]
        print(f"resume: {len(done_names)} already probed, {len(candidates)} remaining")
    sample = candidates[args.offset : args.offset + args.n]

    lock = threading.Lock()
    done = 0

    def run_one(c):
        primed = None
        if args.offline_probe:
            # Populate cache online (no probing), then measure fully offline so
            # no server code has network access during the conformance probe.
            proc = subprocess.run(prime_cmd(c["pkg"]), capture_output=True,
                                  text=True, timeout=args.timeout + 120)
            primed = proc.returncode == 0
            if not primed:
                res = {"started": False, "handshake_ok": False,
                       "failure_class": "install-error",
                       "checks": [{"id": "server-initialize", "verdict": "fail",
                                   "detail": (proc.stderr or "")[-300:]}]}
                res.update(_tag(c, primed))
                return res
        res = probe(docker_cmd(c["pkg"], offline=args.offline_probe), args.timeout)
        res.update(_tag(c, primed))
        return res

    def _tag(c, primed):
        return {"server_name": c["name"], "server_version": c["version"],
                "registry_type": c["pkg"]["registryType"],
                "identifier": c["pkg"]["identifier"], "primed": primed}

    OUT.parent.mkdir(exist_ok=True)
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
