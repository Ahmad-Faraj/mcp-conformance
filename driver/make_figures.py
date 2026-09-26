"""Generate the paper's figures (PDF) from the dataset.

  figures/pipeline.pdf    -- method overview: frame -> sandbox -> checks -> verdicts
  figures/failures.pdf    -- RQ1: why servers never reach a handshake (ranked)
  figures/sdk.pdf         -- RQ4: the divergence tracks the SDK, not the author
  figures/by_registry.pdf -- RQ5: runnability differs by registry, conformance does not

Layout: label column flush left, bars, value column flush right. Every category is
direct-labeled, so colour never carries identity on its own.
"""

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
import matplotlib.ticker  # noqa: E402
import matplotlib.transforms  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from failure_classes import failure_class, harness_error  # noqa: E402
from stats import cluster_ci  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FIG = ROOT / "paper" / "figures"

# House palette: navy for the primary series (server faults, the hazard, npm) and
# light blue for the secondary one (environment, PyPI). The two differ strongly in
# lightness, so they stay separable in greyscale and for colour-blind readers.
NAVY, SKY = "#1d3557", "#9dbde0"
INK, MUTED, GRID, RULE, LIGHT = "#14213d", "#6b7280", "#e6e9ee", "#b9cde4", "#d5dae1"
TINT = "#f1f6fb"

# Figures are drawn at their printed size so no text is scaled: COL is one IEEE
# column. Fonts are embedded as TrueType (42),
# not Type 3, which PDF checkers reject.
COL = 3.45
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "font.size": 7.5,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "axes.edgecolor": MUTED,
    "axes.labelcolor": INK,
    "axes.labelsize": 7.5,
    "text.color": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7.5,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.linewidth": 0.6,
    "xtick.major.width": 0.6,
    "figure.dpi": 200,
})


# Startup-failure classes. A server-side failure is the server's own fault; the
# environment bucket covers packaging, undeclared configuration, and the few runs
# our own harness interrupted (exit 137 = killed by the disk guard), which must not
# be charged to the server.
ENVIRONMENT = {"entrypoint-not-provided", "needs-auth-or-config", "install-error", "install-not-found",
               "crash-exit-137", "unclassified"}

PRETTY = {
    "crash-exit-1": "crash (exit 1)",
    "crash-exit-2": "crash (exit 2)",
    "entrypoint-not-provided": "uvx entry-point artifact",
    "crash-exit-127": "command not found (exit 127)",
    "crash-exit-137": "interrupted by harness (137)",
    "crash-with-error-output": "abort with error output",
    "crash-python-exception": "uncaught Python exception",
    "exit-silent": "exits 0 without serving",
    "hang-no-reply": "hangs, no initialize reply",
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


# ------------------------------------------------------------------ layout ----
def label_width(fig, texts, **kw):
    """Widest of `texts` in figure-fraction units, measured with the real font."""
    r = fig.canvas.get_renderer()
    w = 0.0
    for t in texts:
        a = fig.text(0, 0, t, **kw)
        w = max(w, a.get_window_extent(r).width)
        a.remove()
    return w / (fig.get_figwidth() * fig.dpi)


def hbar_figure(labels, values, colors, xmax, xlabel, value_texts, height,
                errors=None, ticks=None, headers=None, top_pad=0.10):
    """Label column | bars | value column, the label column flush left.

    `headers` maps a row index (top-down) to a bold group heading drawn in the
    label column above that row, so groups separate without a legend.
    """
    headers = headers or {}
    fig = plt.figure(figsize=(COL, height))
    lab_w = label_width(fig, labels, fontsize=7.5)
    val_w = label_width(fig, value_texts, fontsize=7.5)
    left, right = lab_w + 0.035, 1 - val_w - 0.035
    ax = fig.add_axes([left, 0.36 / height, right - left,
                       1 - (0.36 + top_pad) / height])

    ys, y = [], 0.0
    for i in range(len(labels)):
        if i in headers:
            y += 1.05 if i else 0.95
        ys.append(-y)
        y += 1
    for i, (v, c) in enumerate(zip(values, colors)):
        kw = {}
        if errors:
            kw = dict(xerr=[[errors[i][0]], [errors[i][1]]],
                      error_kw=dict(ecolor=NAVY, lw=0.7, capsize=1.6))
        ax.barh(ys[i], v, color=c, height=0.62, **kw)

    ax.set_xlim(0, xmax)
    ax.set_ylim(ys[-1] - 0.6, 0.6)
    tl = matplotlib.transforms.blended_transform_factory(fig.transFigure, ax.transData)
    for i, text in headers.items():
        ax.text(0.0, ys[i] + 1.0, text, transform=tl, ha="left", va="center",
                fontsize=7.2, color=INK, weight="bold")
    ax.set_yticks([])
    for s in ("left", "right", "top"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(RULE)
    ax.xaxis.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(axis="x", length=0, pad=3, labelcolor=MUTED, labelsize=7)
    if ticks is not None:
        ax.set_xticks(ticks)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
        lambda v, _: f"{v:,.0f}"))
    ax.set_xlabel(xlabel, fontsize=7, color=MUTED, labelpad=3)

    for yi, lab, vt in zip(ys, labels, value_texts):
        ax.text(0.0, yi, lab, transform=tl, ha="left", va="center",
                fontsize=7.5, color=INK)
        ax.text(1.0, yi, vt, transform=tl, ha="right", va="center",
                fontsize=7.5, color=INK)
    return fig, ax, ys


