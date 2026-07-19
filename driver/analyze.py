"""Analyze probe results: funnel, verdict distributions, failure classes.

Reads data/probe_results.jsonl (cumulative across batches, deduped by server
name keeping the latest record) and prints the tables that feed the paper's
results section. Optionally writes a machine-readable summary JSON.

Usage:
  python analyze.py [--json out.json]
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
RESULTS = DATA / "probe_results.jsonl"

CHECK_ORDER = [
    "server-initialize", "ping", "tools-list", "tools-schema-valid",
    "tools-call-unknown", "tools-call-invalid-args", "malformed-json",
    "stdout-purity",
]


def load() -> list[dict]:
    by_name: dict[str, dict] = {}
    with RESULTS.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            name = r.get("server_name") or json.dumps(r.get("cmd"))
            by_name[name] = r  # later batches supersede earlier records
    return list(by_name.values())


def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({100 * a / b:.1f}%)" if b else "0/0"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="also write summary JSON to this path")
    args = ap.parse_args()

    rows = load()
    n = len(rows)
    started = [r for r in rows if r.get("started")]
    hs = [r for r in rows if r.get("handshake_ok")]

    print("== Funnel ==")
    print(f"  probed:            {n}")
    print(f"  process started:   {pct(len(started), n)}")
    print(f"  handshake ok:      {pct(len(hs), n)}")

    print("\n== Pre-handshake failure classes ==")
    fc = Counter(r.get("failure_class", "?") for r in rows if not r.get("handshake_ok"))
    for k, v in fc.most_common():
        print(f"  {k:28} {v}")

    print("\n== Handshake yield by registry ==")
    by_reg = defaultdict(lambda: [0, 0])
    for r in rows:
        reg = r.get("registry_type", "?")
        by_reg[reg][1] += 1
        if r.get("handshake_ok"):
            by_reg[reg][0] += 1
    for reg, (ok, tot) in sorted(by_reg.items()):
        print(f"  {reg:8} {pct(ok, tot)}")

    print("\n== Negotiated protocol versions (handshake ok) ==")
    for k, v in Counter(r.get("negotiated_version") for r in hs).most_common():
        print(f"  {str(k):16} {v}")

    print("\n== Check verdicts (handshake ok) ==")
    verdicts: dict[str, Counter] = defaultdict(Counter)
    for r in hs:
        for c in r.get("checks", []):
            verdicts[c["id"]][c["verdict"]] += 1
    header = ["pass", "fail", "warn", "error-as-result", "skip", "error"]
    print(f"  {'check':26}" + "".join(f"{h:>17}" for h in header))
    for cid in CHECK_ORDER:
        cnt = verdicts.get(cid, Counter())
        print(f"  {cid:26}" + "".join(f"{cnt.get(h, 0):>17}" for h in header))

    print("\n== Servers accepting wrong-typed args ==")
    for r in hs:
        for c in r.get("checks", []):
            if c["id"] == "tools-call-invalid-args" and c["verdict"] == "fail":
                print(f"  {r.get('server_name'):55} {c['detail'][:70]}")

    print("\n== stdout-purity violators ==")
    for r in hs:
        for c in r.get("checks", []):
            if c["id"] == "stdout-purity" and c["verdict"] == "fail":
                print(f"  {r.get('server_name'):55} {c['detail'][:70]}")

    print("\n== malformed-json casualties ==")
    for r in hs:
        for c in r.get("checks", []):
            if c["id"] == "malformed-json" and c["verdict"] == "fail":
                print(f"  {r.get('server_name'):55} {c['detail'][:70]}")

    print("\n== Tool counts (handshake ok) ==")
    tc = sorted(r.get("tools_count") or 0 for r in hs)
    if tc:
        mid = tc[len(tc) // 2]
        print(f"  min={tc[0]} median={mid} max={tc[-1]} total={sum(tc)}")

    if args.json:
        summary = {
            "n": n, "started": len(started), "handshake_ok": len(hs),
            "failure_classes": dict(fc),
            "verdicts": {k: dict(v) for k, v in verdicts.items()},
            "negotiated_versions": dict(Counter(r.get("negotiated_version") for r in hs)),
        }
        Path(args.json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
