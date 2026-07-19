"""Assemble the clean canonical dataset from collected probe data.

Given the study machine's Docker instability, a subset of offline-probe rows
were invalidated when the engine crashed mid-run (recorded as install-error but
carrying a Docker-daemon error in stderr, not a package error). This script:

  1. Dedupes probe_dev.jsonl by server name.
  2. EXCLUDES rows invalidated by the infrastructure fault (primed is False AND
     stderr shows a Docker-engine error, not a real package error).
  3. Re-classifies any non-handshake rows missing a failure_class (earliest
     pilot rows) from their stderr.
  4. Tags each row with its probe condition (online single-phase vs offline
     two-phase) so analyses can check condition-independence.
  5. Writes the clean dataset to probe_final.jsonl.

The two conditions are pooled for conformance analysis (server-side protocol
behavior is condition-independent) and reported side-by-side for the funnel.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcpprobe import classify_failure  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
SRC = DATA / "probe_dev.jsonl"
OUT = DATA / "probe_final.jsonl"

DOCKER_SIGNS = ("cannot connect to the docker", "500 internal server error",
                "docker daemon", "error during connect",
                "the system cannot find the file specified",
                "is the docker daemon running")


def row_text(r: dict) -> str:
    parts = list(r.get("stderr_tail") or [])
    for c in r.get("checks", []):
        parts.append(c.get("detail", ""))
    return " ".join(parts).lower()


def is_infra_contaminated(r: dict) -> bool:
    # Only prime-phase failures can be infra-contaminated; a real handshake or a
    # real package error is trustworthy.
    if r.get("primed") is not False:
        return False
    return any(s in row_text(r) for s in DOCKER_SIGNS)


def main() -> None:
    by = {}
    with SRC.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            by[r.get("server_name") or str(r.get("cmd"))] = r
    rows = list(by.values())

    kept, excluded = [], 0
    for r in rows:
        if is_infra_contaminated(r):
            excluded += 1
            continue
        # Probe condition tag.
        r["probe_condition"] = "offline-two-phase" if r.get("primed") is not None else "online-single-phase"
        # Backfill failure_class for earliest pilot rows.
        if not r.get("handshake_ok") and not r.get("failure_class"):
            r["failure_class"] = classify_failure(r.get("exit_code"),
                                                  r.get("stderr_tail") or [])
        kept.append(r)

    with OUT.open("w", encoding="utf-8") as f:
        for r in kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    hs = sum(1 for r in kept if r.get("handshake_ok"))
    on = sum(1 for r in kept if r["probe_condition"] == "online-single-phase")
    off = len(kept) - on
    print(f"source rows (deduped):     {len(rows)}")
    print(f"excluded (infra-contam):   {excluded}")
    print(f"clean canonical dataset:   {len(kept)}  -> {OUT.name}")
    print(f"  online single-phase:     {on}")
    print(f"  offline two-phase:       {off}")
    print(f"  completed handshake:     {hs} ({100*hs/len(kept):.1f}%)")


if __name__ == "__main__":
    main()
