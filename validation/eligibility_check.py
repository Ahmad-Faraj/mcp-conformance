"""Validate the eligibility filter against an independent reading of the criteria.

The empirical standard for repository mining asks how the inclusion and exclusion
criteria were validated. The census applies them in run_batch.eligible_packages.
This script applies the same four criteria as the paper states them in Section 3.1,
written from that text and importing nothing from the harness, and compares the two
decisions server by server. Any disagreement is printed with the registry record
that caused it.

It also draws a stratified sample of registry entries, a few from each exclusion
class and from the eligible set, and writes the fields each decision rests on to a
file a person can read in a few minutes.

Usage:
  python validation/eligibility_check.py [--frame data/release/frame_latest.jsonl]
"""

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The paper's criteria, restated.
#   (i)   locally installable      -> declares at least one package
#   (ii)  stdio transport           -> that package's transport type is stdio
#   (iii) npm or PyPI               -> that package's registry type is npm or pypi
#   (iv)  self-contained            -> no environment variable, package argument or
#                                      runtime argument that is required and has no
#                                      default
# A server is eligible when at least one of its packages meets all four, and its
# registry status is active.


def needs_user_input(items):
    for it in items or []:
        required = bool(it.get("isRequired") or it.get("required"))
        has_default = "default" in it and it["default"] is not None
        if required and not has_default:
            return True
    return False


def independent_decision(entry):
    if entry.get("meta", {}).get("status") != "active":
        return "inactive"
    srv = entry["server"]
    pkgs = srv.get("packages") or []
    if not pkgs:
        return "remote-only"
    for p in pkgs:
        if (p.get("transport") or {}).get("type") != "stdio":
            continue
        if p.get("registryType") not in ("npm", "pypi"):
            continue
        if needs_user_input(p.get("environmentVariables")):
            continue
        if needs_user_input(p.get("packageArguments")):
            continue
        if needs_user_input(p.get("runtimeArguments")):
            continue
        return "eligible"
    return "excluded"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", default=str(ROOT / "data" / "release" / "frame_latest.jsonl"))
    ap.add_argument("--sample", default=str(ROOT / "validation" / "eligibility_sample.md"))
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT / "driver"))
    from run_batch import eligible_packages  # the census's own filter

    with open(args.frame, encoding="utf-8") as f:
        entries = [json.loads(line) for line in f]

    agree, disagree = 0, []
    decisions = Counter()
    by_class = {}
    for e in entries:
        mine = independent_decision(e)
        active = e.get("meta", {}).get("status") == "active"
        theirs = "eligible" if active and list(eligible_packages(e["server"])) else "not"
        mine_bin = "eligible" if mine == "eligible" else "not"
        decisions[mine] += 1
        by_class.setdefault(mine, []).append(e)
        if mine_bin == theirs:
            agree += 1
        else:
            disagree.append((e["server"].get("name"), mine, theirs))

    print(f"registry entries        : {len(entries):,}")
    print(f"independent decisions   : {dict(decisions)}")
    print(f"agreement with census   : {agree:,} of {len(entries):,}")
    for name, mine, theirs in disagree[:20]:
        print(f"  DISAGREE {name}: independent={mine} census={theirs}")

    # A stratified sample a person can check by eye.
    rng = random.Random(20260719)
    lines = ["# Eligibility sample", "",
             "Five registry entries from each class, with the fields the decision "
             "rests on. Check that each decision follows from the fields shown.", ""]
    for cls in ("eligible", "excluded", "remote-only", "inactive"):
        pool = by_class.get(cls, [])
        lines.append(f"## {cls} ({len(pool):,} in the snapshot)")
        lines.append("")
        for e in rng.sample(pool, min(5, len(pool))):
            srv = e["server"]
            lines.append(f"- `{srv.get('name')}` status={e.get('meta', {}).get('status')}")
            for p in srv.get("packages") or []:
                req_env = [v.get("name") for v in p.get("environmentVariables") or []
                           if (v.get("isRequired") or v.get("required"))
                           and v.get("default") is None]
                req_arg = [a.get("name") or a.get("valueHint") or a.get("value")
                           for a in (p.get("packageArguments") or [])
                           + (p.get("runtimeArguments") or [])
                           if (a.get("isRequired") or a.get("required"))
                           and a.get("default") is None]
                lines.append(f"  - {p.get('registryType')} / "
                             f"{(p.get('transport') or {}).get('type')}; "
                             f"required env without default: {req_env or 'none'}; "
                             f"required args without default: {req_arg or 'none'}")
            if not srv.get("packages"):
                lines.append(f"  - no packages; remotes: {len(srv.get('remotes') or [])}")
        lines.append("")
    Path(args.sample).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.sample}")
    return 0 if not disagree else 1


if __name__ == "__main__":
    sys.exit(main())