def save(fig, name):
    fig.savefig(FIG / name)
    plt.close(fig)


# ---------------------------------------------------------------- pipeline ----
def fig_pipeline(rows, n_frame):
    """Method overview as a numbered stack: one row per stage, top to bottom."""
    stages = [
        ("Registry snapshot", f"{n_frame:,} servers, official registry"),
        ("Eligibility filter", f"{len(rows):,} self-contained stdio servers"),
        ("Sandboxed execution", "one disposable container per server"),
        ("Conformance probe", "8 checks over stdio"),
        ("Verdicts", "graded per negotiated version"),
    ]
    row_h, gap = 0.235, 0.085
    H = len(stages) * row_h + (len(stages) - 1) * gap + 0.02
    fig = plt.figure(figsize=(COL, H))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, COL)
    ax.set_ylim(0, H)
    ax.axis("off")

    top = H - 0.01
    for i, (title, desc) in enumerate(stages):
        y0 = top - row_h
        ax.add_patch(plt.Rectangle((0.01, y0), COL - 0.02, row_h, facecolor=TINT,
                                   edgecolor=RULE, linewidth=0.6))
        ax.add_patch(plt.Rectangle((0.01, y0), 0.045, row_h, facecolor=NAVY,
                                   edgecolor="none"))
        yc = y0 + row_h / 2
        ax.text(0.13, yc, f"{i + 1}", ha="left", va="center", fontsize=7.5,
                color=MUTED, weight="bold")
        ax.text(0.25, yc, title, ha="left", va="center", fontsize=7.5,
                color=INK, weight="bold")
        ax.text(1.45, yc, desc, ha="left", va="center", fontsize=7.2, color=INK)
        if i < len(stages) - 1:
            ax.annotate("", xy=(COL / 2, y0 - gap + 0.008), xytext=(COL / 2, y0 - 0.008),
                        arrowprops=dict(arrowstyle="-|>", color=MUTED, lw=0.6,
                                        mutation_scale=5, shrinkA=0, shrinkB=0))
        top = y0 - gap
    save(fig, "pipeline.pdf")


# ---------------------------------------------------------------- failures ----
def fig_failures(rows):
    """RQ1. Ranked bars; packaging/config/harness separated from real failures."""
    non = [r for r in rows if not r.get("handshake_ok") and not harness_error(r)]
    counts = Counter(failure_class(r) for r in non)
    items = [(PRETTY.get(k, k), v, k) for k, v in counts.most_common() if v >= 5]

    fig, ax, ys = hbar_figure(
        [i[0] for i in items], [i[1] for i in items],
        [SKY if i[2] in ENVIRONMENT else NAVY for i in items],
        xmax=max(i[1] for i in items) * 1.02,
        xlabel=f"servers, of {len(non):,} with no handshake",
        value_texts=[f"{i[1]:,}" for i in items], height=2.5,
        ticks=[0, 100, 200, 300, 400], top_pad=0.27)
    handles = [plt.Rectangle((0, 0), 1, 1, color=NAVY),
               plt.Rectangle((0, 0), 1, 1, color=SKY)]
    # Key sits above the chart, flush with the label column, so it never overlaps
    # a bar.
    fig.legend(handles, ["server-side failure", "packaging, config or harness"],
               frameon=False, fontsize=7, loc="upper left", bbox_to_anchor=(0, 1),
               ncol=2, handlelength=0.9, handleheight=0.9, columnspacing=1.4,
               borderaxespad=0, borderpad=0.1, labelcolor=INK)
    save(fig, "failures.pdf")


# --------------------------------------------------------------------- sdk ----
def fig_sdk():
    """RQ4. The divergence tracks the SDK, not the author."""
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
    fams.sort(key=lambda t: -t[1])
    labels, rates, errs = [], [], []
    for f, tot in fams:
        p, lo, hi = wilson(tab[f].get("error-as-result", 0), tot)
        labels.append(f"{f} (n={tot:,})")
        rates.append(p)
        errs.append((p - lo, hi - p))

    fig, ax, _ = hbar_figure(
        labels, rates, [NAVY] * len(rates), xmax=100,
        xlabel="% answering an unknown tool with isError",
        value_texts=[f"{p:.1f}%" for p in rates], height=1.35, errors=errs,
        ticks=[0, 25, 50, 75, 100])
    save(fig, "sdk.pdf")


