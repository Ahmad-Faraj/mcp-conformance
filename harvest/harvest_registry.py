"""Harvest the official MCP registry into a raw JSONL sampling frame.

Pages through https://registry.modelcontextprotocol.io/v0/servers with cursor
pagination, writes one server JSON object per line, then prints summary stats
used to define the study's sampling frame (locally-runnable vs remote-only).
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

BASE = "https://registry.modelcontextprotocol.io/v0/servers"
OUT = Path(__file__).resolve().parent.parent / "data" / "registry_raw.jsonl"
PAGE_LIMIT = 100


def fetch(cursor: str | None) -> dict:
    params = {"limit": str(PAGE_LIMIT)}
    if cursor:
        params["cursor"] = cursor
    url = f"{BASE}?{urllib.parse.urlencode(params)}"
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                return json.load(resp)
        except Exception as e:  # noqa: BLE001 - retry any transient failure
            wait = 2**attempt
            print(f"  fetch failed ({e}), retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"giving up on {url}")


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cursor = None
    total = 0
    with OUT.open("w", encoding="utf-8") as f:
        while True:
            page = fetch(cursor)
            servers = page.get("servers", [])
            for s in servers:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
            total += len(servers)
            cursor = (page.get("metadata") or {}).get("nextCursor")
            print(f"  {total} servers harvested", end="\r", flush=True)
            if not cursor or not servers:
                break
    print(f"\nwrote {total} servers -> {OUT}")

    # Summary stats for the sampling frame.
    kinds = Counter()
    pkg_registries = Counter()
    transports = Counter()
    with OUT.open(encoding="utf-8") as f:
        for line in f:
            s = json.loads(line)
            has_pkg = bool(s.get("packages"))
            has_remote = bool(s.get("remotes"))
            kinds[
                "package+remote"
                if has_pkg and has_remote
                else "package-only"
                if has_pkg
                else "remote-only"
                if has_remote
                else "neither"
            ] += 1
            for p in s.get("packages") or []:
                pkg_registries[p.get("registryType") or p.get("registry_type") or "?"] += 1
                transports[(p.get("transport") or {}).get("type") or "?"] += 1

    print("\nsampling frame:")
    for k, v in kinds.most_common():
        print(f"  {k:15} {v}")
    print("\npackage registries:")
    for k, v in pkg_registries.most_common():
        print(f"  {k:15} {v}")
    print("\npackage transports:")
    for k, v in transports.most_common():
        print(f"  {k:15} {v}")


if __name__ == "__main__":
    main()
