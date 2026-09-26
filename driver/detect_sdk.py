"""Attribute each probed server to the SDK it is built on, from its resolved
dependency graph.

Method
------
For every server that completed a handshake we take the exact package version
that was launched, resolve its runtime dependency graph with deps.dev v3, and
look for a known MCP SDK or framework in that graph. The resolved graph carries
transitive edges, so a server that reaches an official SDK through a wrapper is
attributed to that SDK and marked as an indirect user rather than being recorded
as having no known SDK.

Three earlier defects are fixed here.

1. Version source. The registry entry's ``server_version`` is the version of the
   *server record*, not of the published package, and the two disagree for
   hundreds of servers. The version used here comes from the census launch
   command (``cmd``), which pins the exact artifact the probe installed and
   measured, for example ``pkg==1.2.3`` or ``pkg@1.2.3``. The launch command
   wins over every other source because attribution has to describe the code
   that actually answered the probe. If a row has no launch command, the frame
   snapshot's ``packages[].version`` is used instead, since that is what the
   registry says a client would install. ``server_version`` is never used.

2. Transitive edges. Direct dependencies alone miss every server that builds on
   a third-party wrapper. deps.dev returns the resolved graph, and each node
   carries ``relation`` of SELF, DIRECT or INDIRECT. That distinction is kept in
   the output as ``sdk_edge``.

3. Name matching. Dependency names are compared as whole, canonicalized names,
   never as substrings. Python requirement strings in the fallback path are
   parsed with ``packaging.requirements.Requirement`` and normalized with
   ``packaging.utils.canonicalize_name``.

Development dependencies are excluded. The deps.dev dependency graph for NPM is
the production resolution and already omits ``devDependencies``; the fallback
path reads the npm registry's ``dependencies`` field only, and drops PyPI
requirements that are gated behind an ``extra`` marker. Any node deps.dev marks
with a development-only relation is skipped as well.

Every HTTP response is cached under data/cache/, keyed by system, name and
version, so a second run is offline and costs nothing.

Output: data/sdk_attribution.csv and a cross-tab printed to stdout.
"""

import argparse
import csv
import json
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
DEPSDEV_CACHE = CACHE / "depsdev"
REGISTRY_CACHE = CACHE / "registry"
OUT = DATA / "sdk_attribution.csv"

DEPSDEV = "https://api.deps.dev/v3/systems/{system}/packages/{name}/versions/{version}:dependencies"

# Canonical package name -> SDK family. Whole-name match, never a substring.
# "rank" orders candidates when a graph contains more than one: a framework is
# the layer the author actually programmed against, and every one of these
# frameworks itself depends on the official SDK, so a framework outranks the
# official SDK it wraps.
NPM_SDK = {
    "@modelcontextprotocol/sdk": ("official-ts", 1),
    "fastmcp": ("fastmcp-ts", 2),
    "mcp-framework": ("mcp-framework-ts", 2),
    "xmcp": ("xmcp-ts", 2),
}
PYPI_SDK = {
    "mcp": ("official-py", 1),
    "mcp-server": ("official-py", 1),
    "fastmcp": ("fastmcp-py", 2),
}

# deps.dev relations that are not part of the runtime graph. The v3 dependency
# endpoint resolves production dependencies only, but guard the field anyway so
# a future development relation cannot leak into attribution.
DEV_RELATIONS = {"DEV", "DEVELOPMENT", "DEV_DEPENDENCY"}

_rate_lock = threading.Lock()
_next_call = [0.0]
MIN_INTERVAL = 0.05  # seconds between outbound requests, all threads combined


def _pace():
    """Polite global rate limit shared by every worker thread."""
    with _rate_lock:
        now = time.monotonic()
        wait = _next_call[0] - now
        if wait > 0:
            time.sleep(wait)
            now = time.monotonic()
        _next_call[0] = now + MIN_INTERVAL


def cache_path(root: Path, system: str, name: str, version: str) -> Path:
    key = urllib.parse.quote(f"{name}@{version}", safe="")
    return root / system.lower() / f"{key}.json"


