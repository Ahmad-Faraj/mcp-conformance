"""Classify what servers actually return when handed a wrong-typed argument.

The `tools-call-invalid-args` check records whether a server rejects an argument
that violates its own declared schema. It grades a plain success envelope as a
failure to reject. That is correct as a protocol judgement but too coarse for the
question a client cares about, because two very different behaviours land in the
same bucket:

  * the server validated the input and reported the problem in the result *text*,
    without setting `isError` -- non-conformant, but the information is there; and
  * the server executed the tool on input its own schema rejects and returned
    ordinary-looking output -- the information is not there, and no client can
    recover it.

Only the second is a correctness hazard for the agent consuming the result. This
script separates them from the recorded transcripts and emits the counts and
examples used in the paper's consequences section.

Usage:
  python analyze_consequences.py [--transcripts data/data/transcripts]
"""

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Text that signals the server noticed something was wrong. Deliberately generous:
# when in doubt we credit the server, so the hazard class is a lower bound.
ERROR_SIGNAL = re.compile(
    r"(?i)\b(error|invalid|must be|must have|required|expected|cannot|can't|unable|"
    r"failed|failure|not found|missing|unsupported|bad request|type\s*error|"
    r"malformed|rejected|no such)\b")

# A result that merely reports "nothing matched" is still a substantive answer to a
# question the server never legitimately parsed, so it stays in the hazard class.


def load_census(path):
    rows = {}
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            rows[r.get("server_name")] = r
    return rows


def result_text(reply_raw):
    """Extract the human-visible text an agent would receive from a tool result."""
    try:
        msg = json.loads(reply_raw)
    except Exception:
        return None, None
    if "error" in msg:
        return "protocol-error", json.dumps(msg["error"])[:400]
    res = msg.get("result")
    if not isinstance(res, dict):
        return None, None
    if res.get("isError"):
        return "is-error", json.dumps(res)[:400]
    parts = []
    for block in res.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text") or "")
    return "success", "\n".join(parts)


def find_invalid_args_exchange(transcript):
    """Locate the wrong-typed tools/call and its reply.

    The reply is matched on the JSON-RPC id, not by position: servers may emit log
    notifications between the request and the response, and taking the next received
    frame silently picks up the notification instead.
    """
    for i, e in enumerate(transcript):
        if e[1] != "send" or "tools/call" not in e[2]:
            continue
        try:
            msg = json.loads(e[2])
        except Exception:
            continue
        params = msg.get("params") or {}
        args = params.get("arguments") or {}
        if not args:
            continue  # the unknown-tool probe carries no arguments
        want = msg.get("id")
        for x in transcript[i + 1:]:
            if x[1] != "recv":
                continue
            try:
                cand = json.loads(x[2])
            except Exception:
                continue
            if isinstance(cand, dict) and cand.get("id") == want:
                return params.get("name"), args, x[2]
        return params.get("name"), args, None
    return None, None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=str(DATA / "probe_final.jsonl"))
    ap.add_argument("--transcripts", default=str(DATA / "data" / "transcripts"))
    ap.add_argument("--out", default=str(DATA / "consequences.json"))
    args = ap.parse_args()

    rows = load_census(args.inp)
    tdir = Path(args.transcripts)

    accepted = [n for n, r in rows.items() if r.get("handshake_ok") and any(
        c["id"] == "tools-call-invalid-args" and c["verdict"] == "fail"
        for c in r.get("checks", []))]

    buckets = {"silent-execution": [], "in-band-error": [], "empty-result": [],
               "no-transcript": [], "unparsed": []}

    for name in accepted:
        f = tdir / (name.replace("/", "__") + ".json")
        if not f.exists():
            buckets["no-transcript"].append(name)
            continue
        tr = json.loads(f.read_text(encoding="utf-8")).get("transcript") or []
        tool, sent, reply = find_invalid_args_exchange(tr)
        if not reply:
            buckets["unparsed"].append(name)
            continue
        kind, text = result_text(reply)
        if kind != "success":
            # Rejected after all (harness recorded otherwise); keep for audit.
            buckets["unparsed"].append(name)
            continue
        rec = {"server": name, "tool": tool, "sent": sent, "text": (text or "")[:600]}
        if not (text or "").strip():
            buckets["empty-result"].append(rec)
        elif ERROR_SIGNAL.search(text):
            buckets["in-band-error"].append(rec)
        else:
            buckets["silent-execution"].append(rec)

    n = len(accepted)
    print(f"servers graded 'accepts wrong-typed argument': {n}\n")
    for k in ("silent-execution", "in-band-error", "empty-result",
              "no-transcript", "unparsed"):
        v = buckets[k]
        print(f"  {k:18} {len(v):4}  ({100*len(v)/n:.1f}%)")

    resp = sum(1 for r in rows.values() if r.get("handshake_ok"))
    silent = len(buckets["silent-execution"])
    print(f"\nhazard class (silent execution) = {silent} of {resp:,} responding "
          f"servers = {100*silent/resp:.1f}%")

    print("\n=== examples: tool executed on input its own schema rejects ===")
    for rec in buckets["silent-execution"][:8]:
        one = " ".join((rec["text"] or "").split())[:150]
        print(f"\n  {rec['server']}  ({rec['tool']})")
        print(f"    sent : {json.dumps(rec['sent'])[:120]}")
        print(f"    got  : {one}")

    Path(args.out).write_text(json.dumps(
        {k: (v if k in ("no-transcript", "unparsed") else v)
         for k, v in buckets.items()}, indent=1), encoding="utf-8")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
