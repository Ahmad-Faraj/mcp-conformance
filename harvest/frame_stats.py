"""Compute the sampling frame from the raw registry harvest.

Unwraps the {server, _meta} envelope, keeps only the latest active version of
each server name, and reports the runnability breakdown that defines the
study's sampling frame. Writes the deduped frame to data/frame_latest.jsonl.
"""

import json
from collections import Counter
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
RAW = DATA / "registry_raw.jsonl"
OUT = DATA / "frame_latest.jsonl"


def main() -> None:
    latest: dict[str, dict] = {}
    versions = Counter()
    statuses = Counter()
    with RAW.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            srv = row.get("server", {})
            meta = (row.get("_meta") or {}).get(
                "io.modelcontextprotocol.registry/official"
            ) or {}
            name = srv.get("name")
            if not name:
                continue
            versions[name] += 1
            if meta.get("isLatest"):
                statuses[meta.get("status", "?")] += 1
                latest[name] = {"server": srv, "meta": meta}

    with OUT.open("w", encoding="utf-8") as f:
        for name in sorted(latest):
            f.write(json.dumps(latest[name], ensure_ascii=False) + "\n")

    print(f"raw rows (all versions): {sum(versions.values())}")
    print(f"unique server names:     {len(versions)}")
    print(f"latest-version entries:  {len(latest)}")
    print(f"status of latest:        {dict(statuses)}")

    kinds = Counter()
    pkg_registries = Counter()
    transports = Counter()
    remote_types = Counter()
    has_repo = 0
    for entry in latest.values():
        s = entry["server"]
        if s.get("repository", {}).get("url"):
            has_repo += 1
        pkgs = s.get("packages") or []
        remotes = s.get("remotes") or []
        kinds[
            "package+remote"
            if pkgs and remotes
            else "package-only"
            if pkgs
            else "remote-only"
            if remotes
            else "neither"
        ] += 1
        for p in pkgs:
            pkg_registries[p.get("registryType", "?")] += 1
            transports[(p.get("transport") or {}).get("type", "?")] += 1
        for r in remotes:
            remote_types[r.get("type", "?")] += 1

    print(f"\nwith repository URL: {has_repo}")
    print("\nrunnability (latest versions):")
    for k, v in kinds.most_common():
        print(f"  {k:15} {v}")
    print("\npackage registryType:")
    for k, v in pkg_registries.most_common():
        print(f"  {k:15} {v}")
    print("\npackage transport:")
    for k, v in transports.most_common():
        print(f"  {k:15} {v}")
    print("\nremote type:")
    for k, v in remote_types.most_common():
        print(f"  {k:15} {v}")
    print(f"\nwrote deduped frame -> {OUT}")


if __name__ == "__main__":
    main()