def fetch_json(url: str, cache_file: Path):
    """GET url, caching the parsed body (or a 404 marker) on disk.

    A cached entry is returned without any network access, so a rerun is
    offline. 404 is a real answer (the package version is not indexed) and is
    cached as such; 429 and 5xx are retried with backoff and are never cached.
    """
    if cache_file.exists():
        try:
            blob = json.loads(cache_file.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            blob = None
        if isinstance(blob, dict):
            return None if blob.get("__miss__") else blob.get("body")

    body = None
    missing = False
    for attempt in range(5):
        _pace()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "mcpprobe-sdk/0.2"})
            with urllib.request.urlopen(req, timeout=45) as r:
                body = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code in (404, 400):
                missing = True
                break
            if e.code == 429 or e.code >= 500:
                retry_after = e.headers.get("Retry-After") if e.headers else None
                delay = float(retry_after) if (retry_after or "").isdigit() else 2.0 * (2 ** attempt)
                time.sleep(min(delay, 60) + random.random())
                continue
            missing = True
            break
        except Exception:  # noqa: BLE001  network hiccup, DNS, timeout
            time.sleep(1.5 * (attempt + 1) + random.random())
    else:
        return None  # exhausted retries; do not cache a transient failure

    if body is None and not missing:
        return None
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_suffix(".tmp")
    tmp.write_text(json.dumps({"__miss__": missing, "body": body}), encoding="utf-8")
    tmp.replace(cache_file)
    return body


# ----------------------------------------------------------------- versions --


def version_from_cmd(cmd, registry: str):
    """Exact version the probe installed, read off the launch command.

    npm rows end in ``npx -y name@version`` (the name may be scoped, so split on
    the last '@'); PyPI rows end in ``uvx name==version``.
    """
    if not cmd:
        return None, None
    toks = [t for t in cmd if isinstance(t, str)]
    if registry == "pypi":
        for t in toks:
            if "==" in t:
                name, _, ver = t.partition("==")
                name = name.split("[")[0]
                return (name or None), (ver or None)
        return None, None
    if registry == "npm":
        try:
            rest = toks[toks.index("npx") + 1:]
        except ValueError:
            rest = toks
        for t in rest:
            if t.startswith("-"):
                continue
            name, sep, ver = t.rpartition("@")
            if sep and name:  # "pkg@1.2.3" or "@scope/pkg@1.2.3"
                return name, (ver or None)
            return t, None
    return None, None


def load_frame_versions(frame_path: Path):
    """identifier -> published package version, from the registry snapshot."""
    out = {}
    if not frame_path.exists():
        return out
    with frame_path.open(encoding="utf-8") as f:
        for line in f:
            try:
                s = json.loads(line).get("server") or {}
            except ValueError:
                continue
            for pkg in s.get("packages") or []:
                ident, ver = pkg.get("identifier"), pkg.get("version")
                if ident and ver:
                    out.setdefault((pkg.get("registryType"), ident), ver)
    return out


# -------------------------------------------------------------- resolution --


def depsdev_graph(system: str, name: str, version: str):
    url = DEPSDEV.format(system=system,
                         name=urllib.parse.quote(name, safe=""),
                         version=urllib.parse.quote(version, safe=""))
    return fetch_json(url, cache_path(DEPSDEV_CACHE, "depsdev-" + system, name, version))


def pick(candidates):
    """Best (family, edge, requirement, resolved) from the SDK nodes in a graph.

    A direct edge beats an indirect one, because a direct dependency is the API
    the author wrote against. Within the same edge type a framework beats the
    official SDK it wraps.
    """
    if not candidates:
        return None
    candidates.sort(key=lambda c: (0 if c[1] == "direct" else 1, -c[4]))
    fam, edge, req, resolved, _rank = candidates[0]
    return fam, edge, req, resolved


