"""Generate LaTeX tables for the paper from the dataset.

Emits paper/tables/{startup,verdicts,sdk}.tex. Run together with make_numbers.py
and make_figures.py to regenerate every data-derived artifact in the paper.
"""

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TABLES = ROOT / "paper" / "tables"

CHECK_ORDER = ["server-initialize", "ping", "tools-list", "tools-schema-valid",
               "tools-call-unknown", "tools-call-invalid-args", "malformed-json",
               "stdout-purity"]


def wilson(k, n):
    if n == 0:
        return (0, 0, 0)
    z = 1.96
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0, c - h), min(1, c + h))


def load(path):
    by = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            by[r.get("server_name") or json.dumps(r.get("cmd"))] = r
    return list(by.values())


def esc(s):
    return str(s).replace("_", "\\_").replace("%", "\\%").replace("&", "\\&")


def startup_table(rows):
    non = [r for r in rows if not r.get("handshake_ok")]
    c = Counter(r.get("failure_class", "unknown") for r in non)
    total = len(non)
    out = [r"\begin{table}[t]", r"\centering",
           r"\caption{Startup-failure taxonomy: causes for servers that never reach a handshake.}",
           r"\label{tab:startup}", r"\begin{tabular}{lrr}", r"\toprule",
           r"Failure class & Count & \% of failures \\", r"\midrule"]
    for cls, n in c.most_common():
        pct = f"{100*n/total:.1f}" if total else "-"
        out.append(f"{esc(cls)} & {n} & {pct} \\\\")
    out += [r"\midrule", f"Total non-handshaking & {total} & 100.0 \\\\",
            r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    return "\n".join(out)


def verdicts_table(rows):
    resp = [r for r in rows if r.get("handshake_ok")]
    n = len(resp)
    tally = defaultdict(Counter)
    for r in resp:
        for ch in r.get("checks", []):
            tally[ch["id"]][ch["verdict"]] += 1
    out = [r"\begin{table}[t]", r"\centering",
           r"\caption{Verdict distribution per check over responding servers, with 95\% Wilson CIs on the pass (or documented) rate.}",
           r"\label{tab:verdicts}", r"\begin{tabular}{lrrrr}", r"\toprule",
           r"Check & Pass & Fail & Other & Pass rate (95\% CI) \\", r"\midrule"]
    for cid in CHECK_ORDER:
        c = tally.get(cid, Counter())
        p = c.get("pass", 0)
        f = c.get("fail", 0)
        other = sum(v for k, v in c.items() if k not in ("pass", "fail"))
        _, lo, hi = wilson(p, n)
        out.append(f"{esc(cid)} & {p} & {f} & {other} & {100*p/n:.1f} ({100*lo:.1f}--{100*hi:.1f}) \\\\" if n else f"{esc(cid)} & {p} & {f} & {other} & - \\\\")
    out += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    return "\n".join(out)


def sdk_table():
    path = DATA / "sdk_attribution.csv"
    if not path.exists():
        return "% sdk_attribution.csv missing; run detect_sdk.py\n"
    xtab = defaultdict(Counter)
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            xtab[row["sdk_family"]][row["unknown_verdict"]] += 1
    out = [r"\begin{table}[t]", r"\centering",
           r"\caption{SDK family vs.\ unknown-tool response. The error-as-result divergence tracks the SDK, not the author.}",
           r"\label{tab:sdk}", r"\begin{tabular}{lrrr}", r"\toprule",
           r"SDK family & error-as-result & protocol error & other \\", r"\midrule"]
    for fam in sorted(xtab, key=lambda k: -sum(xtab[k].values())):
        c = xtab[fam]
        ear = c.get("error-as-result", 0)
        pe = c.get("pass", 0)
        other = sum(v for k, v in c.items() if k not in ("error-as-result", "pass"))
        out.append(f"{esc(fam)} & {ear} & {pe} & {other} \\\\")
    out += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=str(DATA / "probe_results.jsonl"))
    args = ap.parse_args()
    TABLES.mkdir(parents=True, exist_ok=True)
    rows = load(Path(args.inp))
    (TABLES / "startup.tex").write_text(startup_table(rows), encoding="utf-8")
    (TABLES / "verdicts.tex").write_text(verdicts_table(rows), encoding="utf-8")
    (TABLES / "sdk.tex").write_text(sdk_table(), encoding="utf-8")
    print(f"wrote 3 tables to {TABLES} from {len(rows)} servers")


if __name__ == "__main__":
    main()
