"""Attribute each probed server to the SDK it is built on, from package metadata.

Reads dependency lists from the npm and PyPI metadata APIs (no code execution),
classifies each server's SDK family, and cross-tabulates SDK against the
tools-call-unknown verdict. This tests the hypothesis that the near-universal
error-as-result behavior is inherited from the official SDKs rather than
independently reinvented by thousands of authors.

Output: data/sdk_attribution.csv and a cross-tab printed to stdout.
"""

import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
RESULTS = DATA / "probe_final.jsonl"
OUT = DATA / "sdk_attribution.csv"

# Dependency-name -> SDK family. Substring match, case-insensitive.
NPM_SDK = {
    "@modelcontextprotocol/sdk": "official-ts",
    "fastmcp": "fastmcp-ts",
    "mcp-framework": "mcp-framework-ts",
    "xmcp": "xmcp-ts",
}
PYPI_SDK = {
    "mcp": "official-py",
    "fastmcp": "fastmcp-py",
    "mcp-server": "official-py",
}


def fetch_json(url: str):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "mcpprobe-sdk/0.1"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception:  # noqa: BLE001
            time.sleep(1.5 * (attempt + 1))
    return None


def npm_sdk(ident: str, version: str | None):
    meta = fetch_json(f"https://registry.npmjs.org/{urllib.parse.quote(ident, safe='@/')}")
    if not meta:
        return "unknown", None
    v = version or (meta.get("dist-tags") or {}).get("latest")
    vmeta = (meta.get("versions") or {}).get(v) or {}
    deps = {**(vmeta.get("dependencies") or {}), **(vmeta.get("devDependencies") or {})}
    names = " ".join(deps).lower()
    for dep, fam in NPM_SDK.items():
        if dep.lower() in names:
            return fam, deps.get(dep)
    return ("none-handrolled" if deps else "unknown"), None


def pypi_sdk(ident: str, version: str | None):
    url = (f"https://pypi.org/pypi/{ident}/{version}/json" if version
           else f"https://pypi.org/pypi/{ident}/json")
    meta = fetch_json(url)
    if not meta:
        return "unknown", None
    reqs = (meta.get("info") or {}).get("requires_dist") or []
    names = " ".join(reqs).lower()
    # Order matters: fastmcp before bare "mcp" to avoid mislabeling.
    for dep in ("fastmcp", "mcp-server", "mcp"):
        # match dependency token at a word boundary (avoids "mcp" in "mcpxyz")
        for r in reqs:
            tok = r.split(";")[0].strip().split()[0].split("[")[0].split("==")[0].split(">")[0].split("<")[0].split("~")[0].strip().lower()
            if tok == dep:
                return PYPI_SDK[dep], None
    return ("none-handrolled" if reqs else "unknown"), None


def unknown_verdict(r: dict) -> str:
    for c in r.get("checks", []):
        if c["id"] == "tools-call-unknown":
            return c["verdict"]
    return "n/a"


def main():
    by_name = {}
    with RESULTS.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("handshake_ok"):
                by_name[r.get("server_name")] = r
    servers = list(by_name.values())
    print(f"attributing SDK for {len(servers)} handshaking servers...", file=sys.stderr)

    def attribute(r):
        ident, ver, reg = r.get("identifier"), r.get("server_version"), r.get("registry_type")
        if reg == "npm":
            fam, sdkver = npm_sdk(ident, ver)
        elif reg == "pypi":
            fam, sdkver = pypi_sdk(ident, ver)
        else:
            fam, sdkver = "unknown", None
        return {"server": r.get("server_name"), "registry": reg, "identifier": ident,
                "sdk_family": fam, "sdk_version": sdkver, "unknown_verdict": unknown_verdict(r)}

    # Metadata lookups are network-bound, so fan out across threads.
    from concurrent.futures import ThreadPoolExecutor
    rows = []
    xtab = defaultdict(Counter)
    done = 0
    with ThreadPoolExecutor(max_workers=24) as ex:
        for row in ex.map(attribute, servers):
            rows.append(row)
            xtab[row["sdk_family"]][row["unknown_verdict"]] += 1
            done += 1
            if done % 100 == 0:
                print(f"  {done}/{len(servers)}", file=sys.stderr)

    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["server", "registry", "identifier",
                                          "sdk_family", "sdk_version", "unknown_verdict"])
        w.writeheader()
        w.writerows(rows)

    print("\n== SDK family x tools-call-unknown verdict ==")
    verdicts = ["error-as-result", "pass", "warn", "fail", "n/a"]
    print(f"  {'sdk_family':20}" + "".join(f"{v:>17}" for v in verdicts) + f"{'total':>8}")
    for fam in sorted(xtab, key=lambda k: -sum(xtab[k].values())):
        c = xtab[fam]
        tot = sum(c.values())
        print(f"  {fam:20}" + "".join(f"{c.get(v, 0):>17}" for v in verdicts) + f"{tot:>8}")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