def sdk_from_depsdev(system: str, name: str, version: str):
    table = NPM_SDK if system == "NPM" else PYPI_SDK
    graph = depsdev_graph(system, name, version)
    nodes = (graph or {}).get("nodes") or []
    if not nodes:
        return None, "no-graph"

    # Requirement string declared on the edge that pulls the SDK in. For a direct
    # edge that is the server's own declaration, which is what the historical
    # sdk_version column held; downstream code reads its range style (caret vs
    # exact) to say whether a server would pick up an SDK fix automatically, so
    # the declared range must be kept, not replaced by the resolved version.
    req_from_self, req_any = {}, {}
    for e in (graph or {}).get("edges") or []:
        to = e.get("toNode")
        if to is None:
            continue
        if e.get("fromNode") == 0:
            req_from_self.setdefault(to, e.get("requirement"))
        req_any.setdefault(to, e.get("requirement"))

    cands = []
    for i, node in enumerate(nodes):
        rel = (node.get("relation") or "").upper()
        if rel == "SELF" or rel in DEV_RELATIONS:
            continue
        vk = node.get("versionKey") or {}
        nm = vk.get("name") or ""
        key = canonicalize_name(nm) if system == "PYPI" else nm.lower()
        hit = table.get(str(key))
        if hit:
            direct = rel == "DIRECT"
            req = (req_from_self.get(i) if direct else None) or req_any.get(i)
            cands.append((hit[0], "direct" if direct else "indirect",
                          req, vk.get("version"), hit[1]))
    best = pick(cands)
    if best:
        return best, "depsdev"
    return None, "depsdev-no-sdk"


# ------------------------------------------------------------- fallbacks ----
# Used only when deps.dev has no resolved graph for the exact version. These see
# direct dependencies only, so anything they find is recorded as a direct edge
# and anything they miss stays unattributed rather than being called indirect.


def npm_packument(name: str):
    return fetch_json(
        f"https://registry.npmjs.org/{urllib.parse.quote(name, safe='@/')}",
        cache_path(REGISTRY_CACHE, "npm", name, "index"))


def npm_resolve_tag(name: str, version: str | None):
    """Turn a dist tag into a concrete version.

    A handful of launch commands pin a tag rather than a number (``pkg@latest``).
    deps.dev only indexes concrete versions, so resolve the tag against the
    packument first. The tag is read as of now, not as of the probe, which is
    the one place this attribution cannot be exact; those rows are flagged with
    version_source "npm-tag".
    """
    if not version:
        return None
    tags = (npm_packument(name) or {}).get("dist-tags") or {}
    return tags.get(version)


def npm_dev_only_sdk(name: str, version: str | None):
    """SDK family declared only under devDependencies, or None.

    These servers bundle the SDK into their published build, so it never appears
    in the runtime graph. They are NOT attributed to that family, because the
    runtime dependency is genuinely absent, but the fact is recorded so the
    residual bucket can be audited.
    """
    meta = npm_packument(name)
    if not meta:
        return None
    v = version or (meta.get("dist-tags") or {}).get("latest")
    vmeta = (meta.get("versions") or {}).get(v) or {}
    cands = [NPM_SDK[d.lower()] for d in (vmeta.get("devDependencies") or {})
             if d.lower() in NPM_SDK]
    if not cands:
        return None
    return max(cands, key=lambda c: c[1])[0]


def npm_direct(name: str, version: str | None):
    meta = npm_packument(name)
    if not meta:
        return None, False
    v = version or (meta.get("dist-tags") or {}).get("latest")
    vmeta = (meta.get("versions") or {}).get(v) or {}
    deps = vmeta.get("dependencies") or {}  # devDependencies deliberately excluded
    cands = []
    for dep, spec in deps.items():
        hit = NPM_SDK.get(dep.lower())
        if hit:
            cands.append((hit[0], "direct", spec, None, hit[1]))
    return pick(cands), bool(vmeta)


