"""Resolve the implementation language of servers behind a given check failure.

A maintainer who reproduced our malformed-frame finding pointed out that their
server contains no framing code at all: it is built on the official Go SDK, whose
stdio transport ends the session on a decode error. Our SDK attribution had
classified it as having no known SDK, because attribution reads npm and PyPI
dependency graphs and a Go binary shipped through npm declares no MCP dependency.

That is a structural blind spot, not a one-off. This script measures its size for a
given check by asking the registry's linked repository what language it is written
in. A server whose repository is not JavaScript, TypeScript or Python is one our
dependency-graph attribution cannot see into, whatever SDK it actually uses.

Requires the `gh` CLI, authenticated. Writes data/repo_languages.csv.

Usage:
  python driver/repo_languages.py [--check malformed-json] [--verdict fail]
"""

import argparse
import csv
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# The two ecosystems whose dependency graphs detect_sdk.py can resolve. Anything
# else reaches the registry as a compiled or bundled artifact.
ATTRIBUTABLE = {"JavaScript", "TypeScript", "Python"}


def api(path):
    p = subprocess.run(["gh", "api", path], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=str(DATA / "probe_census.jsonl"))
    ap.add_argument("--frame", default=str(DATA / "frame_latest.jsonl"))
    ap.add_argument("--check", default="malformed-json")
    ap.add_argument("--verdict", default="fail")
    ap.add_argument("--out", default=str(DATA / "repo_languages.csv"))
    args = ap.parse_args()

    with open(args.inp, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    hit = sorted({r["server_name"] for r in rows
                  if any(c["id"] == args.check and c["verdict"] == args.verdict
                         for c in r.get("checks") or [])})

    repos = {}
    with open(args.frame, encoding="utf-8") as f:
        for line in f:
            s = json.loads(line)["server"]
            repos[s["name"]] = (s.get("repository") or {}).get("url", "")

    sdk = {}
    p = DATA / "sdk_attribution.csv"
    if p.exists():
        with p.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                sdk[r["server"]] = r.get("sdk_family", "")

    out = []
    for name in hit:
        url = repos.get(name, "")
        lang = ""
        if "github.com/" in url:
            slug = url.split("github.com/")[1].strip("/")
            if slug.endswith(".git"):
                slug = slug[:-4]
            d = api(f"repos/{slug}")
            if d:
                lang = d.get("language") or ""
        out.append({"server": name, "check": args.check,
                    "sdk_family": sdk.get(name, ""), "repository": url,
                    "language": lang,
                    "attributable": str(lang in ATTRIBUTABLE).lower()})
        print(f"{name[:50]:52} {sdk.get(name, ''):18} {lang or '(unknown)'}")

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    opaque = [r for r in out if r["attributable"] == "false" and r["language"]]
    go = [r for r in out if r["language"] == "Go"]
    print(f"\nwrote {args.out}")
    print(f"  {args.check}={args.verdict}: {len(out)} servers")
    print(f"  written in a language our attribution cannot resolve: {len(opaque)}")
    print(f"  of those, Go: {len(go)}")


if __name__ == "__main__":
    main()
