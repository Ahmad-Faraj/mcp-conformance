"""The interval arithmetic every reported rate depends on."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "driver"))

from stats import cluster_ci, cluster_diff_ci, design_effect, wilson  # noqa: E402


def test_wilson_matches_a_published_value():
    # 81 of 263, the worked example in Brown, Cai and DasGupta (2001), gives
    # a Wilson interval of about 0.255 to 0.366.
    p, lo, hi = wilson(81, 263)
    assert p == pytest.approx(81 / 263)
    assert lo == pytest.approx(0.2553, abs=0.002)
    assert hi == pytest.approx(0.3662, abs=0.002)


def test_wilson_stays_inside_zero_and_one():
    assert wilson(0, 10)[1] == 0.0
    assert wilson(10, 10)[2] == 1.0
    assert wilson(0, 0) == (0.0, 0.0, 0.0)


def test_cluster_ci_is_reproducible_under_its_fixed_seed():
    units = [(i % 7, i % 3 == 0) for i in range(300)]
    assert cluster_ci(units) == cluster_ci(units)


def test_clustering_widens_the_interval_when_publishers_are_homogeneous():
    """The reason the paper reports clustered intervals at all.

    Ten publishers, each shipping thirty identical servers: 300 trials that carry
    the information of ten. The clustered interval must be far wider than the
    binomial one, and the design effect well above one.
    """
    units = [(pub, pub < 5) for pub in range(10) for _ in range(30)]
    _, wlo, whi = wilson(150, 300)
    _, clo, chi = cluster_ci(units)
    assert (chi - clo) > 2 * (whi - wlo)
    assert design_effect(units) > 2


def test_independent_units_give_a_clustered_interval_near_wilson():
    units = [(i, i % 2 == 0) for i in range(400)]
    assert 0.7 < design_effect(units) < 1.4


def test_cluster_diff_ci_point_estimate_is_the_difference_in_rates():
    a = [(i, i < 60) for i in range(100)]          # 60%
    b = [(i + 1000, i < 40) for i in range(100)]   # 40%
    point, lo, hi = cluster_diff_ci(a, b)
    assert point == pytest.approx(20.0)
    assert lo < 20 < hi
