"""Tests for M15 reversal-reaction detection (src/signals/m15_reaction.py).

Per docs/DAO_GAM_RULES.md Section 4 and docs/DATA_SCHEMA.md Section 7.
Does not call src/signals/sweep.py or src/market_structure/zones.py.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.signals.m15_reaction import check_m15_reaction  # noqa: E402

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")
SWEEP_H1_OPEN = "2024-01-02T22:00:00Z"


def load_m15(name):
    return pd.read_csv(os.path.join(FIXTURES_DIR, name, "m15.csv"))


# ---------------------------------------------------------------------------
# Fixture 01 (BUY) -- fires on the 2nd candle (23:15), scanning stops there
# ---------------------------------------------------------------------------


def test_fixture_01_buy_fires_on_second_candle():
    df = load_m15("01_buy_valid")
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=2000.0)

    assert result.outcome == "fired"
    assert result.reaction_fired is True
    assert result.fired_index == 2
    assert result.fired_timestamp == pd.Timestamp("2024-01-02T23:15:00Z")
    assert result.activation_h1_open == pd.Timestamp("2024-01-02T23:00:00Z")

    # scanning stops at the firing candle -- only 2 candles evaluated, not 4
    assert len(result.candles) == 2

    c1, c2 = result.candles
    assert c1.m15_index_in_window == 1
    assert c1.body_size == pytest.approx(1)
    assert c1.candle_range == pytest.approx(5)
    assert c1.body_ratio == pytest.approx(0.20)
    assert c1.close_position_in_range == pytest.approx(0.20)
    assert c1.cond_a is True
    assert c1.cond_b is False
    assert c1.reaction_fired is False

    assert c2.m15_index_in_window == 2
    assert c2.body_size == pytest.approx(6)
    assert c2.candle_range == pytest.approx(9)
    assert c2.body_ratio == pytest.approx(6 / 9)
    assert c2.close_position_in_range == pytest.approx(7 / 9)
    assert c2.cond_a is True
    assert c2.cond_b is True
    assert c2.cond_c is True
    assert c2.reaction_fired is True


# ---------------------------------------------------------------------------
# Fixture 02 (SELL) -- mirrors fixture 01, fires on the 2nd candle
# ---------------------------------------------------------------------------


def test_fixture_02_sell_fires_on_second_candle():
    df = load_m15("02_sell_valid")
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="sell", zone_center=2000.0)

    assert result.outcome == "fired"
    assert result.fired_index == 2
    assert len(result.candles) == 2

    c1, c2 = result.candles
    assert c1.reaction_fired is False  # body_ratio 0.20 < 0.30
    assert c1.body_ratio == pytest.approx(0.20)

    assert c2.reaction_fired is True
    assert c2.body_ratio == pytest.approx(6 / 9)
    assert c2.close_position_in_range == pytest.approx(2 / 9)  # (1990-1988)/9


# ---------------------------------------------------------------------------
# Fixture 03 -- no reaction, all 4 candles evaluated
#
# NOTE: tests/fixtures/03_no_m15_reaction/README.md line 14 states
# close_position = 0.60 for the 23:15 candle. That is WRONG relative to
# the actual data in tests/fixtures/03_no_m15_reaction/m15.csv (open=2000.5,
# high=2003, low=2000, close=2000.8): the correct value from the CSV is
# (2000.8 - 2000) / (2003 - 2000) = 0.8 / 3 = 0.2667, not 0.60. Per the
# user's explicit decision, the CSV is the source of truth and the README
# cell is left uncorrected (out of scope for this module); these tests
# assert the CSV-derived value (0.2667), not the README's.
# ---------------------------------------------------------------------------


def test_fixture_03_no_reaction_all_four_candles_evaluated():
    df = load_m15("03_no_m15_reaction")
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=2000.0)

    assert result.outcome == "no_reaction"
    assert result.reaction_fired is False
    assert result.fired_index is None
    assert result.fired_timestamp is None
    assert result.activation_h1_open is None
    assert len(result.candles) == 4


def test_fixture_03_candle_23_00_fails_condition_b():
    df = load_m15("03_no_m15_reaction")
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=2000.0)
    c = result.candles[0]
    assert c.timestamp == pd.Timestamp("2024-01-02T23:00:00Z")
    assert c.body_ratio == pytest.approx(0.25)
    assert c.close_position_in_range == pytest.approx(0.75)
    assert c.cond_a is True
    assert c.cond_b is False
    assert c.cond_c is True
    assert c.reaction_fired is False


def test_fixture_03_candle_23_15_fails_conditions_b_and_c():
    """CSV-derived close_position = 0.8/3 = 0.2667 -- see module note above
    re: the README's incorrect 0.60 for this candle."""
    df = load_m15("03_no_m15_reaction")
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=2000.0)
    c = result.candles[1]
    assert c.timestamp == pd.Timestamp("2024-01-02T23:15:00Z")
    assert c.body_ratio == pytest.approx(0.10)
    assert c.close_position_in_range == pytest.approx(0.8 / 3)
    assert c.close_position_in_range == pytest.approx(0.2667, abs=1e-4)
    assert c.cond_a is True
    assert c.cond_b is False
    assert c.cond_c is False
    assert c.reaction_fired is False


