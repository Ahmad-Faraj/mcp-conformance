"""Generate ready-to-send maintainer notifications for security-relevant findings.

The paper states that security-relevant findings are reported to maintainers before
publication, so that has to actually happen. This builds the kit:

  data/disclosure_kit/CONTACTS.csv     one row per affected server, with repo URL
  data/disclosure_kit/SDK_REPORT.md    the systemic report for SDK maintainers
  data/disclosure_kit/notices/*.md     one paste-ready notice per server
  data/disclosure_kit/README.md        process, tiers, and tracking

Notices are drafts. Nothing is sent by this script.

Usage:
  python make_disclosure_kit.py [--in data/probe_final.jsonl]
"""

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

FINDINGS = {
    ("malformed-json", "fail"): (
        "high", "Server crashes or stops responding after a malformed JSON-RPC frame",
        "A single syntactically invalid frame from a client ends the session. Any "
        "client that garbles one message -- or any peer that sends one deliberately -- "
        "can terminate the server. This is a denial-of-service primitive.",
        "Wrap frame parsing so a JSON decode error is answered with a JSON-RPC "
        "parse error (-32700) and the read loop continues, instead of propagating.",
    ),
    ("stdout-purity", "fail"): (
        "medium", "Non-protocol output on stdout corrupts the stdio channel",
        "Under the stdio transport, stdout carries protocol messages only. Log lines "
        "or banners printed to stdout are parsed as protocol traffic and can "
        "desynchronise a connected client.",
        "Send all logging and diagnostics to stderr. Reserve stdout for protocol "
        "messages.",
    ),
    ("tools-call-unknown", "fail"): (
        "medium", "Call to an unknown tool is not safely rejected",
        "Calling a tool that does not exist produces a crash, a hang, or an "
        "apparently successful result rather than an error. A client that requests a "
        "stale or mistyped tool name can hang or mislead the agent driving it.",
        "Return a JSON-RPC error for unknown tool names (the specification "
        "categorises this under protocol errors), or at minimum an isError result.",
    ),
}

NOTICE = """# {title}

Hello, and apologies for the unsolicited report.

Your MCP server **`{server}`** (`{identifier}`) was included in an automated
conformance study of publicly registered Model Context Protocol servers. The study
installed and executed every eligible server in the official registry and drove it
through a set of protocol checks. One result looked worth reporting to you directly.

## What we observed

**{title}** (severity: {severity})

{impact}

Observed during the check `{check}`:

```
{evidence}
```

## Reproducing it

The harness is open source. With Docker installed:

```bash
git clone https://github.com/Ahmad-Faraj/mcp-conformance
cd mcp-conformance
python driver/mcpprobe.py --cmd "{cmd}"
```

The relevant verdict is `{check}` in the JSON output.

## Suggested fix

{fix}

## About the study

This is part of an academic measurement study of MCP server conformance. **Your
server is not named in the paper or the public dataset** -- results are reported only
in aggregate, and servers behind security-relevant findings are pseudonymised. We are
contacting maintainers before publication so that anyone who wants to fix an issue
can do so first. There is no deadline attached and no follow-up is required.

If this is a false positive, we would genuinely like to know: the harness may be
wrong, and we will correct both it and the dataset.

Repository: https://github.com/Ahmad-Faraj/mcp-conformance
"""

SDK_REPORT = """# Systemic finding: unknown-tool responses diverge from the specification

This report goes to the maintainers of the MCP specification and the official SDKs.
It concerns a defaults question rather than a bug in any one server.

## Summary

In a complete execution census of **{n_probed:,} publicly registered MCP servers**
(the full eligible frame of a {n_frame:,}-server registry snapshot), **{ear_pct}** of
the {n_resp:,} servers that completed a handshake answered a call to a *non-existent
tool* with a successful response carrying `isError: true`, rather than a JSON-RPC
protocol error.

The specification's error-handling section categorises "unknown tools" under
*protocol errors* and illustrates the case with a `-32602` example, in contrast to
*tool execution errors* reported as a result with `isError`. That categorisation is
expressed in prose and an example; it uses no RFC-2119 keyword. We therefore do not
characterise this as a violation, and this report is not a claim that anyone is out
of compliance.

## The behaviour tracks the SDK, not the server author

| SDK family | servers | answer with isError |
|---|---|---|
{sdk_rows}

The official reference servers show the same behaviour. Servers that emit a protocol
error are a small minority, and are mostly built on the TypeScript SDK -- so the
conforming behaviour is reachable within the SDK, it is simply not the default. The
pattern also reproduces through third-party wrappers, which inherit the same default
from the SDKs they build on.

## Why the distinction has practical consequences

A protocol error is handled by client *code*: a client library can deterministically
detect that a call never executed and route around it. An `isError` result arrives
through the success path and lands in the model's context as ordinary tool output,
where interpreting it becomes the model's job. The divergence moves error handling
from deterministic code into probabilistic interpretation, and it makes
"this tool does not exist" indistinguishable from "the tool ran and reported a
problem" for any client that does not special-case the message text.

## What would resolve it

Either direction would work, and either is better than the present ambiguity:

1. Make the categorisation normative (`MUST`/`SHOULD`) and align the SDK defaults, or
2. State explicitly that both mechanisms are acceptable, so client authors know they
   must handle both and can stop inferring intent from message strings.

Because the behaviour is set by a handful of SDK defaults rather than by thousands of
independent decisions, a change at that layer would move the entire ecosystem at once.

## Data

Harness, methodology and the full disclosure-filtered dataset:
https://github.com/Ahmad-Faraj/mcp-conformance
"""