def pypi_direct(name: str, version: str | None):
    url = (f"https://pypi.org/pypi/{urllib.parse.quote(name)}/{urllib.parse.quote(version)}/json"
           if version else f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json")
    meta = fetch_json(url, cache_path(REGISTRY_CACHE, "pypi", name, version or "latest"))
    if not meta:
        return None, False
    reqs = (meta.get("info") or {}).get("requires_dist") or []
    cands = []
    for raw in reqs:
        try:
            req = Requirement(raw)
        except Exception:  # noqa: BLE001  malformed requirement string
            continue
        # Skip anything installed only with an optional extra: it is not part of
        # the runtime the probe exercised.
        if req.marker is not None and "extra" in str(req.marker):
            continue
        hit = PYPI_SDK.get(str(canonicalize_name(req.name)))
        if hit:
            cands.append((hit[0], "direct", str(req.specifier) or None, None, hit[1]))
    return pick(cands), True


# ----------------------------------------------------------------- driver ----


def unknown_verdict(r: dict) -> str:
    for c in r.get("checks", []):
        if c["id"] == "tools-call-unknown":
            return c["verdict"]
    return "n/a"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=str(DATA / "probe_census.jsonl"))
    ap.add_argument("--frame", default=str(DATA / "frame_latest.jsonl"))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    frame_versions = load_frame_versions(Path(args.frame))

    by_name = {}
    with Path(args.inp).open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("handshake_ok"):
                by_name[r.get("server_name")] = r
    servers = list(by_name.values())
    print(f"attributing SDK for {len(servers)} handshaking servers...", file=sys.stderr)

    def attribute(r):
        ident = r.get("identifier")
        reg = r.get("registry_type")
        cmd_name, cmd_ver = version_from_cmd(r.get("cmd"), reg)
        name = cmd_name or ident
        ver = cmd_ver or frame_versions.get((reg, ident))
        vsrc = "cmd" if cmd_ver else ("frame" if ver else "none")

        fam = edge = sdkver = sdkres = None
        note = "unsupported-registry"
        if reg in ("npm", "pypi"):
            system = "NPM" if reg == "npm" else "PYPI"
            if reg == "npm" and ver and not re.match(r"\d", ver):
                concrete = npm_resolve_tag(name, ver)
                if concrete:
                    ver, vsrc = concrete, "npm-tag"
            if ver:
                best, note = sdk_from_depsdev(system, name, ver)
                if best:
                    fam, edge, sdkver, sdkres = best
            else:
                note = "no-version"
            if fam is None and note != "depsdev-no-sdk":
                # deps.dev could not resolve this exact version; fall back to the
                # registry's own direct dependency list.
                direct = npm_direct(name, ver) if reg == "npm" else pypi_direct(name, ver)
                best, had_meta = direct
                if best:
                    fam, edge, sdkver, sdkres = best
                    note = "registry-direct"
                elif had_meta:
                    note = "registry-no-sdk"

        if fam is None:
            fam = "none-handrolled" if note in ("depsdev-no-sdk", "registry-no-sdk") else "unknown"
            if reg == "npm" and fam == "none-handrolled":
                dev = npm_dev_only_sdk(name, ver)
                if dev:
                    note = f"dev-only-sdk:{dev}"
            edge = ""
        return {"server": r.get("server_name"), "registry": reg, "identifier": ident,
                "sdk_family": fam, "sdk_version": sdkver or "",
                "unknown_verdict": unknown_verdict(r),
                "sdk_edge": edge or "", "sdk_resolved_version": sdkres or "",
                "version_source": vsrc, "resolution": note,
                "package_version": ver or ""}

    from concurrent.futures import ThreadPoolExecutor
    rows = []
    xtab = defaultdict(Counter)
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for row in ex.map(attribute, servers):
            rows.append(row)
            xtab[row["sdk_family"]][row["unknown_verdict"]] += 1
            done += 1
            if done % 250 == 0:
                print(f"  {done}/{len(servers)}", file=sys.stderr)

    rows.sort(key=lambda x: x["server"] or "")
    out_path = Path(args.out)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        # The first six columns are the historical schema, kept in order so the
        # table, figure and release code keeps working unchanged.
        w = csv.DictWriter(f, fieldnames=["server", "registry", "identifier",
                                          "sdk_family", "sdk_version", "unknown_verdict",
                                          "sdk_edge", "sdk_resolved_version",
                                          "version_source", "resolution",
                                          "package_version"])
        w.writeheader()
        w.writerows(rows)

    print("\n== SDK family x tools-call-unknown verdict ==")
    verdicts = ["error-as-result", "pass", "warn", "fail", "n/a"]
    print(f"  {'sdk_family':20}" + "".join(f"{v:>17}" for v in verdicts) + f"{'total':>8}")
    for fam in sorted(xtab, key=lambda k: -sum(xtab[k].values())):
        c = xtab[fam]
        tot = sum(c.values())
        print(f"  {fam:20}" + "".join(f"{c.get(v, 0):>17}" for v in verdicts) + f"{tot:>8}")

    print("\n== edge type ==")
    for k, v in Counter(r["sdk_edge"] or "unattributed" for r in rows).most_common():
        print(f"  {k:14}{v:>8}")
    print("\n== version source ==")
    for k, v in Counter(r["version_source"] for r in rows).most_common():
        print(f"  {k:14}{v:>8}")
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
