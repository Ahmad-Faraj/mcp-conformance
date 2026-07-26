"""Generate paper/numbers.tex from the final dataset.

Every number cited in the paper comes from here, so prose can never drift from
data. Run after the final clean dataset is complete.

Usage:
  python make_numbers.py [--in data/probe_results.jsonl] [--out paper/numbers.tex]
"""

import argparse
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def wilson(k: int, n: int):
    """95% Wilson score interval for a proportion (robust for small/edge counts)."""
    if n == 0:
        return (0.0, 0.0, 0.0)
    z = 1.96
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (p, max(0.0, center - half), min(1.0, center + half))


def pctci(k, n):
    p, lo, hi = wilson(k, n)
    return f"{100*p:.1f}\\% (95\\% CI {100*lo:.1f}--{100*hi:.1f})"


def load(path):
    by = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            by[r.get("server_name") or json.dumps(r.get("cmd"))] = r
    return list(by.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=str(DATA / "probe_results.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "paper" / "numbers.tex"))
    ap.add_argument("--frame", default=str(DATA / "frame_latest.jsonl"))
    ap.add_argument("--reprobe", default=str(DATA / "entrypoint_reprobe.jsonl"),
                    help="completed re-probe of entry-point-blocked PyPI servers")
    args = ap.parse_args()

    rows = load(Path(args.inp))
    n = len(rows)
    hs = sum(1 for r in rows if r.get("handshake_ok"))
    responders = [r for r in rows if r.get("handshake_ok")]
    n_resp = len(responders)

    def resp_rate(pred):
        k = sum(1 for r in responders for c in r.get("checks", []) if pred(c))
        return k, pctci(k, n_resp)

    err_as_result_k, err_as_result = resp_rate(
        lambda c: c["id"] == "tools-call-unknown" and c["verdict"] == "error-as-result")
    notypecheck_k, notypecheck = resp_rate(
        lambda c: c["id"] == "tools-call-invalid-args" and c["verdict"] == "fail")
    malformed_k, malformed = resp_rate(
        lambda c: c["id"] == "malformed-json" and c["verdict"] == "fail")

    frame_n = sum(1 for _ in open(args.frame, encoding="utf-8"))

    # Publisher clustering. Registry names are "namespace/server", and a single
    # publisher can account for hundreds of servers that share a template and
    # behave near-identically -- so they are not independent trials and the Wilson
    # intervals above are too narrow. Recompute each headline rate on a subset
    # holding one server per publisher, to bound how far the clustering moves it.
    def publisher(r):
        # The public release carries a hashed publisher_id, because pseudonymised
        # server names lose their namespace prefix. Prefer it when present so the
        # clustering check reproduces identically from the released dataset.
        return r.get("publisher_id") or (r.get("server_name") or "").split("/")[0]

    pub_counts = Counter(publisher(r) for r in rows)
    seen, uniq = set(), []
    for r in rows:
        p = publisher(r)
        if p not in seen:
            seen.add(p)
            uniq.append(r)
    uniq_resp = [r for r in uniq if r.get("handshake_ok")]
    uniq_hs = len(uniq_resp)
    top_n = pub_counts.most_common(1)[0][1] if pub_counts else 0
    top10_n = sum(v for _, v in pub_counts.most_common(10))

    def uniq_rate(cid, verdict):
        k = sum(1 for r in uniq_resp for c in r.get("checks", [])
                if c["id"] == cid and c["verdict"] == verdict)
        return pctci(k, uniq_hs)

    # Entry-point correction. `uvx <pkg>` resolves only when a PyPI package's console
    # script is named after the package, so servers whose script differs installed
    # fine but were never launched -- a harness artifact, not a server defect. We
    # re-probed ALL of them with the entry point resolved; those results correct the
    # runnability numbers. (An early 30-server pilot suggested a far higher recovery
    # rate; the complete re-probe supersedes it and is what we report.)
    reprobe = load(Path(args.reprobe)) if Path(args.reprobe).exists() else []
    ep_n = len(reprobe)
    ep_ok = sum(1 for r in reprobe if r.get("handshake_ok"))
    hs_corr = hs + ep_ok

    def reg_split(reg):
        sub = [r for r in rows if r.get("registry_type") == reg]
        return len(sub), sum(1 for r in sub if r.get("handshake_ok"))

    npm_n, npm_hs = reg_split("npm")
    pypi_n, pypi_hs = reg_split("pypi")
    npm_p = 100 * npm_hs / npm_n if npm_n else 0
    pypi_p = 100 * pypi_hs / pypi_n if pypi_n else 0
    pypi_p_corr = 100 * (pypi_hs + ep_ok) / pypi_n if pypi_n else 0

    macros = {
        "Nframe": f"{frame_n:,}",
        "Nprobed": f"{n:,}",
        "Nresponders": f"{n_resp:,}",
        "HandshakeRate": pctci(hs, n),
        "HandshakeCount": str(hs),
        "ErrAsResultRate": err_as_result,
        "ErrAsResultCount": str(err_as_result_k),
        "NoTypecheckRate": notypecheck,
        "MalformedDiesRate": malformed,
        # Publisher-clustering robustness check (Threats to Validity).
        "Npublishers": f"{len(pub_counts):,}",
        "NuniqPub": f"{len(uniq):,}",
        "TopPublisherN": f"{top_n:,}",
        "TopPublisherPct": f"{100*top_n/n:.1f}\\%",
        "TopTenPct": f"{100*top10_n/n:.1f}\\%",
        "HandshakeRatePub": pctci(uniq_hs, len(uniq)),
        "ErrAsResultRatePub": uniq_rate("tools-call-unknown", "error-as-result"),
        "NoTypecheckRatePub": uniq_rate("tools-call-invalid-args", "fail"),
        # Entry-point-corrected runnability (complete re-probe).
        "NEntrypointBlocked": f"{ep_n:,}",
        "EntrypointBlockedPct": f"{100*ep_n/pypi_n:.1f}\\%" if pypi_n else "-",
        "EntrypointRecovered": f"{ep_ok:,}",
        "EntrypointRecoveryRate": pctci(ep_ok, ep_n) if ep_n else "-",
        "HandshakeCountCorr": f"{hs_corr:,}",
        "HandshakeRateCorr": pctci(hs_corr, n),
        "NpmRate": f"{npm_p:.1f}\\%",
        "NpmN": f"{npm_n:,}",
        "PypiN": f"{pypi_n:,}",
        "PypiRateRaw": f"{pypi_p:.1f}\\%",
        "PypiRateCorr": pctci(pypi_hs + ep_ok, pypi_n) if pypi_n else "-",
        "GapRaw": f"{npm_p - pypi_p:.1f}",
        "GapCorr": f"{npm_p - pypi_p_corr:.1f}",
    }
    lines = ["% AUTO-GENERATED by driver/make_numbers.py -- do not edit by hand."]
    lines += [f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in macros.items()]
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({n} servers, {n_resp} responders)")
    for k, v in macros.items():
        print(f"  \\{k} = {v}")


if __name__ == "__main__":
    main()
