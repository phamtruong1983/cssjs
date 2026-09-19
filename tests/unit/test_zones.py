"""Tests for support/resistance zone construction (src/market_structure/zones.py).

Per docs/DAO_GAM_RULES.md Section 3 rule 3 and docs/DATA_SCHEMA.md
Section 4. Builds on find_swings (src/market_structure/swings.py),
already tested in tests/unit/test_swings.py -- these tests only exercise
zone construction, not swing detection itself.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.market_structure.swings import find_swings  # noqa: E402
from src.market_structure.zones import (  # noqa: E402
    RESULT_COLUMNS,
    TICK,
    _validate_as_of,
    _validate_min_touches,
    _validate_width,
    create_zones,
)

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")


def make_df(highs, lows, index=None):
    df = pd.DataFrame({"high": highs, "low": lows})
    if index is not None:
        df.index = index
    return df


def load_fixture_h1(name):
    return pd.read_csv(os.path.join(FIXTURES_DIR, name, "h1.csv"))


# ---------------------------------------------------------------------------
# Two swings at the same level -> touch_count == 2
# ---------------------------------------------------------------------------

# Two symmetric troughs at low=100, both at idx 3 and idx 9.
TWO_TOUCH_LOWS = [150, 140, 130, 100, 130, 140, 150, 140, 130, 100, 130, 140, 150]
TWO_TOUCH_HIGHS = [x + 50 for x in TWO_TOUCH_LOWS]


def test_two_swings_same_level_gives_touch_count_2():
    df = make_df(TWO_TOUCH_HIGHS, TWO_TOUCH_LOWS)
    result = create_zones(df, as_of=len(df) - 1, n=3)
    support = result[result["side"] == "support"]
    assert len(support) == 2  # one row per anchor (idx 3 and idx 9); see ASSUMPTIONS
    for _, row in support.iterrows():
        assert row["anchor_idx"] in (3, 9)
        assert row["zone_center"] == pytest.approx(100.0)
        assert row["touch_count"] == 2
        assert row["touch_idxs"] == [3, 9]
        assert row["zone_low"] == pytest.approx(99.5)
        assert row["zone_high"] == pytest.approx(100.5)


# ---------------------------------------------------------------------------
# A single, isolated swing -> not a valid zone (touch_count 1 < min_touches)
# ---------------------------------------------------------------------------

SINGLE_SWING_LOWS = [150, 140, 130, 100, 130, 140, 160, 180, 200, 220, 240, 260, 280]
SINGLE_SWING_HIGHS = [x + 50 for x in SINGLE_SWING_LOWS]


def test_single_isolated_swing_is_not_a_valid_zone():
    df = make_df(SINGLE_SWING_HIGHS, SINGLE_SWING_LOWS)
    result = create_zones(df, as_of=len(df) - 1, n=3)
    assert len(result[result["side"] == "support"]) == 0


# ---------------------------------------------------------------------------
# A swing outside the band is not counted as a touch
# ---------------------------------------------------------------------------

# Troughs at idx3=100, idx9=100 (same level), idx15=110 (outside the
# default width=1.0 band around 100, i.e. outside [99.5, 100.5]).
OUTSIDE_BAND_LOWS = [
    150, 140, 130, 100, 130, 140, 150, 140, 130, 100, 130, 140, 150, 140, 130, 110, 140, 160, 180,
]
OUTSIDE_BAND_HIGHS = [x + 50 for x in OUTSIDE_BAND_LOWS]


def test_swing_outside_band_not_counted_as_touch():
    df = make_df(OUTSIDE_BAND_HIGHS, OUTSIDE_BAND_LOWS)
    result = create_zones(df, as_of=len(df) - 1, n=3, width=1.0)
    zone_at_3 = result[(result["side"] == "support") & (result["anchor_idx"] == 3)]
    assert len(zone_at_3) == 1
    row = zone_at_3.iloc[0]
    assert row["touch_count"] == 2
    assert row["touch_idxs"] == [3, 9]
    assert 15 not in row["touch_idxs"]


def test_wider_width_pulls_in_the_previously_excluded_swing():
    df = make_df(OUTSIDE_BAND_HIGHS, OUTSIDE_BAND_LOWS)
    result = create_zones(df, as_of=len(df) - 1, n=3, width=21.0)  # band [89.5, 110.5]
    zone_at_3 = result[(result["side"] == "support") & (result["anchor_idx"] == 3)]
    row = zone_at_3.iloc[0]
    assert row["touch_count"] == 3
    assert row["touch_idxs"] == [3, 9, 15]


# ---------------------------------------------------------------------------
# A swing exactly at the band boundary IS counted (inclusive comparison)
# ---------------------------------------------------------------------------

BOUNDARY_LOWS = [150, 140, 130, 100, 130, 140, 150, 140, 130, 100.5, 130, 140, 150]
BOUNDARY_HIGHS = [x + 50 for x in BOUNDARY_LOWS]


def test_swing_exactly_at_boundary_counts_as_touch():
    df = make_df(BOUNDARY_HIGHS, BOUNDARY_LOWS)
    # anchor at idx3 (100.0) -> band [99.5, 100.5]; idx9 = 100.5 is exactly zone_high
    result = create_zones(df, as_of=len(df) - 1, n=3, width=1.0)
    zone_at_3 = result[(result["side"] == "support") & (result["anchor_idx"] == 3)]
    row = zone_at_3.iloc[0]
    assert row["touch_count"] == 2
    assert row["touch_idxs"] == [3, 9]


# ---------------------------------------------------------------------------
# Support and resistance are tracked independently
# ---------------------------------------------------------------------------

# Two low troughs at 100 (idx3, idx9) and two high peaks at 900 (idx6, idx?)
# far away in price, both independently valid.
SEP_LOWS = [
    150, 140, 130, 100, 130, 140, 150, 140, 130, 100, 130, 140, 150, 140, 130, 120, 140, 160, 180, 200, 220,
]
SEP_HIGHS = [
    250, 260, 270, 280, 290, 300, 900, 300, 290, 280, 270, 260, 250, 260, 270, 900, 270, 260, 250, 240, 230,
]


def test_support_and_resistance_do_not_cross_contaminate():
    df = make_df(SEP_HIGHS, SEP_LOWS)
    result = create_zones(df, as_of=len(df) - 1, n=3, width=1.0)
    support = result[result["side"] == "support"]
    resistance = result[result["side"] == "resistance"]

    assert len(support) == 2
    assert len(resistance) == 2

    for _, row in support.iterrows():
        assert row["zone_center"] == pytest.approx(100.0)
        assert row["touch_idxs"] == [3, 9]

    for _, row in resistance.iterrows():
        assert row["zone_center"] == pytest.approx(900.0)
        assert row["touch_idxs"] == [6, 15]


# ---------------------------------------------------------------------------
# min_touches
# ---------------------------------------------------------------------------


def test_custom_min_touches_3_rejects_2_touch_zone():
    df = make_df(OUTSIDE_BAND_HIGHS, OUTSIDE_BAND_LOWS)
    result = create_zones(df, as_of=len(df) - 1, n=3, width=1.0, min_touches=3)
    assert len(result[result["side"] == "support"]) == 0


def test_min_touches_1_accepts_isolated_swing():
    df = make_df(SINGLE_SWING_HIGHS, SINGLE_SWING_LOWS)
    result = create_zones(df, as_of=len(df) - 1, n=3, min_touches=1)
    support = result[result["side"] == "support"]
    assert len(support) == 1
    assert support.iloc[0]["touch_count"] == 1
    assert support.iloc[0]["touch_idxs"] == [3]


def test_min_touches_invalid_raises():
    df = make_df(TWO_TOUCH_HIGHS, TWO_TOUCH_LOWS)
    with pytest.raises(ValueError, match="min_touches must be >= 1"):
        create_zones(df, as_of=len(df) - 1, min_touches=0)


def test_min_touches_non_int_raises():
    df = make_df(TWO_TOUCH_HIGHS, TWO_TOUCH_LOWS)
    with pytest.raises(TypeError, match="min_touches must be an int"):
        create_zones(df, as_of=len(df) - 1, min_touches=2.5)


# ---------------------------------------------------------------------------
# width validation
# ---------------------------------------------------------------------------


def test_width_zero_raises():
    df = make_df(TWO_TOUCH_HIGHS, TWO_TOUCH_LOWS)
    with pytest.raises(ValueError, match="width must be > 0"):
        create_zones(df, as_of=len(df) - 1, width=0)


def test_width_negative_raises():
    df = make_df(TWO_TOUCH_HIGHS, TWO_TOUCH_LOWS)
    with pytest.raises(ValueError, match="width must be > 0"):
        create_zones(df, as_of=len(df) - 1, width=-1.0)


def test_width_non_numeric_raises():
    df = make_df(TWO_TOUCH_HIGHS, TWO_TOUCH_LOWS)
    with pytest.raises(TypeError, match="width must be a number"):
        create_zones(df, as_of=len(df) - 1, width="1.0")


# ---------------------------------------------------------------------------
# as_of validation
# ---------------------------------------------------------------------------


def test_as_of_negative_raises():
    df = make_df(TWO_TOUCH_HIGHS, TWO_TOUCH_LOWS)
    with pytest.raises(ValueError, match="as_of must be >= 0"):
        create_zones(df, as_of=-1)


def test_as_of_non_int_raises():
    df = make_df(TWO_TOUCH_HIGHS, TWO_TOUCH_LOWS)
    with pytest.raises(TypeError, match="as_of must be an int"):
        create_zones(df, as_of=5.5)


# ---------------------------------------------------------------------------
# NaN / missing columns (delegated to find_swings)
# ---------------------------------------------------------------------------


def test_missing_low_column_raises():
    df = pd.DataFrame({"high": TWO_TOUCH_HIGHS})
    with pytest.raises(ValueError, match="missing required column"):
        create_zones(df, as_of=len(df) - 1)


def test_nan_in_high_raises():
    highs = list(TWO_TOUCH_HIGHS)
    highs[5] = np.nan
    df = make_df(highs, TWO_TOUCH_LOWS)
    with pytest.raises(ValueError, match="NaN"):
        create_zones(df, as_of=len(df) - 1)


# ---------------------------------------------------------------------------
# Index / idx handling: anchor_idx and touch_idxs are positional, not labels
# ---------------------------------------------------------------------------


def test_anchor_and_touch_idxs_are_positional_with_non_default_index():
    idx = pd.date_range("2024-01-02", periods=len(TWO_TOUCH_LOWS), freq="h")
    df = make_df(TWO_TOUCH_HIGHS, TWO_TOUCH_LOWS, index=idx)
    result = create_zones(df, as_of=len(df) - 1, n=3)
    support = result[result["side"] == "support"]
    assert set(support["anchor_idx"]) == {3, 9}
    for _, row in support.iterrows():
        assert row["touch_idxs"] == [3, 9]


def test_result_dataframe_has_default_range_index():
    df = make_df(TWO_TOUCH_HIGHS, TWO_TOUCH_LOWS)
    result = create_zones(df, as_of=len(df) - 1, n=3)
    assert list(result.index) == list(range(len(result)))


# ---------------------------------------------------------------------------
# Synthetic look-ahead check
# ---------------------------------------------------------------------------


def test_synthetic_lookahead_zone_not_valid_before_second_swing_confirmed():
    df = make_df(TWO_TOUCH_HIGHS, TWO_TOUCH_LOWS)
    # idx 9 confirms at 9+3=12; as_of=9 is one short -> only anchor 3 known,
    # touch_count=1 -> no valid support zone yet.
    result_early = create_zones(df, as_of=9, n=3)
    assert len(result_early[result_early["side"] == "support"]) == 0

    # as_of=12 (full data, len-1): idx 9 confirmed -> valid 2-touch zone.
    result_full = create_zones(df, as_of=12, n=3)
    assert len(result_full[result_full["side"] == "support"]) == 2


def test_synthetic_lookahead_truncated_equals_full_at_same_as_of():
    df = make_df(TWO_TOUCH_HIGHS, TWO_TOUCH_LOWS)
    for as_of in (6, 9, 10, 12):
        full = create_zones(df, as_of=as_of, n=3)
        truncated = create_zones(df.iloc[: as_of + 1], as_of=as_of, n=3)
        pd.testing.assert_frame_equal(full.reset_index(drop=True), truncated.reset_index(drop=True))


# ---------------------------------------------------------------------------
# Fixture 01 (BUY valid) -- real h1.csv, 25 rows (idx 0-24)
# ---------------------------------------------------------------------------


def test_fixture_01_as_of_19_no_valid_support_zone_yet():
    df = load_fixture_h1("01_buy_valid")
    result = create_zones(df, as_of=19, n=3)
    assert len(result[result["side"] == "support"]) == 0


@pytest.mark.parametrize("as_of", [20, 21])
def test_fixture_01_support_zone_valid_from_as_of_20(as_of):
    df = load_fixture_h1("01_buy_valid")
    result = create_zones(df, as_of=as_of, n=3)
    support = result[result["side"] == "support"]

    # per ASSUMPTIONS: one row per anchor -- idx 5 and idx 17 both anchor
    # a zone at the same level, so 2 rows, not 1 (see module docstring and
    # the discrepancy noted in the final report to the user).
    assert len(support) == 2
    for _, row in support.iterrows():
        assert row["anchor_idx"] in (5, 17)
        assert row["zone_center"] == pytest.approx(2000.00)
        assert row["zone_low"] == pytest.approx(1999.50)
        assert row["zone_high"] == pytest.approx(2000.50)
        assert row["touch_count"] == 2
        assert row["touch_idxs"] == [5, 17]

    resistance = result[result["side"] == "resistance"]
    assert len(resistance) == 0


@pytest.mark.parametrize("as_of", [21, 22, 23])
def test_fixture_01_swing_high_idx21_not_yet_an_anchor(as_of):
    df = load_fixture_h1("01_buy_valid")
    result = create_zones(df, as_of=as_of, n=3)
    assert 21 not in set(result["anchor_idx"])


def test_fixture_01_as_of_24_idx21_confirmed_but_still_invalid_1_touch():
    df = load_fixture_h1("01_buy_valid")
    result_21 = create_zones(df, as_of=21, n=3)
    result_24 = create_zones(df, as_of=24, n=3)

    # idx 21 (high=2050) is now confirmed (21+3=24<=24) but forms a
    # 1-touch resistance zone (no other high swing within [2049.5,
    # 2050.5]) -> invalid, so it does not appear in the result.
    assert 21 not in set(result_24["anchor_idx"])

    # the support side is unaffected and identical to as_of=21.
    pd.testing.assert_frame_equal(
        result_21[result_21["side"] == "support"].reset_index(drop=True),
        result_24[result_24["side"] == "support"].reset_index(drop=True),
    )


def test_fixture_01_lookahead_truncated_equals_full():
    df = load_fixture_h1("01_buy_valid")
    for as_of in (19, 20, 21, 22, 23, 24):
        full = create_zones(df, as_of=as_of, n=3)
        truncated = create_zones(df.iloc[: as_of + 1], as_of=as_of, n=3)
        pd.testing.assert_frame_equal(full.reset_index(drop=True), truncated.reset_index(drop=True))


# ---------------------------------------------------------------------------
# Fixture 02 (SELL valid) -- mirror of fixture 01
# ---------------------------------------------------------------------------


def test_fixture_02_as_of_19_no_valid_resistance_zone_yet():
    df = load_fixture_h1("02_sell_valid")
    result = create_zones(df, as_of=19, n=3)
    assert len(result[result["side"] == "resistance"]) == 0


@pytest.mark.parametrize("as_of", [20, 21])
def test_fixture_02_resistance_zone_valid_from_as_of_20(as_of):
    df = load_fixture_h1("02_sell_valid")
    result = create_zones(df, as_of=as_of, n=3)
    resistance = result[result["side"] == "resistance"]

    assert len(resistance) == 2
    for _, row in resistance.iterrows():
        assert row["anchor_idx"] in (5, 17)
        assert row["zone_center"] == pytest.approx(2000.00)
        assert row["zone_low"] == pytest.approx(1999.50)
        assert row["zone_high"] == pytest.approx(2000.50)
        assert row["touch_count"] == 2
        assert row["touch_idxs"] == [5, 17]

    support = result[result["side"] == "support"]
    assert len(support) == 0


def test_fixture_02_lookahead_truncated_equals_full():
    df = load_fixture_h1("02_sell_valid")
    for as_of in (19, 20, 21, 22, 23, 24):
        full = create_zones(df, as_of=as_of, n=3)
        truncated = create_zones(df.iloc[: as_of + 1], as_of=as_of, n=3)
        pd.testing.assert_frame_equal(full.reset_index(drop=True), truncated.reset_index(drop=True))


# ---------------------------------------------------------------------------
# Performance-optimization equivalence: brute-force reference vs. the
# current (vectorized touch-counting) create_zones. The brute-force body
# below is copied VERBATIM from `git show HEAD:src/market_structure/zones.py`
# (the O(P^2) touch-counting implementation) as of the commit immediately
# before the numpy/searchsorted optimization, so this test proves the
# optimization changed nothing observable.
# ---------------------------------------------------------------------------


def _round_tick_ref(x: float) -> float:
    return round(round(x / TICK) * TICK, 10)


def _create_zones_brute_force(
    df: pd.DataFrame,
    as_of: int,
    n: int = 3,
    width: float = 1.00,
    min_touches: int = 2,
) -> pd.DataFrame:
    """Verbatim pre-optimization reference (O(P^2) touch counting)."""
    _validate_as_of(as_of, len(df))
    _validate_width(width)
    _validate_min_touches(min_touches)

    truncated = df.iloc[: as_of + 1]
    swings = find_swings(truncated, n=n)

    high = truncated["high"].to_numpy()
    low = truncated["low"].to_numpy()

    high_swing_positions = [i for i in range(len(truncated)) if bool(swings["is_swing_high"].iloc[i])]
    low_swing_positions = [i for i in range(len(truncated)) if bool(swings["is_swing_low"].iloc[i])]

    rows = []

    for side, positions, prices in (
        ("resistance", high_swing_positions, high),
        ("support", low_swing_positions, low),
    ):
        for anchor_pos in positions:
            center = float(prices[anchor_pos])
            zone_low = _round_tick_ref(center - width / 2)
            zone_high = _round_tick_ref(center + width / 2)

            touch_idxs = [
                p
                for p in positions
                if zone_low <= _round_tick_ref(float(prices[p])) <= zone_high
            ]
            touch_count = len(touch_idxs)

            if touch_count >= min_touches:
                rows.append(
                    {
                        "side": side,
                        "anchor_idx": anchor_pos,
                        "zone_center": center,
                        "zone_low": zone_low,
                        "zone_high": zone_high,
                        "zone_width": float(width),
                        "touch_count": touch_count,
                        "touch_idxs": sorted(touch_idxs),
                    }
                )

    if not rows:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    return pd.DataFrame(rows, columns=RESULT_COLUMNS)


def _make_synthetic_df(rng: np.random.Generator, length: int, grid: float, cluster: bool) -> pd.DataFrame:
    """Synthetic OHLC-ish (high/low only) series with lots of repeated
    values, on a fixed price grid, optionally with tight clusters of
    near-identical prices (to stress the touch-counting boundary)."""
    if cluster:
        base = rng.choice(np.arange(90.0, 110.0, grid * 5), size=length)
        noise = rng.integers(-2, 3, size=length) * grid
        low = np.round(base + noise, 6)
    else:
        levels = np.round(np.arange(80.0, 120.0, grid), 6)
        low = rng.choice(levels, size=length)
    spread = rng.choice([grid, grid * 2, grid * 5, 1.0], size=length)
    high = np.round(low + spread, 6)
    return pd.DataFrame({"high": high, "low": low})


@pytest.mark.parametrize("seed", list(range(30)))
def test_create_zones_matches_brute_force_reference_synthetic(seed):
    rng = np.random.default_rng(seed)
    length = int(rng.integers(20, 401))
    grid = float(rng.choice([0.005, 0.01]))
    cluster = bool(rng.integers(0, 2))
    df = _make_synthetic_df(rng, length, grid, cluster)

    n = int(rng.choice([2, 3, 4]))
    width = float(rng.choice([0.5, 1.0, 2.0]))
    min_touches = int(rng.choice([1, 2, 3]))
    as_of = int(rng.integers(max(2 * n, 1), length))

    fast = create_zones(df, as_of=as_of, n=n, width=width, min_touches=min_touches)
    ref = _create_zones_brute_force(df, as_of=as_of, n=n, width=width, min_touches=min_touches)

    pd.testing.assert_frame_equal(
        fast.reset_index(drop=True), ref.reset_index(drop=True), check_dtype=True
    )


REAL_H1_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "data", "processed", "XAUUSD", "h1.csv"
)


@pytest.mark.skipif(not os.path.isfile(REAL_H1_PATH), reason="real dataset not present (never required in this repo)")
@pytest.mark.parametrize("as_of", [200, 500, 900, 1400])
def test_create_zones_matches_brute_force_reference_real_data_slice(as_of):
    df = pd.read_csv(REAL_H1_PATH).iloc[:1500].reset_index(drop=True)

    fast = create_zones(df, as_of=as_of, n=3, width=1.00, min_touches=2)
    ref = _create_zones_brute_force(df, as_of=as_of, n=3, width=1.00, min_touches=2)

    pd.testing.assert_frame_equal(fast.reset_index(drop=True), ref.reset_index(drop=True), check_dtype=True)
