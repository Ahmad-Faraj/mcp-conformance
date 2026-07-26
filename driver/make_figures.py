"""Generate the paper's figures (PDF) from the dataset.

  figures/pipeline.pdf    -- method overview: frame -> sandbox -> checks -> verdicts
  figures/failures.pdf    -- RQ1: why servers never reach a handshake (ranked)
  figures/sdk.pdf         -- RQ4: the divergence tracks the SDK, not the author
  figures/by_registry.pdf -- RQ5: runnability differs by registry, conformance does not

Palette is a two-hue categorical set validated for CVD separation, lightness band,
chroma floor and surface contrast (blue/orange, worst-adjacent dE 22.8 protan).
Gray is de-emphasis ink only and never carries identity on its own: every category
that uses it is also direct-labeled.
"""

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrow, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FIG = ROOT / "paper" / "figures"

# Validated categorical pair + neutral ink.
BLUE, ORANGE = "#2b6cb0", "#dd6b20"
INK, MUTED, GRID = "#1a202c", "#718096", "#e2e8f0"

plt.rcParams.update({
    "font.size": 9,
    "axes.edgecolor": MUTED,
    "axes.labelcolor": INK,
    "text.color": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 200,
})

# Startup-failure classes. A server-side failure is the server's own fault; the
# environment bucket covers packaging, undeclared configuration, and the few runs
# our own harness interrupted (exit 137 = killed by the disk guard), which must not
# be charged to the server.
ENVIRONMENT = {"needs-auth-or-config", "install-error", "install-not-found",
               "crash-exit-137", "unclassified"}

PRETTY = {
    "crash-exit-1": "crash (exit 1)",
    "crash-exit-2": "crash (exit 2)",
    "crash-exit-127": "missing entry point (127)",
    "crash-exit-137": "interrupted by harness (137)",
    "crash-with-error-output": "abort with error output",
    "crash-python-exception": "uncaught Python exception",
    "exit-silent": "exits 0 without serving",
    "hang-no-reply": "hangs, never answers initialize",
    "needs-auth-or-config": "needs credentials / config",
    "install-error": "install failure",
    "install-not-found": "package not found",
}


def wilson(k, n):
    if not n:
        return 0.0, 0.0, 0.0
    z = 1.96
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return 100 * p, 100 * max(0.0, c - h), 100 * min(1.0, c + h)


def load(path):
    by = {}
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            by[r.get("server_name") or json.dumps(r.get("cmd"))] = r
    return list(by.values())


def finish(fig, name):
    fig.tight_layout()
    fig.savefig(FIG / name, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- pipeline ----
def fig_pipeline(rows, n_frame):
    """Method overview. A diagram, not a plot: the job is orientation."""
    fig, ax = plt.subplots(figsize=(6.6, 1.9))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 30)
    ax.axis("off")

    stages = [
        ("Registry\nsnapshot", f"{n_frame:,} servers"),
        ("Eligibility\nfilter", f"{len(rows):,} eligible"),
        ("Sandboxed\nexecution", "1 container\nper server"),
        ("Conformance\nprobe", "8 checks"),
        ("Verdicts", "per negotiated\nspec version"),
    ]
    w, gap = 15.5, 5.0
    x = 1.0
    for i, (title, sub) in enumerate(stages):
        ax.add_patch(FancyBboxPatch(
            (x, 9), w, 12, boxstyle="round,pad=0.6,rounding_size=1.2",
            linewidth=1.1, edgecolor=BLUE if i < 4 else ORANGE,
            facecolor="white"))
        ax.text(x + w / 2, 17.2, title, ha="center", va="center",
                fontsize=8.6, color=INK, weight="bold")
        ax.text(x + w / 2, 12.4, sub, ha="center", va="center",
                fontsize=7.6, color=MUTED)
        if i < len(stages) - 1:
            ax.add_patch(FancyArrow(x + w + 0.6, 15, gap - 2.0, 0,
                                    width=0.18, head_width=1.5, head_length=1.3,
                                    length_includes_head=True, color=MUTED))
        x += w + gap

    ax.text(1.0 + (w + gap) + w / 2, 5.6,
            "excludes remote-only,\ncredential-requiring",
            ha="center", va="center", fontsize=7.0, color=MUTED, style="italic")
    ax.text(1.0 + 2 * (w + gap) + w / 2, 5.6,
            "cap-drop ALL, no host mounts,\ndisposable cloud host",
            ha="center", va="center", fontsize=7.0, color=MUTED, style="italic")
    finish(fig, "pipeline.pdf")


