"""Generate the paper's figures (PDF) from the dataset.

figures/funnel.pdf     -- the sampled->handshake funnel with loss causes.
figures/by_registry.pdf -- handshake yield + per-check pass rate by registry.

Uses a restrained, print-friendly style (no chartjunk, colorblind-safe).
"""

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FIG = ROOT / "paper" / "figures"

BLUE, GRAY, ORANGE = "#2b6cb0", "#a0aec0", "#dd6b20"
CHECK_ORDER = ["server-initialize", "ping", "tools-list", "tools-schema-valid",
               "tools-call-unknown", "tools-call-invalid-args", "malformed-json",
               "stdout-purity"]


def wilson_half(k, n):
    if n == 0:
        return 0
    z = 1.96
    p = k / n
    d = 1 + z * z / n
    return z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d


def load(path):
    by = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            by[r.get("server_name") or json.dumps(r.get("cmd"))] = r
    return list(by.values())


def funnel_fig(rows):
    n = len(rows)
    started = sum(1 for r in rows if r.get("started"))
    hs = sum(1 for r in rows if r.get("handshake_ok"))
    stages = ["Sampled", "Container\nstarted", "Handshake\ncompleted"]
    vals = [n, started, hs]
    fig, ax = plt.subplots(figsize=(5.2, 3.0))
    bars = ax.bar(stages, vals, color=[GRAY, BLUE, BLUE], width=0.6)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v}\n({100*v/n:.0f}%)",
                ha="center", va="bottom", fontsize=9)
    ax.set_ylabel("Servers")
    ax.set_ylim(0, n * 1.15)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIG / "funnel.pdf")
    plt.close(fig)


def by_registry_fig(rows):
    regs = ["npm", "pypi"]
    resp = defaultdict(list)
    hs = defaultdict(lambda: [0, 0])
    for r in rows:
        reg = r.get("registry_type")
        if reg not in regs:
            continue
        hs[reg][1] += 1
        if r.get("handshake_ok"):
            hs[reg][0] += 1
            resp[reg].append(r)

    checks = ["tools-call-invalid-args", "malformed-json"]
    labels = ["Handshake"] + ["type-check", "malformed-survive"]
    fig, ax = plt.subplots(figsize=(6.0, 3.2))
    x = range(len(labels))
    width = 0.38
    for i, reg in enumerate(regs):
        rates, errs = [], []
        ok, tot = hs[reg]
        rates.append(100 * ok / tot if tot else 0)
        errs.append(100 * wilson_half(ok, tot))
        for chk in checks:
            k = sum(1 for r in resp[reg] for c in r.get("checks", [])
                    if c["id"] == chk and c["verdict"] == "pass")
            nn = len(resp[reg])
            rates.append(100 * k / nn if nn else 0)
            errs.append(100 * wilson_half(k, nn))
        off = (i - 0.5) * width
        ax.bar([xx + off for xx in x], rates, width, yerr=errs, capsize=3,
               label=reg, color=BLUE if reg == "npm" else ORANGE)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("Pass rate (%)")
    ax.set_ylim(0, 105)
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIG / "by_registry.pdf")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=str(DATA / "probe_results.jsonl"))
    args = ap.parse_args()
    FIG.mkdir(parents=True, exist_ok=True)
    rows = load(Path(args.inp))
    funnel_fig(rows)
    by_registry_fig(rows)
    print(f"wrote figures to {FIG} from {len(rows)} servers")


if __name__ == "__main__":
    main()