def test_fixture_03_candle_23_30_fails_condition_a():
    df = load_m15("03_no_m15_reaction")
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=2000.0)
    c = result.candles[2]
    assert c.timestamp == pd.Timestamp("2024-01-02T23:30:00Z")
    assert c.close == pytest.approx(1999.5)
    assert c.cond_a is False
    assert c.reaction_fired is False


def test_fixture_03_candle_23_45_fails_condition_a():
    df = load_m15("03_no_m15_reaction")
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=2000.0)
    c = result.candles[3]
    assert c.timestamp == pd.Timestamp("2024-01-02T23:45:00Z")
    assert c.close == pytest.approx(1998.0)
    assert c.cond_a is False
    assert c.reaction_fired is False


# ---------------------------------------------------------------------------
# Fixture 04 -- BUY, fires on 2nd candle (identical shape to fixture 01)
# ---------------------------------------------------------------------------


def test_fixture_04_buy_fires_on_second_candle():
    df = load_m15("04_expired_no_entry_touch")
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=2000.0)
    assert result.outcome == "fired"
    assert result.fired_index == 2
    assert len(result.candles) == 2
    assert result.candles[0].reaction_fired is False
    assert result.candles[1].reaction_fired is True


# ---------------------------------------------------------------------------
# Fixture 05 -- reuses fixture 01's candles, fires on 2nd candle
# ---------------------------------------------------------------------------


def test_fixture_05_buy_fires_on_second_candle():
    df = load_m15("05_rr_below_threshold")
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=2000.0)
    assert result.outcome == "fired"
    assert result.fired_index == 2
    assert len(result.candles) == 2


# ---------------------------------------------------------------------------
# Fixture 06 -- reuses fixture 04's candles, fires on 2nd candle
# ---------------------------------------------------------------------------


def test_fixture_06_buy_fires_on_second_candle():
    df = load_m15("06_same_bar_entry_sl_conflict")
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=2000.0)
    assert result.outcome == "fired"
    assert result.fired_index == 2
    assert len(result.candles) == 2


# ---------------------------------------------------------------------------
# Window boundaries: [sweep_h1_open+1h, sweep_h1_open+2h), inclusive start,
# exclusive end, sweep hour itself excluded
# ---------------------------------------------------------------------------


def test_window_excludes_sweep_hour_and_end_boundary_includes_only_next_hour():
    rows = [
        ("2024-01-02T22:45:00Z", 100, 110, 90, 100),  # sweep hour itself -- excluded
        ("2024-01-02T23:00:00Z", 100, 110, 90, 100),  # window start, inclusive
        ("2024-01-02T23:15:00Z", 100, 110, 90, 100),
        ("2024-01-02T23:30:00Z", 100, 110, 90, 100),
        ("2024-01-02T23:45:00Z", 100, 110, 90, 100),  # last candle in window
        ("2024-01-03T00:00:00Z", 100, 110, 90, 100),  # window end, exclusive -- excluded
    ]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=99999.0)  # never fires

    assert len(result.candles) == 4
    assert result.candles[0].timestamp == pd.Timestamp("2024-01-02T23:00:00Z")
    assert result.candles[-1].timestamp == pd.Timestamp("2024-01-02T23:45:00Z")
    assert result.window_start == pd.Timestamp("2024-01-02T23:00:00Z")
    assert result.window_end == pd.Timestamp("2024-01-03T00:00:00Z")
    assert result.outcome == "no_reaction"


def test_sweep_h1_open_accepts_timestamp_object_same_result_as_string():
    df = load_m15("01_buy_valid")
    result_str = check_m15_reaction(df, "2024-01-02T22:00:00Z", direction="buy", zone_center=2000.0)
    result_ts = check_m15_reaction(df, pd.Timestamp("2024-01-02T22:00:00Z"), direction="buy", zone_center=2000.0)
    assert result_str.outcome == result_ts.outcome
    assert result_str.fired_index == result_ts.fired_index
    assert result_str.fired_timestamp == result_ts.fired_timestamp


