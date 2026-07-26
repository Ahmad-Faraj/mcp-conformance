"""Re-probe the PyPI servers that the census never actually launched.

`uvx <package>` resolves only when the package's console script is named after the
package. Servers whose script has a different name installed correctly but were
recorded as startup failures, which biases PyPI runnability downward relative to npm
(whose `npx` resolves the entry point from package.json). This script finds every
such server in the census, resolves its real entry point from uv's own error, and
re-probes it via `uvx --from <spec> <script>`.

Results are appended one line at a time and completed servers are skipped on
restart, so the run survives a Docker engine crash and can be resumed.

Usage:
  python reprobe_entrypoints.py [--out data/entrypoint_reprobe.jsonl]
                                [--timeout 90] [--workers 3] [--limit N]
"""

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcpprobe import probe  # noqa: E402
from run_batch import docker_cmd, is_docker_error, stderr_text, uvx_entrypoint, wait_for_docker  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=str(DATA / "probe_final.jsonl"))
    ap.add_argument("--out", default=str(DATA / "entrypoint_reprobe.jsonl"))
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    # Key on (identifier, version), not identifier alone: 10 affected packages
    # appear under more than one registry entry, sometimes at different versions,
    # and those are genuinely different artifacts that must each be probed. Entries
    # sharing an identifier AND a version are true duplicates and are probed once.
    def key(r):
        return (r.get("identifier"), r.get("server_version"))

    out = Path(args.out)
    done = set()
    if out.exists():
        with out.open(encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(key(json.loads(line)))
                except Exception:  # noqa: BLE001 - tolerate a torn final line
                    pass

    cands, queued = [], set()
    with Path(args.inp).open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("handshake_ok"):
                continue
            ep = uvx_entrypoint(stderr_text(r), r.get("identifier", ""))
            if ep and key(r) not in done and key(r) not in queued:
                queued.add(key(r))
                cands.append((r, ep))

    if args.limit:
        cands = cands[: args.limit]
    print(f"affected servers: {len(cands) + len(done)} | already done: {len(done)} | "
          f"to probe now: {len(cands)}", flush=True)

    lock = threading.Lock()
    fh = out.open("a", encoding="utf-8")
    counter = [0]

    def run(item):
        r, ep = item
        pkg = {"registryType": "pypi", "identifier": r["identifier"],
               "version": r.get("server_version")}
        res = None
        for _ in range(2):
            try:
                res = probe(docker_cmd(pkg, offline=False, entrypoint=ep), args.timeout)
            except Exception as e:  # noqa: BLE001
                res = {"handshake_ok": False, "failure_class": f"harness-error: {e}"}
            # Retry once if the engine, not the package, is what failed.
            if is_docker_error(stderr_text(res)) and wait_for_docker():
                continue
            break

        rec = {
            "identifier": r["identifier"],
            "server_name": r.get("server_name"),
            "server_version": r.get("server_version"),
            "entrypoint": ep,
            "handshake_ok": bool(res.get("handshake_ok")),
            "failure_class": res.get("failure_class"),
            "negotiated_version": res.get("negotiated_version"),
            "tools_count": res.get("tools_count"),
            "checks": [{"id": c["id"], "verdict": c["verdict"]}
                       for c in res.get("checks", [])],
        }
        with lock:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            counter[0] += 1
            print(f"  [{counter[0]}/{len(cands)}] {r['identifier']} -> {ep} : "
                  f"handshake={rec['handshake_ok']}", flush=True)
        return rec

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            list(ex.map(run, cands))
    finally:
        fh.close()

    allrows = [json.loads(l) for l in out.open(encoding="utf-8") if l.strip()]
    ok = sum(1 for r in allrows if r["handshake_ok"])
    print("\n=== RESULT ===", flush=True)
    print(f"  re-probed     : {len(allrows)}", flush=True)
    print(f"  now handshake : {ok} ({100*ok/len(allrows):.1f}%)", flush=True)
    print(f"  wrote {out}", flush=True)


if __name__ == "__main__":
    main()