def slug(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s or "unknown")[:80]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=str(DATA / "probe_final.jsonl"))
    ap.add_argument("--out", default=str(DATA / "disclosure_kit"))
    args = ap.parse_args()

    out = Path(args.out)
    (out / "notices").mkdir(parents=True, exist_ok=True)

    repos = {}
    with (DATA / "frame_latest.jsonl").open(encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            s = e["server"]
            repos[s["name"]] = (s.get("repository") or {}).get("url", "")

    rows = {}
    with open(args.inp, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            rows[r.get("server_name")] = r

    contacts, tiers = [], Counter()
    for name, r in rows.items():
        if not r.get("handshake_ok"):
            continue
        for c in r.get("checks", []):
            key = (c["id"], c["verdict"])
            if key not in FINDINGS:
                continue
            sev, title, impact, fix = FINDINGS[key]
            tiers[sev] += 1
            cmd = " ".join(r.get("cmd") or []) or "<see dataset>"
            body = NOTICE.format(
                title=title, server=name, identifier=r.get("identifier", "?"),
                severity=sev.upper(), impact=impact, check=c["id"],
                evidence=(c.get("detail") or "(no additional detail captured)")[:400],
                cmd=cmd, fix=fix)
            fn = f"{sev}__{slug(name)}__{c['id']}.md"
            (out / "notices" / fn).write_text(body, encoding="utf-8")
            contacts.append({
                "server": name, "identifier": r.get("identifier", ""),
                "severity": sev, "check": c["id"],
                "repository": repos.get(name, ""), "notice_file": fn,
                "status": "not_yet_contacted", "date_reported": "",
            })

    with (out / "CONTACTS.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(contacts[0].keys()))
        w.writeheader()
        w.writerows(sorted(contacts, key=lambda c: (c["severity"] != "high", c["server"])))

    # Systemic report for the SDK/spec maintainers.
    sdk_counts = {}
    p = DATA / "sdk_attribution.csv"
    if p.exists():
        label = {"none-handrolled": "no known SDK", "unknown": "metadata unavailable"}
        agg = {}
        with p.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                fam = label.get(row["sdk_family"], row["sdk_family"])
                a = agg.setdefault(fam, [0, 0])
                a[0] += 1
                a[1] += 1 if row["unknown_verdict"] == "error-as-result" else 0
        sdk_counts = agg
    sdk_rows = "\n".join(
        f"| `{fam}` | {tot:,} | {100*k/tot:.0f}% |"
        for fam, (tot, k) in sorted(sdk_counts.items(), key=lambda t: -t[1][0]) if tot >= 25)

    n_probed = len(rows)
    resp = [r for r in rows.values() if r.get("handshake_ok")]
    ear = sum(1 for r in resp for c in r.get("checks", [])
              if c["id"] == "tools-call-unknown" and c["verdict"] == "error-as-result")
    n_frame = sum(1 for _ in (DATA / "frame_latest.jsonl").open(encoding="utf-8"))
    (out / "SDK_REPORT.md").write_text(SDK_REPORT.format(
        n_probed=n_probed, n_frame=n_frame, n_resp=len(resp),
        ear_pct=f"{100*ear/len(resp):.1f}%", sdk_rows=sdk_rows), encoding="utf-8")

    (out / "README.md").write_text(f"""# Disclosure kit (PRIVATE -- do not publish)

Generated by `driver/make_disclosure_kit.py`. Drafts only; nothing has been sent.

## Contents

- `CONTACTS.csv` -- {len(contacts)} findings across affected servers, with repository
  URLs and a `status` column to track progress.
- `notices/` -- one paste-ready notice per finding, named `<severity>__<server>__<check>.md`.
  Suitable as a GitHub issue body.
- `SDK_REPORT.md` -- the systemic unknown-tool report for the specification and
  official SDK maintainers. This one matters most: it addresses the root cause.

## Suggested order

1. **Send `SDK_REPORT.md` first**, to the specification and SDK repositories. It is
   the finding with real leverage and it is not about any individual author.
2. **High severity ({tiers['high']} findings)** -- crash/hang on a malformed frame.
   Send these individually; they are genuine availability bugs.
3. **Medium ({tiers['medium']} findings)** -- send in batches. These are correctness
   and hygiene issues, not urgent.

Filing several hundred issues at once will read as spam and will not help anyone.
Prefer the SDK report plus the high-severity set, then work through the rest at a
humane pace.

## Rules

- Do not name individual servers publicly before their maintainer has been contacted.
- If a maintainer says it is a false positive, verify with the harness and correct
  both the harness and the dataset if they are right.
- Record the date in `CONTACTS.csv` as you go; the paper's ethics section states that
  maintainers are notified before publication.
""", encoding="utf-8")

    print(f"wrote {out}")
    print(f"  findings   : {len(contacts)}  (high {tiers['high']}, medium {tiers['medium']})")
    print(f"  notices    : {len(list((out / 'notices').glob('*.md')))}")
    print(f"  contactable: {sum(1 for c in contacts if c['repository'])}/{len(contacts)}")


if __name__ == "__main__":
    main()