# ---------------------------------------------------------------------------
# More than 4 candles available in the window -- only the first 4 (in row
# order) are evaluated
# ---------------------------------------------------------------------------


def test_more_than_4_candles_in_window_only_first_4_evaluated():
    rows = [
        ("2024-01-02T23:00:00Z", 100, 110, 90, 100),
        ("2024-01-02T23:15:00Z", 100, 110, 90, 100),
        ("2024-01-02T23:30:00Z", 100, 110, 90, 100),
        ("2024-01-02T23:45:00Z", 100, 110, 90, 100),
        ("2024-01-02T23:50:00Z", 100, 110, 90, 100),  # 5th candle, within window, must be ignored
    ]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=99999.0)
    assert len(result.candles) == 4
    assert result.candles[-1].timestamp == pd.Timestamp("2024-01-02T23:45:00Z")
    assert result.outcome == "no_reaction"


# ---------------------------------------------------------------------------
# body_ratio exact tick boundary (0.30) vs one tick under -- using awkward
# decimal prices (2000.50 / 2000.80 style) to prove tick-integer comparison
# is immune to binary float noise.
# ---------------------------------------------------------------------------


def test_body_ratio_exact_030_fires():
    # range=1.00 (low=2000.00, high=2001.00); body=0.30 (open=2000.50, close=2000.80)
    # close_position = 0.80/1.00 = 0.80 >= 0.60 -> cond_c also satisfied
    rows = [("2024-01-02T23:00:00Z", 2000.50, 2001.00, 2000.00, 2000.80)]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=1990.0)
    c = result.candles[0]
    assert c.body_ratio == pytest.approx(0.30)
    assert c.cond_b is True
    assert c.reaction_fired is True
    assert result.outcome == "fired"


def test_body_ratio_one_tick_under_030_does_not_fire():
    # same as above but open shifted by 1 tick (2000.51) -> body=0.29
    rows = [("2024-01-02T23:00:00Z", 2000.51, 2001.00, 2000.00, 2000.80)]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=1990.0)
    c = result.candles[0]
    assert c.body_ratio == pytest.approx(0.29)
    assert c.cond_b is False
    assert c.reaction_fired is False
    assert result.outcome == "window_incomplete"  # only 1 candle supplied


# ---------------------------------------------------------------------------
# BUY close_position exact tick boundary (0.60) vs one tick under
# ---------------------------------------------------------------------------


def test_buy_close_position_exact_060_fires():
    # range=1.00 (low=2000.00, high=2001.00); close=2000.60 -> pos=0.60
    # body = open(2000.00) to close(2000.60) = 0.60 >= 0.30 -> cond_b ok
    rows = [("2024-01-02T23:00:00Z", 2000.00, 2001.00, 2000.00, 2000.60)]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=1990.0)
    c = result.candles[0]
    assert c.close_position_in_range == pytest.approx(0.60)
    assert c.cond_c is True
    assert c.reaction_fired is True


def test_buy_close_position_one_tick_under_060_does_not_fire():
    rows = [("2024-01-02T23:00:00Z", 2000.00, 2001.00, 2000.00, 2000.59)]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=1990.0)
    c = result.candles[0]
    assert c.close_position_in_range == pytest.approx(0.59)
    assert c.cond_c is False
    assert c.reaction_fired is False


# ---------------------------------------------------------------------------
# SELL boundary conditions (synthetic, hand-computable)
# ---------------------------------------------------------------------------


def test_sell_fires_when_all_three_conditions_met_exactly_at_boundary():
    # body_ratio exactly 0.30, close_position exactly 0.40, close < zone_center
    # range=10, body=3 -> ratio=0.30; close_position=0.40 -> close = low + 0.4*range
    # low=90, high=100 -> close = 90 + 4 = 94; open = close +/- body (body=3) -> open=97 or 91
    # pick open=97 (open>close, a down candle), close=94, high=100, low=90
    rows = [("2024-01-02T23:00:00Z", 97, 100, 90, 94)]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="sell", zone_center=95.0)
    c = result.candles[0]
    assert c.body_ratio == pytest.approx(0.30)
    assert c.close_position_in_range == pytest.approx(0.40)
    assert c.close < 95.0
    assert c.reaction_fired is True
    assert result.outcome == "fired"


