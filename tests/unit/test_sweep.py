"""Tests for H1 sweep/trap candle detection (src/signals/sweep.py).

Per docs/DAO_GAM_RULES.md Section 3 rules 4, 5, 7 and docs/DATA_SCHEMA.md
Sections 4-6. Builds on src/indicators/atr.py's atr(), already tested in
tests/unit/test_atr.py -- these tests exercise sweep/trap detection only.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.indicators.atr import atr as compute_atr  # noqa: E402
from src.signals.sweep import detect_sweep  # noqa: E402

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")


def load_fixture_h1(name):
    return pd.read_csv(os.path.join(FIXTURES_DIR, name, "h1.csv"))


def make_base_df(sweep_open, sweep_high, sweep_low, sweep_close):
    """22 bars (idx 0-21) with True Range = 10 exactly (validated in
    tests/unit/test_atr.py's construction), so atr.iloc[21] == 10.0
    exactly, followed by one custom sweep candle at idx 22."""
    rows = []
    price = 2000
    for _ in range(22):
        rows.append((price, price + 10, price, price + 10))
        price += 10
    rows.append((sweep_open, sweep_high, sweep_low, sweep_close))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


SUPPORT_ZONE = {"side": "support", "zone_low": 2219.50, "zone_center": 2220.00, "zone_high": 2220.50}
RESISTANCE_ZONE = {"side": "resistance", "zone_low": 2219.50, "zone_center": 2220.00, "zone_high": 2220.50}


# ---------------------------------------------------------------------------
# Fixture 01 (BUY / support) -- real h1.csv + real atr.py output
# ---------------------------------------------------------------------------


def test_fixture_01_idx22_is_trap_support():
    df = load_fixture_h1("01_buy_valid")
    atr = compute_atr(df, period=14)
    zone = {"side": "support", "zone_low": 1999.50, "zone_center": 2000.00, "zone_high": 2000.50}

    result = detect_sweep(df, atr, idx=22, zone=zone)

    assert result.is_trap is True
    assert result.direction == "buy"
    assert result.sweep_extreme == pytest.approx(1965.0)
    assert result.h1_range == pytest.approx(81.0)
    assert result.pierce_depth == pytest.approx(34.5)
    assert result.atr_h1_14 == pytest.approx(10.0)
    assert result.range_multiple == pytest.approx(8.1)
    assert result.range_ok is True
    assert result.pierce_ok is True
    assert result.closed_back_inside is True
    assert result.reason == "ok"


# ---------------------------------------------------------------------------
# Fixture 02 (SELL / resistance) -- real h1.csv + real atr.py output
# ---------------------------------------------------------------------------


def test_fixture_02_idx22_is_trap_resistance():
    df = load_fixture_h1("02_sell_valid")
    atr = compute_atr(df, period=14)
    zone = {"side": "resistance", "zone_low": 1999.50, "zone_center": 2000.00, "zone_high": 2000.50}

    result = detect_sweep(df, atr, idx=22, zone=zone)

    assert result.is_trap is True
    assert result.direction == "sell"
    assert result.sweep_extreme == pytest.approx(2035.0)
    assert result.h1_range == pytest.approx(81.0)
    assert result.pierce_depth == pytest.approx(34.5)
    assert result.atr_h1_14 == pytest.approx(10.0)
    assert result.range_ok is True
    assert result.pierce_ok is True
    assert result.closed_back_inside is True
    assert result.reason == "ok"


# ---------------------------------------------------------------------------
# Fixture 07 -- real breakout, no close back inside the zone -> not a trap
# ---------------------------------------------------------------------------


def test_fixture_07_idx22_not_a_trap_no_close_back():
    df = load_fixture_h1("07_real_breakout_no_close_back")
    atr = compute_atr(df, period=14)
    zone = {"side": "support", "zone_low": 1999.50, "zone_center": 2000.00, "zone_high": 2000.50}

    result = detect_sweep(df, atr, idx=22, zone=zone)

    assert result.is_trap is False
    assert result.range_ok is True
    assert result.pierce_ok is True
    assert result.closed_back_inside is False
    assert result.reason == "not_closed_back_inside"


# ---------------------------------------------------------------------------
# Range boundary: >=1.5*ATR exactly passes, one tick under fails
# ---------------------------------------------------------------------------


def test_range_exactly_at_threshold_passes():
    # ATR(idx-1)=10 -> threshold 15.0. range = high-low = 2225-2210 = 15.0
    df = make_base_df(2220, 2225, 2210, 2220.0)
    atr = compute_atr(df, period=14)
    result = detect_sweep(df, atr, idx=22, zone=SUPPORT_ZONE)
    assert result.h1_range == pytest.approx(15.0)
    assert result.range_ok is True


def test_range_one_tick_under_threshold_fails():
    # low raised by 0.01 -> range = 2225 - 2210.01 = 14.99
    df = make_base_df(2220, 2225, 2210.01, 2220.0)
    atr = compute_atr(df, period=14)
    result = detect_sweep(df, atr, idx=22, zone=SUPPORT_ZONE)
    assert result.h1_range == pytest.approx(14.99)
    assert result.range_ok is False
    assert result.is_trap is False
    assert result.reason == "range_fail"


# ---------------------------------------------------------------------------
# Pierce boundary: >=0.25*ATR exactly passes, one tick under fails
# ---------------------------------------------------------------------------


def test_pierce_exactly_at_threshold_passes():
    # ATR(idx-1)=10 -> pierce threshold 2.5. low = zone_low - 2.5 = 2217.0
    # range kept comfortably >=15 so this isolates the pierce condition.
    df = make_base_df(2220, 2237.0, 2217.0, 2220.0)
    atr = compute_atr(df, period=14)
    result = detect_sweep(df, atr, idx=22, zone=SUPPORT_ZONE)
    assert result.pierce_depth == pytest.approx(2.5)
    assert result.range_ok is True
    assert result.pierce_ok is True


def test_pierce_one_tick_under_threshold_fails():
    # low = zone_low - 2.49 = 2217.01
    df = make_base_df(2220, 2237.01, 2217.01, 2220.0)
    atr = compute_atr(df, period=14)
    result = detect_sweep(df, atr, idx=22, zone=SUPPORT_ZONE)
    assert result.pierce_depth == pytest.approx(2.49)
    assert result.range_ok is True
    assert result.pierce_ok is False
    assert result.is_trap is False
    assert result.reason == "pierce_fail"


# ---------------------------------------------------------------------------
# Closed-back-inside boundary: inclusive of zone_low/zone_high, 1 tick outside fails
# ---------------------------------------------------------------------------


def test_close_exactly_at_zone_low_passes():
    df = make_base_df(2220, 2225, 2210, 2219.50)  # zone_low
    atr = compute_atr(df, period=14)
    result = detect_sweep(df, atr, idx=22, zone=SUPPORT_ZONE)
    assert result.closed_back_inside is True
    assert result.is_trap is True


def test_close_exactly_at_zone_high_passes():
    df = make_base_df(2220, 2225, 2210, 2220.50)  # zone_high
    atr = compute_atr(df, period=14)
    result = detect_sweep(df, atr, idx=22, zone=SUPPORT_ZONE)
    assert result.closed_back_inside is True
    assert result.is_trap is True


def test_close_one_tick_below_zone_low_fails():
    df = make_base_df(2220, 2225, 2210, 2219.49)
    atr = compute_atr(df, period=14)
    result = detect_sweep(df, atr, idx=22, zone=SUPPORT_ZONE)
    assert result.closed_back_inside is False
    assert result.is_trap is False
    assert result.reason == "not_closed_back_inside"


def test_close_one_tick_above_zone_high_fails():
    df = make_base_df(2220, 2225, 2210, 2220.51)
    atr = compute_atr(df, period=14)
    result = detect_sweep(df, atr, idx=22, zone=SUPPORT_ZONE)
    assert result.closed_back_inside is False
    assert result.is_trap is False
    assert result.reason == "not_closed_back_inside"


# ---------------------------------------------------------------------------
# atr[idx-1] vs atr[idx]: must use idx-1, not idx
# ---------------------------------------------------------------------------


def test_uses_atr_idx_minus_1_not_atr_idx():
    """22 base bars all TR=10 -> atr.iloc[21] == 10.0. Sweep candle (idx
    22) has range 15.2, no gap (open == prev close).

    Manual check (see chat report before this test was written):
      atr.iloc[21] = 10.0            -> threshold 1.5*10     = 15.0
      atr.iloc[22] = (10*13+15.2)/14 = 10.371428571428571
                                      -> threshold 1.5*10.371... = 15.557142857142855
      range 15.2 >= 15.0   -> True  (correct, using atr[idx-1])
      range 15.2 >= 15.557 -> False (would be wrong, using atr[idx])
    """
    low = 2219.50 - 5.0  # pierce=5.0, comfortably >= 2.5
    high = low + 15.2  # range = 15.2 exactly
    df = make_base_df(2220, high, low, 2220.0)

    atr = compute_atr(df, period=14)
    assert atr.iloc[21] == pytest.approx(10.0)
    assert atr.iloc[22] == pytest.approx(10.371428571428571)

    result = detect_sweep(df, atr, idx=22, zone=SUPPORT_ZONE)
    assert result.atr_h1_14 == pytest.approx(10.0)  # confirms atr[idx-1] was used
    assert result.h1_range == pytest.approx(15.2)
    assert result.range_ok is True  # would be False if atr[idx] had been used


# ---------------------------------------------------------------------------
# Range ok but pierce not; pierce ok but range not; wrong-side pierce
# ---------------------------------------------------------------------------


def test_range_ok_pierce_fails():
    # range huge (20.5), but low barely dips past zone_low (pierce=1.0 < 2.5)
    df = make_base_df(2220, 2239.0, 2218.5, 2220.0)  # low = zone_low - 1.0
    atr = compute_atr(df, period=14)
    result = detect_sweep(df, atr, idx=22, zone=SUPPORT_ZONE)
    assert result.h1_range == pytest.approx(20.5)
    assert result.range_ok is True
    assert result.pierce_depth == pytest.approx(1.0)
    assert result.pierce_ok is False
    assert result.is_trap is False
    assert result.reason == "pierce_fail"


def test_pierce_ok_range_fails():
    # big pierce (19.5) but tiny range (5) -- low far below zone, high close to low.
    df = make_base_df(2205, 2205.0, 2200.0, 2202.0)
    atr = compute_atr(df, period=14)
    result = detect_sweep(df, atr, idx=22, zone=SUPPORT_ZONE)
    assert result.pierce_depth == pytest.approx(19.5)
    assert result.pierce_ok is True
    assert result.h1_range == pytest.approx(5.0)
    assert result.range_ok is False
    assert result.is_trap is False
    assert result.reason == "range_fail"


def test_wrong_side_pierce_does_not_count_for_support():
    # Bar moves UP through/above the zone instead of down through it:
    # low stays at/above zone_low, so the support-side pierce_depth is
    # negative (well under the 2.5 threshold) even though the range
    # condition is satisfied by the big upward move.
    df = make_base_df(2220, 2240.0, 2220.0, 2220.2)
    atr = compute_atr(df, period=14)
    result = detect_sweep(df, atr, idx=22, zone=SUPPORT_ZONE)
    assert result.h1_range == pytest.approx(20.0)
    assert result.range_ok is True
    assert result.pierce_depth == pytest.approx(2219.50 - 2220.0)  # -0.5
    assert result.pierce_ok is False
    assert result.is_trap is False
    assert result.reason == "pierce_fail"


# ---------------------------------------------------------------------------
# ATR unavailable: idx < 1, or atr[idx-1] is NaN
# ---------------------------------------------------------------------------


def test_idx_zero_gives_atr_unavailable():
    df = make_base_df(2220, 2225, 2210, 2220.0)
    atr = compute_atr(df, period=14)
    result = detect_sweep(df, atr, idx=0, zone=SUPPORT_ZONE)
    assert result.is_trap is False
    assert result.reason == "atr_unavailable"


def test_atr_nan_at_idx_minus_1_gives_atr_unavailable():
    df = make_base_df(2220, 2225, 2210, 2220.0)
    atr = compute_atr(df, period=14)
    assert pd.isna(atr.iloc[0])  # ATR(14) is NaN before the 14th bar
    result = detect_sweep(df, atr, idx=1, zone=SUPPORT_ZONE)
    assert result.is_trap is False
    assert result.reason == "atr_unavailable"


# ---------------------------------------------------------------------------
# Validation: NaN data, missing columns, idx errors, zone errors, side errors
# ---------------------------------------------------------------------------


def test_nan_in_high_at_idx_raises():
    valid_df = make_base_df(2220, 2225, 2210, 2220.0)
    atr = compute_atr(valid_df, period=14)  # atr computed before corrupting the row
    df = valid_df.copy()
    df.loc[22, "high"] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        detect_sweep(df, atr, idx=22, zone=SUPPORT_ZONE)


def test_nan_in_close_at_idx_raises():
    valid_df = make_base_df(2220, 2225, 2210, 2220.0)
    atr = compute_atr(valid_df, period=14)
    df = valid_df.copy()
    df.loc[22, "close"] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        detect_sweep(df, atr, idx=22, zone=SUPPORT_ZONE)


def test_missing_close_column_raises():
    df = make_base_df(2220, 2225, 2210, 2220.0).drop(columns=["close"])
    atr = pd.Series([10.0] * len(df))
    with pytest.raises(ValueError, match="missing required column"):
        detect_sweep(df, atr, idx=22, zone=SUPPORT_ZONE)


def test_high_below_low_at_idx_raises():
    valid_df = make_base_df(2220, 2225, 2210, 2220.0)
    atr = compute_atr(valid_df, period=14)
    df = valid_df.copy()
    df.loc[22, ["high", "low", "close"]] = [2205, 2210, 2207.0]  # high < low
    with pytest.raises(ValueError, match="high < low"):
        detect_sweep(df, atr, idx=22, zone=SUPPORT_ZONE)


def test_idx_negative_raises():
    df = make_base_df(2220, 2225, 2210, 2220.0)
    atr = compute_atr(df, period=14)
    with pytest.raises(ValueError, match=r"idx must be in"):
        detect_sweep(df, atr, idx=-1, zone=SUPPORT_ZONE)


def test_idx_out_of_range_raises():
    df = make_base_df(2220, 2225, 2210, 2220.0)
    atr = compute_atr(df, period=14)
    with pytest.raises(ValueError, match=r"idx must be in"):
        detect_sweep(df, atr, idx=999, zone=SUPPORT_ZONE)


def test_idx_non_int_raises():
    df = make_base_df(2220, 2225, 2210, 2220.0)
    atr = compute_atr(df, period=14)
    with pytest.raises(TypeError, match="idx must be an int"):
        detect_sweep(df, atr, idx=22.5, zone=SUPPORT_ZONE)


def test_zone_missing_key_raises():
    df = make_base_df(2220, 2225, 2210, 2220.0)
    atr = compute_atr(df, period=14)
    bad_zone = {"side": "support", "zone_low": 2219.5, "zone_center": 2220.0}  # no zone_high
    with pytest.raises(ValueError, match="zone missing required key"):
        detect_sweep(df, atr, idx=22, zone=bad_zone)


def test_zone_bad_side_raises():
    df = make_base_df(2220, 2225, 2210, 2220.0)
    atr = compute_atr(df, period=14)
    bad_zone = {"side": "up", "zone_low": 2219.5, "zone_center": 2220.0, "zone_high": 2220.5}
    with pytest.raises(ValueError, match="side must be one of"):
        detect_sweep(df, atr, idx=22, zone=bad_zone)


def test_zone_bad_bounds_raises():
    df = make_base_df(2220, 2225, 2210, 2220.0)
    atr = compute_atr(df, period=14)
    bad_zone = {"side": "support", "zone_low": 2220.5, "zone_center": 2220.0, "zone_high": 2219.5}
    with pytest.raises(ValueError, match="zone_low < zone_center < zone_high"):
        detect_sweep(df, atr, idx=22, zone=bad_zone)


# ---------------------------------------------------------------------------
# Look-ahead guarantee
# ---------------------------------------------------------------------------


def test_atr_zero_at_idx_minus_1_gives_atr_unavailable_no_zero_division():
    df = make_base_df(2220, 2225, 2210, 2220.0)
    atr = compute_atr(df, period=14).copy()
    atr.iloc[21] = 0.0
    result = detect_sweep(df, atr, idx=22, zone=SUPPORT_ZONE)
    assert result.is_trap is False
    assert result.reason == "atr_unavailable"
    assert pd.isna(result.atr_h1_14)


def test_atr_series_too_short_raises_value_error():
    df = make_base_df(2220, 2225, 2210, 2220.0)
    atr_full = compute_atr(df, period=14)
    atr_short = atr_full.iloc[:21]  # last valid position is 20; idx-1=21 does not exist
    with pytest.raises(ValueError, match="atr series too short"):
        detect_sweep(df, atr_short, idx=22, zone=SUPPORT_ZONE)


def test_no_lookahead_data_after_idx_does_not_affect_result():
    df = make_base_df(2220, 2225, 2210, 2220.0)
    df = pd.concat(
        [df, pd.DataFrame([(2220.0, 2230.0, 2215.0, 2225.0)] * 3, columns=df.columns)],
        ignore_index=True,
    )
    atr = compute_atr(df, period=14)

    result_before = detect_sweep(df, atr, idx=22, zone=SUPPORT_ZONE)

    df_mutated = df.copy()
    df_mutated.loc[23:, ["open", "high", "low", "close"]] = [
        [1.0, 2.0, 0.5, 1.5],
        [500.0, 600.0, 400.0, 550.0],
        [-10.0, -5.0, -20.0, -8.0],
    ]
    atr_mutated = atr.copy()
    atr_mutated.iloc[23:] = 999.0

    result_after = detect_sweep(df_mutated, atr_mutated, idx=22, zone=SUPPORT_ZONE)

    assert result_before == result_after
