"""Shared interval estimation for the census.

Two estimators live here so the paper, the tables and the figures cannot disagree.

wilson()  is the textbook binomial interval. It assumes independent trials.

cluster_ci() resamples publishers, not servers. Registry names are namespace/server and
one publisher can ship hundreds of servers from a single template, so servers are not
independent trials and a binomial interval is too narrow. The published rate is the point
estimate either way; only the interval changes.
"""

import math
from collections import defaultdict

import numpy as np

Z = 1.96
BOOTSTRAP_DRAWS = 2000
SEED = 20260719  # the crawl date, so the interval is reproducible


def wilson(k: int, n: int):
    """95% Wilson score interval for a proportion."""
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    denom = 1 + Z * Z / n
    center = (p + Z * Z / (2 * n)) / denom
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / denom
    return (p, max(0.0, center - half), min(1.0, center + half))


def cluster_ci(units, seed: int = SEED, draws: int = BOOTSTRAP_DRAWS):
    """95% percentile bootstrap interval over publisher clusters.

    units: iterable of (cluster_id, hit) where hit is 1 when the unit shows the property
    and 0 when it does not. Returns (point, lo, hi).
    """
    by = defaultdict(list)
    for cid, hit in units:
        by[cid].append(1.0 if hit else 0.0)
    clusters = list(by.values())
    if not clusters:
        return (0.0, 0.0, 0.0)
    total = sum(len(c) for c in clusters)
    point = sum(sum(c) for c in clusters) / total

    sums = np.array([sum(c) for c in clusters], dtype=float)
    sizes = np.array([len(c) for c in clusters], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(clusters), size=(draws, len(clusters)))
    boot = sums[idx].sum(axis=1) / sizes[idx].sum(axis=1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return (point, float(lo), float(hi))


def cluster_diff_ci(units_a, units_b, seed: int = SEED, draws: int = BOOTSTRAP_DRAWS):
    """95% bootstrap interval for the difference in rates between two groups.

    Publishers are resampled once and both group rates are recomputed from the same
    draw, because a publisher can ship servers into both groups. Returns the difference
    in percentage points as (point, lo, hi).
    """
    by = defaultdict(lambda: ([], []))
    for cid, hit in units_a:
        by[cid][0].append(1.0 if hit else 0.0)
    for cid, hit in units_b:
        by[cid][1].append(1.0 if hit else 0.0)
    clusters = list(by.values())
    if not clusters:
        return (0.0, 0.0, 0.0)

    a_sum = np.array([sum(c[0]) for c in clusters], dtype=float)
    a_n = np.array([len(c[0]) for c in clusters], dtype=float)
    b_sum = np.array([sum(c[1]) for c in clusters], dtype=float)
    b_n = np.array([len(c[1]) for c in clusters], dtype=float)
    point = 100 * (a_sum.sum() / a_n.sum() - b_sum.sum() / b_n.sum())

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(clusters), size=(draws, len(clusters)))
    with np.errstate(invalid="ignore", divide="ignore"):
        boot = 100 * (a_sum[idx].sum(axis=1) / a_n[idx].sum(axis=1)
                      - b_sum[idx].sum(axis=1) / b_n[idx].sum(axis=1))
    boot = boot[np.isfinite(boot)]
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return (point, float(lo), float(hi))


def design_effect(units) -> float:
    """Ratio of the clustered interval width to the Wilson width, as a reported diagnostic."""
    units = list(units)
    k = sum(1 for _, hit in units if hit)
    n = len(units)
    _, wlo, whi = wilson(k, n)
    _, clo, chi = cluster_ci(units)
    if whi - wlo == 0:
        return 1.0
    return (chi - clo) / (whi - wlo)