def test_sell_fails_when_close_position_one_tick_above_threshold():
    # close_position = 0.41 (> 0.40) -> should NOT fire
    rows = [("2024-01-02T23:00:00Z", 97.1, 100, 90, 94.1)]  # close_position=(94.1-90)/10=0.41
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="sell", zone_center=95.0)
    c = result.candles[0]
    assert c.close_position_in_range == pytest.approx(0.41)
    assert c.reaction_fired is False
    assert result.outcome == "window_incomplete"


def test_sell_fails_when_close_not_strictly_below_zone_center():
    rows = [("2024-01-02T23:00:00Z", 97, 100, 90, 95.0)]  # close == zone_center, not strictly below
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="sell", zone_center=95.0)
    c = result.candles[0]
    assert c.cond_a is False
    assert c.reaction_fired is False


def test_buy_fails_when_close_not_strictly_above_zone_center():
    rows = [("2024-01-02T23:00:00Z", 90, 100, 85, 95.0)]  # close == zone_center
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=95.0)
    c = result.candles[0]
    assert c.cond_a is False
    assert c.reaction_fired is False


# ---------------------------------------------------------------------------
# Zero-range candle edge case: no exception, treated as not firing
# ---------------------------------------------------------------------------


def test_zero_range_candle_does_not_raise_and_does_not_fire():
    rows = [("2024-01-02T23:00:00Z", 100, 100, 100, 100)]  # high == low
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=50.0)
    c = result.candles[0]
    assert c.candle_range == 0
    assert pd.isna(c.body_ratio)
    assert pd.isna(c.close_position_in_range)
    assert c.cond_b is False
    assert c.cond_c is False
    assert c.reaction_fired is False
    assert result.outcome == "window_incomplete"


# ---------------------------------------------------------------------------
# Fires on candle 1 and candle 4 -- activation_h1_open correctness, and
# candles after a fire are never evaluated
# ---------------------------------------------------------------------------


def test_fires_on_first_candle_only_one_candle_evaluated():
    rows = [
        ("2024-01-02T23:00:00Z", 2000.00, 2001.00, 2000.00, 2000.80),  # fires immediately
        ("2024-01-02T23:15:00Z", 999.0, 999.0, 999.0, 999.0),  # would raise if ever validated (invalid OHLC ok here, but let's keep valid)
        ("2024-01-02T23:30:00Z", 100, 110, 90, 100),
        ("2024-01-02T23:45:00Z", 100, 110, 90, 100),
    ]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=1990.0)
    assert result.outcome == "fired"
    assert result.fired_index == 1
    assert result.fired_timestamp == pd.Timestamp("2024-01-02T23:00:00Z")
    assert result.activation_h1_open == pd.Timestamp("2024-01-02T23:00:00Z")
    assert len(result.candles) == 1  # candles 2-4 never evaluated


def test_fires_on_fourth_candle_all_four_evaluated():
    rows = [
        ("2024-01-02T23:00:00Z", 100, 110, 90, 95),  # neutral, does not fire (close<zone_center for buy)
        ("2024-01-02T23:15:00Z", 100, 110, 90, 95),
        ("2024-01-02T23:30:00Z", 100, 110, 90, 95),
        ("2024-01-02T23:45:00Z", 2000.00, 2001.00, 2000.00, 2000.80),  # fires here
    ]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=1990.0)
    assert result.outcome == "fired"
    assert result.fired_index == 4
    assert result.fired_timestamp == pd.Timestamp("2024-01-02T23:45:00Z")
    assert result.activation_h1_open == pd.Timestamp("2024-01-02T23:00:00Z")
    assert len(result.candles) == 4


# ---------------------------------------------------------------------------
# window_incomplete vs no_reaction
# ---------------------------------------------------------------------------


def test_two_candles_no_fire_is_window_incomplete():
    rows = [
        ("2024-01-02T23:00:00Z", 100, 110, 90, 95),
        ("2024-01-02T23:15:00Z", 100, 110, 90, 95),
    ]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=1990.0)
    assert result.outcome == "window_incomplete"
    assert len(result.candles) == 2


def test_zero_candles_is_window_incomplete():
    df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=1990.0)
    assert result.outcome == "window_incomplete"
    assert len(result.candles) == 0
    assert result.fired_index is None