# ---------------------------------------------------------------- failures ----
def fig_failures(rows):
    """RQ1. Ranked horizontal bars; artifact/config separated from real failures."""
    non = [r for r in rows if not r.get("handshake_ok")]
    counts = Counter(r.get("failure_class") or "unclassified" for r in non)

    items = [(PRETTY.get(k, k), v, k) for k, v in counts.most_common() if v >= 5]
    items.reverse()
    labels = [i[0] for i in items]
    vals = [i[1] for i in items]
    colors = [ORANGE if i[2] in ENVIRONMENT else BLUE for i in items]

    fig, ax = plt.subplots(figsize=(6.6, 3.3))
    y = range(len(items))
    ax.barh(list(y), vals, color=colors, height=0.62)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=8.4, color=INK)
    ax.set_xlabel(f"servers (of {len(non):,} that never reached a handshake)")
    ax.xaxis.grid(True, color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    for yi, v in zip(y, vals):
        ax.text(v + max(vals) * 0.012, yi, f"{v:,}", va="center",
                fontsize=8.0, color=INK)
    ax.set_xlim(0, max(vals) * 1.12)

    handles = [plt.Rectangle((0, 0), 1, 1, color=BLUE),
               plt.Rectangle((0, 0), 1, 1, color=ORANGE)]
    ax.legend(handles, ["server-side failure",
                        "environment: packaging, config, or harness"],
              frameon=False, fontsize=8, loc="lower right")
    finish(fig, "failures.pdf")


# --------------------------------------------------------------------- sdk ----
def fig_sdk():
    """RQ4. The headline: the divergence tracks the SDK, not the author."""
    path = DATA / "sdk_attribution.csv"
    if not path.exists():
        return
    label = {"none-handrolled": "no known SDK", "unknown": "metadata unavailable"}
    tab = defaultdict(Counter)
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tab[label.get(row["sdk_family"], row["sdk_family"])][row["unknown_verdict"]] += 1

    # Families with a handful of servers carry intervals too wide to read; they are
    # reported in Table~\ref{tab:sdk} rather than plotted.
    fams = [(f, sum(c.values())) for f, c in tab.items() if sum(c.values()) >= 25]
    fams.sort(key=lambda t: t[1])
    names, rates, los, his, ns = [], [], [], [], []
    for f, tot in fams:
        k = tab[f].get("error-as-result", 0)
        p, lo, hi = wilson(k, tot)
        names.append(f)
        rates.append(p)
        los.append(p - lo)
        his.append(hi - p)
        ns.append(tot)

    fig, ax = plt.subplots(figsize=(6.6, 2.9))
    y = range(len(names))
    ax.barh(list(y), rates, xerr=[los, his], color=BLUE, height=0.58,
            error_kw=dict(ecolor=MUTED, lw=1.0, capsize=2.5))
    ax.set_yticks(list(y))
    ax.set_yticklabels([f"{n}  (n={c:,})" for n, c in zip(names, ns)],
                       fontsize=8.4, color=INK)
    ax.set_xlabel("servers answering an unknown tool with an isError result (%)")
    ax.set_xlim(0, 108)
    ax.xaxis.grid(True, color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    # Anchor the value label past the CI whisker, not the bar end, so the two
    # never overlap.
    for yi, p, hi in zip(y, rates, his):
        ax.text(p + hi + 2.4, yi, f"{p:.0f}%", va="center", fontsize=8.0, color=INK)
    finish(fig, "sdk.pdf")


# ------------------------------------------------------------- by registry ----
def fig_by_registry(rows, reprobe):
    """RQ5. Runnability differs by registry; conformance does not."""
    ep_ok = sum(1 for r in reprobe if r.get("handshake_ok"))

    def reg(name):
        sub = [r for r in rows if r.get("registry_type") == name]
        hs = sum(1 for r in sub if r.get("handshake_ok"))
        resp = [r for r in sub if r.get("handshake_ok")]
        ear = sum(1 for r in resp for c in r.get("checks", [])
                  if c["id"] == "tools-call-unknown" and c["verdict"] == "error-as-result")
        return len(sub), hs, len(resp), ear

    npm_n, npm_hs, npm_r, npm_e = reg("npm")
    py_n, py_hs, py_r, py_e = reg("pypi")

    groups = [
        ("Handshake\n(runnability)",
         wilson(npm_hs, npm_n), wilson(py_hs + ep_ok, py_n)),
        ("error-as-result\n(conformance)",
         wilson(npm_e, npm_r), wilson(py_e, py_r)),
    ]

    fig, ax = plt.subplots(figsize=(5.4, 2.9))
    width = 0.3
    for i, (label, npm_v, py_v) in enumerate(groups):
        for j, (v, color) in enumerate(((npm_v, BLUE), (py_v, ORANGE))):
            p, lo, hi = v
            xpos = i + (j - 0.5) * width
            ax.bar(xpos, p, width * 0.88, yerr=[[p - lo], [hi - p]],
                   color=color, capsize=3, error_kw=dict(ecolor=MUTED, lw=1.0))
            ax.text(xpos, hi + 3.0, f"{p:.0f}%", ha="center",
                    fontsize=8.2, color=INK)
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels([g[0] for g in groups], fontsize=8.6, color=INK)
    ax.set_xlim(-0.45, len(groups) - 0.55)
    ax.set_ylabel("% of servers")
    ax.set_ylim(0, 118)
    ax.yaxis.grid(True, color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    # Explicit handles: bars carry error bars, so auto-legend picks the wrong artist.
    handles = [plt.Rectangle((0, 0), 1, 1, color=BLUE),
               plt.Rectangle((0, 0), 1, 1, color=ORANGE)]
    ax.legend(handles, ["npm", "PyPI"], frameon=False, fontsize=8.2,
              loc="upper center", bbox_to_anchor=(0.5, 1.16), ncol=2)
    finish(fig, "by_registry.pdf")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=str(DATA / "probe_final.jsonl"))
    ap.add_argument("--frame", default=str(DATA / "frame_latest.jsonl"))
    ap.add_argument("--reprobe", default=str(DATA / "entrypoint_reprobe.jsonl"))
    args = ap.parse_args()

    FIG.mkdir(parents=True, exist_ok=True)
    rows = load(args.inp)
    reprobe = load(args.reprobe) if Path(args.reprobe).exists() else []
    n_frame = sum(1 for _ in open(args.frame, encoding="utf-8"))

    fig_pipeline(rows, n_frame)
    fig_failures(rows)
    fig_sdk()
    fig_by_registry(rows, reprobe)
    print(f"wrote 4 figures to {FIG} from {len(rows):,} servers")


if __name__ == "__main__":
    main()