# ------------------------------------------------------------- by registry ----
def fig_by_registry(rows, reprobe):
    """RQ5. Runnability differs by registry; conformance does not."""

    def pub(r):
        return r.get("publisher_id") or (r.get("server_name") or "").split("/")[0]

    def ci(sub, pred):
        """Publisher-cluster bootstrap interval, in percent, matching the paper."""
        p, lo, hi = cluster_ci([(pub(r), pred(r)) for r in sub])
        return 100 * p, 100 * lo, 100 * hi

    def reg(name):
        sub = [r for r in rows if r.get("registry_type") == name
               and not harness_error(r)]
        resp = [r for r in sub if r.get("handshake_ok")]
        return sub, resp

    npm_all, npm_resp = reg("npm")
    py_all, py_resp = reg("pypi")
    started = lambda r: bool(r.get("handshake_ok"))  # noqa: E731
    ear = lambda r: any(c["id"] == "tools-call-unknown"  # noqa: E731
                        and c["verdict"] == "error-as-result"
                        for c in r.get("checks", []))
    # PyPI runnability is shown after the entry-point correction, so the recovered
    # servers are folded in before the interval is taken.
    ep_ids = {r.get("server_name") for r in reprobe if r.get("handshake_ok")}
    py_corr = lambda r: bool(r.get("handshake_ok")) or r.get("server_name") in ep_ids  # noqa: E731
    rows_ = [
        ("npm", ci(npm_all, started), len(npm_all), NAVY),
        ("PyPI", ci(py_all, py_corr), len(py_all), SKY),
        ("npm", ci(npm_resp, ear), len(npm_resp), NAVY),
        ("PyPI", ci(py_resp, ear), len(py_resp), SKY),
    ]
    fig, ax, _ = hbar_figure(
        [f"{r[0]} (n={r[2]:,})" for r in rows_], [r[1][0] for r in rows_],
        [r[3] for r in rows_], xmax=100, xlabel="% of servers",
        value_texts=[f"{r[1][0]:.1f}%" for r in rows_], height=1.55,
        errors=[(r[1][0] - r[1][1], r[1][2] - r[1][0]) for r in rows_],
        ticks=[0, 25, 50, 75, 100],
        headers={0: "completes a handshake",
                 2: "answers an unknown tool with isError"})
    save(fig, "by_registry.pdf")


# ------------------------------------------------------------ consequences ----
def fig_consequences():
    """Decompose 'fails to reject a wrong-typed argument' by what the client gets.

    A single stacked bar: the coarse verdict splits roughly in half, and only one
    half is a hazard the client cannot detect. The point is the split, so the split
    is the whole chart.
    """
    path = DATA / "consequences.json"
    if not path.exists():
        return
    cons = json.loads(path.read_text(encoding="utf-8"))
    silent = len(cons.get("silent-execution", []))
    inband = len(cons.get("in-band-error", []))
    unclass = len(cons.get("unparsed", [])) + len(cons.get("no-transcript", []))
    total = silent + inband + unclass + len(cons.get("empty-result", []))

    fig = plt.figure(figsize=(COL, 0.72))
    ax = fig.add_axes([0.005, 0, 0.99, 1])
    segs = [
        (silent, NAVY, "executed the tool,\nno error signalled", "left", "white"),
        (inband, SKY, "problem reported\nin the result text", "center", INK),
        (unclass, LIGHT, "not\nclassifiable", "right", INK),
    ]
    left = 0
    for v, color, label, align, tc in segs:
        ax.barh(0, v, left=left, height=0.5, color=color,
                edgecolor="white", linewidth=0.8)
        ax.text(left + v / 2, 0, f"{v}", ha="center", va="center", fontsize=7.5,
                color=tc, weight="bold")
        xl = {"left": left, "center": left + v / 2, "right": left + v}[align]
        ax.text(xl, -0.36, label, ha=align, va="top", fontsize=7,
                color=INK, linespacing=1.1)
        left += v
    ax.set_xlim(0, total)
    ax.set_ylim(-0.95, 0.27)
    ax.axis("off")
    save(fig, "consequences.pdf")


def main():
    global DATA
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=str(DATA / "probe_final.jsonl"))
    ap.add_argument("--frame", default=str(DATA / "frame_latest.jsonl"))
    ap.add_argument("--reprobe", default=str(DATA / "entrypoint_reprobe.jsonl"))
    ap.add_argument("--data", default=str(DATA),
                    help="directory holding sdk_attribution.csv and consequences.json")
    args = ap.parse_args()
    DATA = Path(args.data)

    FIG.mkdir(parents=True, exist_ok=True)
    rows = load(args.inp)
    reprobe = load(args.reprobe) if Path(args.reprobe).exists() else []
    n_frame = sum(1 for _ in open(args.frame, encoding="utf-8"))

    fig_pipeline(rows, n_frame)
    fig_failures(rows)
    fig_sdk()
    fig_by_registry(rows, reprobe)
    fig_consequences()
    print(f"wrote 5 figures to {FIG} from {len(rows):,} servers")


if __name__ == "__main__":
    main()
