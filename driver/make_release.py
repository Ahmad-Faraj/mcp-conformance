"""Build the public, disclosure-filtered dataset release from the census.

The paper reports only aggregates and anonymized case studies, so the released
dataset must not name the servers behind security-relevant findings, and must not
carry credential material that servers emitted at runtime. This script applies both
filters and writes a self-contained release directory.

Two filters are applied:

1. IDENTITY WITHHELD. A server with a security-relevant verdict (see
   make_disclosure.py) keeps every measurement but loses its name, package
   identifier and launch command, replaced by a stable pseudonym. Aggregates are
   unaffected; the per-server finding cannot be attributed until the disclosure
   window closes.

2. CREDENTIAL REDACTION. The census ran with the network available, and a small
   number of servers printed live credential material (session tokens, and in one
   case an API key auto-provisioned against a third-party service). Any such match
   in captured stderr/stdout/check detail is replaced with a redaction marker.

Every number in the paper is recomputable from the release: only identity strings
and free-text credential material are altered, never a verdict or a count.

Usage:
  python make_release.py [--out data/release]
"""

import argparse
import csv
import hashlib
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Verdicts that make a server's identity sensitive until disclosure completes.
# Kept in sync with make_disclosure.py.
SECURITY_RELEVANT = {
    ("malformed-json", "fail"),
    ("stdout-purity", "fail"),
    ("tools-call-unknown", "fail"),
}

# Credential material observed in runtime output. Redacted from the release.
CREDENTIAL_PATTERNS = [
    re.compile(r"(?i)((?:api[_-]?key|secret|auth token|password|token)[\"'\s:=]+)([A-Za-z0-9_\-]{24,})"),
    re.compile(r"(?i)(pvk_)([A-Za-z0-9]{16,})"),
    re.compile(r"(AKIA[0-9A-Z]{16})"),
    re.compile(r"(gh[pousr]_[A-Za-z0-9]{20,})"),
    re.compile(r"(sk-(?:ant-)?[A-Za-z0-9_\-]{20,})"),
    re.compile(r"(xox[baprs]-[A-Za-z0-9-]{10,})"),
    re.compile(r"(eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*)"),
    re.compile(r"(-----BEGIN [A-Z ]*PRIVATE KEY-----)"),
]
REDACTION = "[REDACTED-CREDENTIAL]"


def redact(text: str) -> tuple[str, int]:
    """Strip credential material, keeping the surrounding label for context."""
    n = 0
    for pat in CREDENTIAL_PATTERNS:
        def sub(m):
            nonlocal n
            n += 1
            # Two-group patterns keep group 1 (the label) and redact the value.
            return (m.group(1) + REDACTION) if m.lastindex and m.lastindex >= 2 else REDACTION
        text = pat.sub(sub, text)
    return text, n


def redact_any(obj):
    """Recursively redact strings inside lists/dicts/scalars."""
    total = 0
    if isinstance(obj, str):
        out, n = redact(obj)
        return out, n
    if isinstance(obj, list):
        out = []
        for v in obj:
            r, n = redact_any(v)
            out.append(r)
            total += n
        return out, total
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            r, n = redact_any(v)
            out[k] = r
            total += n
        return out, total
    return obj, 0


def is_sensitive(row: dict) -> bool:
    if not row.get("handshake_ok"):
        return False
    return any((c.get("id"), c.get("verdict")) in SECURITY_RELEVANT
               for c in row.get("checks", []))


def pseudonym(name: str) -> str:
    return "withheld-" + hashlib.sha256((name or "").encode()).hexdigest()[:12]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=str(DATA / "probe_final.jsonl"))
    ap.add_argument("--out", default=str(DATA / "release"))
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    rows = [json.loads(l) for l in Path(args.inp).open(encoding="utf-8")]

    withheld, redactions = {}, 0
    released = []
    for r in rows:
        r, n = redact_any(r)
        redactions += n
        if is_sensitive(r):
            real = r.get("server_name")
            alias = pseudonym(real)
            withheld[real] = alias
            r["server_name"] = alias
            r["identifier"] = alias
            r["identity_withheld"] = True
            r.pop("cmd", None)
            r.pop("server_info", None)
            r.pop("stderr_tail", None)
            r.pop("stdout_noise", None)
        released.append(r)

    with (out / "probe_census.jsonl").open("w", encoding="utf-8") as f:
        for r in released:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # SDK attribution, pseudonymized consistently with the probe file.
    src = DATA / "sdk_attribution.csv"
    if src.exists():
        with src.open(encoding="utf-8") as f, \
             (out / "sdk_attribution.csv").open("w", newline="", encoding="utf-8") as g:
            rd = csv.DictReader(f)
            w = csv.DictWriter(g, fieldnames=rd.fieldnames)
            w.writeheader()
            for row in rd:
                alias = withheld.get(row["server"])
                if alias:
                    row["server"] = alias
                    row["identifier"] = alias
                w.writerow(row)

    # The registry snapshot is third-party data: publishers sometimes paste a live
    # token into a header "value" field instead of a placeholder. It is already
    # public via the registry, but re-publishing it here would amplify it, so the
    # same redactor runs over the frame. Header values are never used in any
    # analysis, so redaction cannot affect a reported number.
    frame_redactions = 0
    src_frame = DATA / "frame_latest.jsonl"
    if src_frame.exists():
        with src_frame.open(encoding="utf-8") as f, \
             (out / "frame_latest.jsonl").open("w", encoding="utf-8") as g:
            for line in f:
                obj, n = redact_any(json.loads(line))
                frame_redactions += n
                g.write(json.dumps(obj, ensure_ascii=False) + "\n")

    if (DATA / "summary.json").exists():
        shutil.copy2(DATA / "summary.json", out / "summary.json")

    print(f"wrote {out}")
    print(f"  servers released      : {len(released)}")
    print(f"  identities withheld   : {len(withheld)}")
    print(f"  credential redactions : {redactions} (probe) + {frame_redactions} (frame)")


if __name__ == "__main__":
    main()
