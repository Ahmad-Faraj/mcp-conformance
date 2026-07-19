"""Build the conformance violation & failure taxonomy from probe transcripts.

Two dimensions:
  (A) Startup failure taxonomy  — why servers never reach a handshake (RQ1).
  (B) Conformance violation taxonomy — how handshaking servers deviate from the
      MCP spec / robustness expectations (RQ2-RQ4).

Each finding gets a stable code, a severity, and the agent-facing consequence
(the "so what"). Emits a per-server long-format CSV (one row per finding) and a
category-count table, both consumed by the stats/figures step and the paper.

Usage:
  python taxonomy.py [--in data/probe_results.jsonl] [--csv data/findings.csv]
"""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

# Startup failure codes -> (severity, agent-facing consequence)
STARTUP = {
    "install-not-found": ("blocker", "package unresolvable; server unusable"),
    "install-error": ("blocker", "dependency/build failure; server unusable"),
    "crash-python-exception": ("blocker", "uncaught exception at startup"),
    "crash-with-error-output": ("blocker", "process aborts before handshake"),
    "crash-exit-1": ("blocker", "nonzero exit before handshake"),
    "crash-exit-2": ("blocker", "nonzero exit before handshake"),
    "crash-exit-127": ("blocker", "missing runtime/entrypoint"),
    "exit-silent": ("blocker", "exits 0 without serving; silent no-op"),
    "hang-no-reply": ("blocker", "connects but never answers initialize; agent hangs"),
}

# Conformance/robustness violation codes keyed by (check_id, verdict).
# severity, code, consequence
VIOLATION = {
    ("server-initialize", "fail"): ("critical", "V-INIT", "handshake result malformed"),
    ("ping", "fail"): ("minor", "V-PING", "ping not answered per spec"),
    ("tools-list", "fail"): ("major", "V-TOOLS-SHAPE", "tools/list violates schema (missing name/inputSchema)"),
    ("tools-schema-valid", "fail"): ("major", "V-SCHEMA-INVALID", "declared inputSchema is not valid JSON Schema; agent cannot rely on it"),
    ("tools-call-unknown", "error-as-result"): ("spec-divergence", "D-ERR-AS-RESULT", "unknown tool returned as isError result, not JSON-RPC -32602"),
    ("tools-call-unknown", "warn"): ("minor", "V-ERR-CODE", "unknown tool errors with a non-standard code"),
    ("tools-call-unknown", "fail"): ("major", "V-UNKNOWN-NOERR", "unknown tool not rejected (crash/hang/success)"),
    ("tools-call-invalid-args", "fail"): ("major", "V-NO-TYPECHECK", "wrong-typed args silently accepted; agent gets confident-wrong output"),
    ("malformed-json", "fail"): ("critical", "V-MALFORMED-DIES", "server dies/hangs on malformed frame; availability risk"),
    ("stdout-purity", "fail"): ("major", "V-STDOUT-NOISE", "non-protocol bytes on stdout corrupt the stdio channel"),
}


def load(path: Path) -> list[dict]:
    by_name: dict[str, dict] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            by_name[r.get("server_name") or json.dumps(r.get("cmd"))] = r
    return list(by_name.values())


def findings_for(r: dict):
    name = r.get("server_name", "?")
    reg = r.get("registry_type", "?")
    if not r.get("handshake_ok"):
        code = r.get("failure_class", "?")
        sev, cons = STARTUP.get(code, ("blocker", "did not reach handshake"))
        yield {"server": name, "registry": reg, "dimension": "startup",
               "code": code, "severity": sev, "consequence": cons,
               "detail": _init_detail(r)}
        return
    for c in r.get("checks", []):
        key = (c["id"], c["verdict"])
        if key in VIOLATION:
            sev, code, cons = VIOLATION[key]
            yield {"server": name, "registry": reg, "dimension": "conformance",
                   "code": code, "severity": sev, "consequence": cons,
                   "detail": c.get("detail", "")[:200]}


def _init_detail(r: dict) -> str:
    for c in r.get("checks", []):
        if c["id"] == "server-initialize":
            return c.get("detail", "")[:200]
    return (r.get("stderr_tail") or [""])[-1][:200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=str(DATA / "probe_results.jsonl"))
    ap.add_argument("--csv", default=str(DATA / "findings.csv"))
    args = ap.parse_args()

    rows = load(Path(args.inp))
    findings = [f for r in rows for f in findings_for(r)]

    with open(args.csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["server", "registry", "dimension",
                                          "code", "severity", "consequence", "detail"])
        w.writeheader()
        w.writerows(findings)

    n = len(rows)
    hs = sum(1 for r in rows if r.get("handshake_ok"))
    print(f"servers: {n} | handshake ok: {hs} | findings: {len(findings)}\n")

    print("== Startup failure taxonomy (of non-handshaking servers) ==")
    sc = Counter(f["code"] for f in findings if f["dimension"] == "startup")
    for code, cnt in sc.most_common():
        sev, cons = STARTUP.get(code, ("?", "?"))
        print(f"  [{sev:9}] {code:26} {cnt:4}  {cons}")

    print("\n== Conformance violation taxonomy (of handshaking servers) ==")
    vc = Counter(f["code"] for f in findings if f["dimension"] == "conformance")
    sev_of = {code: sev for (_, _), (sev, code, _) in VIOLATION.items()}
    cons_of = {code: cons for (_, _), (_, code, cons) in VIOLATION.items()}
    for code, cnt in vc.most_common():
        rate = f"{100 * cnt / hs:.1f}%" if hs else "-"
        print(f"  [{sev_of.get(code, '?'):15}] {code:18} {cnt:4} ({rate:>6} of responders)  {cons_of.get(code, '')}")

    print(f"\nwrote {args.csv}")


if __name__ == "__main__":
    main()