def test_four_candles_no_fire_is_no_reaction():
    rows = [
        ("2024-01-02T23:00:00Z", 100, 110, 90, 95),
        ("2024-01-02T23:15:00Z", 100, 110, 90, 95),
        ("2024-01-02T23:30:00Z", 100, 110, 90, 95),
        ("2024-01-02T23:45:00Z", 100, 110, 90, 95),
    ]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=1990.0)
    assert result.outcome == "no_reaction"
    assert len(result.candles) == 4


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_invalid_direction_raises():
    df = load_m15("01_buy_valid")
    with pytest.raises(ValueError, match="direction must be one of"):
        check_m15_reaction(df, SWEEP_H1_OPEN, direction="up", zone_center=2000.0)


def test_missing_close_column_raises():
    df = load_m15("01_buy_valid").drop(columns=["close"])
    with pytest.raises(ValueError, match="missing required column"):
        check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=2000.0)


def test_nan_in_window_candle_raises():
    df = load_m15("01_buy_valid").copy()
    df.loc[df["timestamp"] == "2024-01-02T23:00:00Z", "close"] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=2000.0)


def test_high_below_low_in_window_candle_raises():
    df = load_m15("01_buy_valid").copy()
    mask = df["timestamp"] == "2024-01-02T23:00:00Z"
    df.loc[mask, "high"] = 1000.0
    df.loc[mask, "low"] = 2000.0
    with pytest.raises(ValueError, match="high < low"):
        check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=2000.0)


def test_nan_outside_window_does_not_raise():
    # a NaN in the sweep-hour candle (excluded from the window) must not
    # block evaluation of the window candles.
    df = load_m15("01_buy_valid").copy()
    df.loc[df["timestamp"] == "2024-01-02T22:00:00Z", "close"] = np.nan
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=2000.0)
    assert result.outcome == "fired"


def test_zone_center_nan_raises():
    df = load_m15("01_buy_valid")
    with pytest.raises(ValueError, match="zone_center must be a finite number"):
        check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=float("nan"))


def test_zone_center_inf_raises():
    df = load_m15("01_buy_valid")
    with pytest.raises(ValueError, match="zone_center must be a finite number"):
        check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=float("inf"))


def test_duplicate_timestamp_in_window_raises():
    rows = [
        ("2024-01-02T23:00:00Z", 100, 110, 90, 95),
        ("2024-01-02T23:00:00Z", 100, 110, 90, 95),  # duplicate
    ]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    with pytest.raises(ValueError, match="strictly increasing"):
        check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=1990.0)


def test_out_of_order_timestamp_in_window_raises():
    rows = [
        ("2024-01-02T23:15:00Z", 100, 110, 90, 95),
        ("2024-01-02T23:00:00Z", 100, 110, 90, 95),  # earlier timestamp appears after
    ]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    with pytest.raises(ValueError, match="strictly increasing"):
        check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=1990.0)


def test_no_sort_applied_rows_read_in_given_order():
    """Rows are read in the order given, not re-sorted -- an
    already-correctly-ordered window must behave identically regardless
    of how it's constructed."""
    rows = [
        ("2024-01-02T23:00:00Z", 100, 110, 90, 95),
        ("2024-01-02T23:15:00Z", 2000.00, 2001.00, 2000.00, 2000.80),
    ]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    result = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=1990.0)
    assert result.outcome == "fired"
    assert result.fired_index == 2


# ---------------------------------------------------------------------------
# Look-ahead: data after the firing candle must not affect the result
# ---------------------------------------------------------------------------


def test_no_lookahead_data_after_firing_candle_does_not_affect_result():
    rows = [
        ("2024-01-02T23:00:00Z", 2000.00, 2001.00, 2000.00, 2000.80),  # fires here
        ("2024-01-02T23:15:00Z", 100, 110, 90, 95),
        ("2024-01-02T23:30:00Z", 100, 110, 90, 95),
        ("2024-01-02T23:45:00Z", 100, 110, 90, 95),
    ]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    result_before = check_m15_reaction(df, SWEEP_H1_OPEN, direction="buy", zone_center=1990.0)

    df_mutated = df.copy()
    df_mutated.loc[1:, ["open", "high", "low", "close"]] = [
        [np.nan, np.nan, np.nan, np.nan],  # would raise if it were ever read
        [-999.0, -998.0, -1000.0, -999.5],
        [5000.0, 6000.0, 4000.0, 5500.0],
    ]

    result_after = check_m15_reaction(df_mutated, SWEEP_H1_OPEN, direction="buy", zone_center=1990.0)

    assert result_before.outcome == result_after.outcome
    assert result_before.fired_index == result_after.fired_index
    assert result_before.fired_timestamp == result_after.fired_timestamp
    assert len(result_before.candles) == len(result_after.candles) == 1
