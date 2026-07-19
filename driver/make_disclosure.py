"""Generate a PRIVATE responsible-disclosure log from probe results.

Security-relevant findings (a server that crashes or hangs on a malformed frame
is a denial-of-service primitive; a server that corrupts its stdout channel can
desync a client) must be reported to maintainers BEFORE the paper is public, and
must never appear as named-and-shamed entries in the paper itself. This script
extracts those findings, resolves a maintainer contact from the registry
repository URL, and writes a private log that is git-ignored.

The paper cites only AGGREGATES and anonymized case studies. This file is the
operational bridge to disclosure; it is not a paper artifact.

Usage:
  python make_disclosure.py   # writes data/DISCLOSURE_PRIVATE.md (git-ignored)
"""

import argparse
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
FRAME = DATA / "frame_latest.jsonl"
OUT = DATA / "DISCLOSURE_PRIVATE.md"

# check_id, verdict -> (severity, what to tell the maintainer)
SECURITY_RELEVANT = {
    ("malformed-json", "fail"): ("high", "Server crashes or hangs on a malformed JSON-RPC frame (DoS primitive). A single bad frame from a client desyncs or kills the server."),
    ("stdout-purity", "fail"): ("medium", "Server writes non-protocol bytes to stdout, corrupting the stdio channel and potentially desyncing any connected client."),
    ("tools-call-unknown", "fail"): ("medium", "Unknown tool call is not safely rejected (crash/hang/unexpected success), which a malicious or buggy client can trigger."),
}


def repo_url(server: dict) -> str:
    return (server.get("repository") or {}).get("url", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=str(DATA / "probe_final.jsonl"))
    args = ap.parse_args()

    # Map server name -> repository URL from the frame.
    repos = {}
    with FRAME.open(encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            repos[e["server"]["name"]] = repo_url(e["server"])

    findings = []
    with open(args.inp, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if not r.get("handshake_ok"):
                continue
            for c in r.get("checks", []):
                key = (c["id"], c["verdict"])
                if key in SECURITY_RELEVANT:
                    sev, desc = SECURITY_RELEVANT[key]
                    findings.append({
                        "server": r.get("server_name"), "sev": sev,
                        "check": c["id"], "desc": desc,
                        "detail": c.get("detail", ""),
                        "repo": repos.get(r.get("server_name"), "?"),
                        "identifier": r.get("identifier"),
                        "commit": r.get("harness_commit", "?"),
                    })

    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda x: order.get(x["sev"], 9))

    lines = [
        "# PRIVATE — Responsible Disclosure Log (DO NOT PUBLISH)",
        "",
        "Report each item to the maintainer BEFORE the paper is public. The paper",
        "reports only aggregates and anonymized case studies. Track disclosure dates below.",
        "",
        f"Total security-relevant findings: **{len(findings)}**",
        "",
    ]
    for i, f in enumerate(findings, 1):
        lines += [
            f"## {i}. [{f['sev'].upper()}] {f['server']}",
            f"- Package: `{f['identifier']}`",
            f"- Repository: {f['repo'] or '(none listed)'}",
            f"- Check: `{f['check']}` — {f['desc']}",
            f"- Evidence: {f['detail'][:200]}",
            f"- Harness commit: `{f['commit']}`",
            "- Disclosure status: ☐ not yet contacted   ☐ reported (date: ____)   ☐ fixed",
            "",
        ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT} ({len(findings)} security-relevant findings)")
    for f in findings:
        print(f"  [{f['sev']:6}] {f['server']}  ({f['check']})")


if __name__ == "__main__":
    main()
