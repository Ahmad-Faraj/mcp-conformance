"""Compare two census runs of the same frame and emit the numbers the paper uses.

The census frame is fixed at the July snapshot, so re-running it later probes the
same servers, at the same declared versions, with the same launch commands. What can
change between runs is everything those commands resolve: the SDK, the transitive
dependency graph, and whatever the package registries serve that day.

That turns a re-run into a natural experiment rather than a stability check, and the
September run caught one. Nine days after the snapshot the official Python SDK
published 2.0.0, which renamed FastMCP to MCPServer. Servers that declared a floor or
a caret on that dependency resolved to 1.x in July and to 2.x in September, and
stopped importing.

Usage:
  python driver/compare_runs.py --before data/probe_census.jsonl \\
      --after data/runs/sept/probe_census_sept.jsonl \\
      --out paper/comparison_numbers.tex
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from failure_classes import harness_error  # noqa: E402
from stats import wilson  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# The SDK's own compatibility message, and the attribute error left by the same
# major version removing decorators. Matching the text rather than guessing keeps
# the attribution checkable against the released transcripts.
SDK2_SIGNS = (
    re.compile(r"This is mcp 2\.x, where FastMCP was renamed to MCPServer"),
    # The same major version removed the low-level Server decorators, so a server
    # that registered handlers through them dies on an attribute that is simply
    # gone. Match the class rather than enumerate the decorators.
    re.compile(r"'(Low[Ll]evel)?Server' object has no attribute"),
)


def load(path):
    with open(path, encoding="utf-8") as f:
        return {r["server_name"]: r for r in map(json.loads, f)}


def verdict(row, check):
    for c in row.get("checks") or []:
        if c["id"] == check:
            return c["verdict"]
    return None


def sdk2_victim(row):
    """Did this server die with the Python SDK 2.0 signature?

    The release strips the stderr of a withheld server, so the classification is
    attached to its row when the release is built. Prefer that field when present,
    and fall back to matching the text on an unredacted run.
    """
    if "rerun_break_cause" in row:
        return row["rerun_break_cause"] == "python-sdk-2"
    blob = "\n".join(row.get("stderr_tail") or [])
    return any(p.search(blob) for p in SDK2_SIGNS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", default=str(DATA / "probe_census.jsonl"))
    ap.add_argument("--after",
                    default=str(DATA / "runs" / "sept" / "probe_census_sept.jsonl"))
    ap.add_argument("--sdk", default=str(DATA / "sdk_attribution.csv"))
    ap.add_argument("--pin", default=str(DATA / "pin_experiment.csv"))
    ap.add_argument("--out", default=str(ROOT / "paper" / "comparison_numbers.tex"))
    args = ap.parse_args()

    before, after = load(args.before), load(args.after)
    common = sorted(set(before) & set(after))

    def graded(rows):
        return {k: r for k, r in rows.items() if not harness_error(r)}

    g_after = graded(after)
    hs_after = sum(1 for r in g_after.values() if r.get("handshake_ok"))

    was = [k for k in common if before[k].get("handshake_ok")]
    now = [k for k in common if after[k].get("handshake_ok")]
    lost = [k for k in was if not after[k].get("handshake_ok")]
    gained = [k for k in now if not before[k].get("handshake_ok")]

    # Attribution: same server version, same launch command, SDK-2.0 signature.
    def same_version(k):
        # Withholding removes server_version, so the release records the comparison
        # as a flag instead.
        if "version_unchanged" in after[k]:
            return bool(after[k]["version_unchanged"])
        return before[k].get("server_version") == after[k].get("server_version")

    unchanged = [k for k in lost if same_version(k)
                 and (before[k].get("cmd") == after[k].get("cmd")
                      or "cmd" not in after[k])]
    sdk2 = [k for k in unchanged if sdk2_victim(after[k])]

    # The registry asymmetry is the control: a host, network or harness fault would
    # not confine itself to one package ecosystem.
    def by_reg(keys, reg):
        return [k for k in keys if after[k].get("registry_type") == reg]

    npm_was, pypi_was = by_reg(was, "npm"), by_reg(was, "pypi")
    npm_lost, pypi_lost = by_reg(lost, "npm"), by_reg(lost, "pypi")

    # Denominator for the headline: servers on a Python MCP SDK that worked before.
    sdk_family = {}
    if Path(args.sdk).exists():
        with open(args.sdk, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                sdk_family[r["server"]] = r.get("sdk_family", "")
    py_was = [k for k in pypi_was
              if sdk_family.get(k) in ("official-py", "fastmcp-py")]
    py_now = [k for k in py_was if after[k].get("handshake_ok")]

    # How the broken servers declared the dependency that moved under them.
    declared = Counter()
    if Path(args.sdk).exists():
        with open(args.sdk, encoding="utf-8") as f:
            spec = {r["server"]: (r.get("sdk_version") or "").strip()
                    for r in csv.DictReader(f)}
        for k in sdk2:
            v = spec.get(k, "")
            declared["exact" if v.startswith("==") else
                     "range" if v else "unrecorded"] += 1

    # Conformance among the servers that still answer, for the stability claim.
    def rate(rows, check, want):
        resp = [r for r in rows.values() if r.get("handshake_ok")]
        k = sum(1 for r in resp if verdict(r, check) == want)
        return k, len(resp)

    ear_k, ear_n = rate(g_after, "tools-call-unknown", "error-as-result")
    inv_k, inv_n = rate(g_after, "tools-call-invalid-args", "fail")
    mal_k, mal_n = rate(g_after, "malformed-json", "fail")

    # The pinning experiment, if it has been run.
    pin_n = pin_restored = 0
    if Path(args.pin).exists():
        with open(args.pin, encoding="utf-8") as f:
            pins = list(csv.DictReader(f))
        pin_n = len(pins)
        pin_restored = sum(1 for r in pins
                           if r["pinned_below_2"] == "handshake"
                           and r["as_census_launches"] != "handshake")

    def pct(k, n, dp=1):
        return f"{100*k/n:.{dp}f}" + chr(92) + "%" if n else "-"

    macros = {
        "SeptDate": "26 September 2026",
        "SDKTwoDate": "28 July 2026",
        "NSeptGraded": f"{len(g_after):,}",
        "NSeptHandshake": f"{hs_after:,}",
        "SeptHandshakeRate": pct(hs_after, len(g_after)),
        "NRerunCommon": f"{len(common):,}",
        "NLost": f"{len(lost):,}",
        "NGained": f"{len(gained):,}",
        "NLostUnchanged": f"{len(unchanged):,}",
        "NSDKTwoBroke": f"{len(sdk2):,}",
        "NSDKTwoRange": f"{declared.get('range', 0):,}",
        "NpmWas": f"{len(npm_was):,}",
        "NpmLost": f"{len(npm_lost):,}",
        "NpmLostRate": pct(len(npm_lost), len(npm_was)),
        "PypiWas": f"{len(pypi_was):,}",
        "PypiLost": f"{len(pypi_lost):,}",
        "PypiLostRate": pct(len(pypi_lost), len(pypi_was)),
        "NPySDKWas": f"{len(py_was):,}",
        "NPySDKNow": f"{len(py_now):,}",
        "PySDKLostRate": pct(len(py_was) - len(py_now), len(py_was), 0),
        "SeptErrAsResult": pct(ear_k, ear_n),
        "SeptNoTypecheck": pct(inv_k, inv_n),
        "SeptMalformedDies": pct(mal_k, mal_n),
        "NPinTested": f"{pin_n:,}",
        "NPinRestored": f"{pin_restored:,}",
    }
    _p, lo, hi = wilson(len(py_was) - len(py_now), len(py_was))
    macros["PySDKLostCI"] = (f"{macros['PySDKLostRate']} (95" + chr(92) + "% CI "
                             f"{100*lo:.0f}--{100*hi:.0f})")

    bs = chr(92)
    body = ["% AUTO-GENERATED by driver/compare_runs.py -- do not edit by hand.",
            "% July census against the September re-run of the same frame."]
    body += [bs + "newcommand{" + bs + k + "}{" + v + "}" for k, v in macros.items()]
    Path(args.out).write_text("\n".join(body) + "\n", encoding="utf-8")

    print(f"wrote {args.out}")
    for k, v in macros.items():
        print(f"  {bs}{k} = {v}")


if __name__ == "__main__":
    main()
