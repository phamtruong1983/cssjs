"""Tests for limit-entry simulation (src/execution/entry_simulation.py).

Per docs/DAO_GAM_RULES.md Section 5 and docs/DATA_SCHEMA.md Section 9.
Does not call sweep.py, m15_reaction.py, zones.py (create_zones), or
risk_reward.py.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.execution.entry_simulation import simulate_entry  # noqa: E402

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")


def load_fixture_h1(name):
    return pd.read_csv(os.path.join(FIXTURES_DIR, name, "h1.csv"))


def make_df(rows):
    """rows: list of (high, low) tuples."""
    return pd.DataFrame(rows, columns=["high", "low"])


# ---------------------------------------------------------------------------
# Fixture 01 (BUY) -- real h1.csv, only 1 window candle exists (25 rows)
# ---------------------------------------------------------------------------


def test_fixture_01_filled_at_idx24_only_one_candle_exists():
    df = load_fixture_h1("01_buy_valid")
    result = simulate_entry(df, activation_idx=23, direction="buy", entry=2000.0, stop=1963.0)
    assert result.outcome == "filled"
    assert result.reason == "ok"
    assert result.fill_idx == 24
    assert result.fill_price == pytest.approx(2000.0)
    assert len(result.candles) == 1
    assert result.candles[0].idx == 24


# ---------------------------------------------------------------------------
# Fixture 02 (SELL) -- mirror of fixture 01
# ---------------------------------------------------------------------------


def test_fixture_02_filled_at_idx24():
    df = load_fixture_h1("02_sell_valid")
    result = simulate_entry(df, activation_idx=23, direction="sell", entry=2000.0, stop=2037.0)
    assert result.outcome == "filled"
    assert result.fill_idx == 24
    assert result.fill_price == pytest.approx(2000.0)
    assert len(result.candles) == 1


# ---------------------------------------------------------------------------
# Fixture 04 -- expired, no_touch, both window candles (idx 24, 25) evaluated
# ---------------------------------------------------------------------------


def test_fixture_04_expired_no_touch_two_candles():
    df = load_fixture_h1("04_expired_no_entry_touch")
    result = simulate_entry(df, activation_idx=23, direction="buy", entry=2000.0, stop=1963.0)
    assert result.outcome == "expired"
    assert result.reason == "no_touch"
    assert result.fill_idx is None
    assert result.fill_price is None
    assert len(result.candles) == 2
    assert [c.idx for c in result.candles] == [24, 25]
    assert result.candles[0].entry_touched is False
    assert result.candles[0].stop_touched is False
    assert result.candles[1].entry_touched is False
    assert result.candles[1].stop_touched is False


# ---------------------------------------------------------------------------
# Fixture 06 -- same-bar entry/stop conflict at idx 24
# ---------------------------------------------------------------------------


def test_fixture_06_same_bar_conflict_at_idx24():
    df = load_fixture_h1("06_same_bar_entry_sl_conflict")
    result = simulate_entry(df, activation_idx=23, direction="buy", entry=2000.0, stop=1963.0)
    assert result.outcome == "expired"
    assert result.reason == "same_bar_entry_stop_conflict"
    assert result.fill_idx is None
    assert result.fill_price is None
    assert len(result.candles) == 1
    c = result.candles[0]
    assert c.idx == 24
    assert c.entry_touched is True
    assert c.stop_touched is True


# ---------------------------------------------------------------------------
# Activation bar itself is never read, even if it "touches" entry
# ---------------------------------------------------------------------------


def test_activation_bar_touch_is_ignored():
    # activation bar (idx 0) touches entry, but must be ignored; window
    # candles (idx 1, 2) don't touch -> expired/no_touch.
    df = make_df(
        [
            (2010, 1990),  # idx0 activation bar -- touches entry(2000) but ignored
            (2010, 2005),  # idx1 window candle 1 -- no touch
            (2010, 2005),  # idx2 window candle 2 -- no touch
        ]
    )
    result = simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=1963.0)
    assert result.outcome == "expired"
    assert result.reason == "no_touch"
    assert [c.idx for c in result.candles] == [1, 2]


# ---------------------------------------------------------------------------
# Boundary: low exactly at entry (BUY) touches; low 1 tick above does not
# ---------------------------------------------------------------------------


def test_buy_entry_touch_exact_boundary():
    df = make_df([(9999, 9999), (2010, 2000.00), (2010, 2005)])
    result = simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=1963.0)
    assert result.outcome == "filled"
    assert result.fill_idx == 1


def test_buy_entry_one_tick_above_does_not_touch():
    df = make_df([(9999, 9999), (2010, 2000.01), (2010, 2005)])
    result = simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=1963.0)
    assert result.candles[0].entry_touched is False
    # second candle also doesn't touch -> expired no_touch
    assert result.outcome == "expired"
    assert result.reason == "no_touch"


def test_sell_entry_touch_exact_boundary():
    df = make_df([(1, 1), (2000.00, 1995), (2010, 2005)])
    result = simulate_entry(df, activation_idx=0, direction="sell", entry=2000.0, stop=2037.0)
    assert result.outcome == "filled"
    assert result.fill_idx == 1


def test_sell_entry_one_tick_below_does_not_touch():
    df = make_df([(1, 1), (1999.99, 1995), (2010, 2005)])
    result = simulate_entry(df, activation_idx=0, direction="sell", entry=2000.0, stop=2037.0)
    assert result.candles[0].entry_touched is False
    assert result.outcome == "expired"
    assert result.reason == "no_touch"


# ---------------------------------------------------------------------------
# Stop touched exactly at stop_t counts as a touch
# ---------------------------------------------------------------------------


def test_buy_stop_touch_exact_boundary_no_entry():
    # low == stop exactly, high stays below entry -> stop touched, entry not
    df = make_df([(1, 1), (1970, 1963.00), (2010, 2005)])
    result = simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=1963.0)
    assert result.candles[0].stop_touched is True
    assert result.candles[0].entry_touched is False
    assert result.outcome == "expired"
    assert result.reason == "stop_touched_before_entry"


def test_sell_stop_touch_exact_boundary_no_entry():
    df = make_df([(1, 1), (2037.00, 2010), (2010, 2005)])
    result = simulate_entry(df, activation_idx=0, direction="sell", entry=2000.0, stop=2037.0)
    assert result.candles[0].stop_touched is True
    assert result.candles[0].entry_touched is False
    assert result.outcome == "expired"
    assert result.reason == "stop_touched_before_entry"


# ---------------------------------------------------------------------------
# Fills on candle 1 vs candle 2; stop touched on candle 2 after candle 1 no-touch
# ---------------------------------------------------------------------------


def test_fills_on_first_window_candle():
    df = make_df([(1, 1), (2010, 1995), (5000, 4000)])  # candle1 touches entry
    result = simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=1963.0)
    assert result.outcome == "filled"
    assert result.fill_idx == 1
    assert len(result.candles) == 1  # candle 2 never evaluated


def test_fills_on_second_window_candle_after_first_no_touch():
    df = make_df([(1, 1), (2010, 2005), (2010, 1995)])  # candle1 no touch, candle2 fills
    result = simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=1963.0)
    assert result.outcome == "filled"
    assert result.fill_idx == 2
    assert len(result.candles) == 2
    assert result.candles[0].entry_touched is False
    assert result.candles[1].entry_touched is True


def test_stop_touched_on_second_candle_after_first_no_touch():
    df = make_df([(1, 1), (2010, 2005), (1999, 1960)])  # candle1 no touch, candle2 stop touch only (high<entry)
    result = simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=1963.0)
    assert result.outcome == "expired"
    assert result.reason == "stop_touched_before_entry"
    assert len(result.candles) == 2
    assert result.candles[1].stop_touched is True
    assert result.candles[1].entry_touched is False


# ---------------------------------------------------------------------------
# window_incomplete: 1 candle available (no conclusion), 0 candles available
# ---------------------------------------------------------------------------


def test_one_candle_available_no_conclusion_is_window_incomplete():
    df = make_df([(1, 1), (2010, 2005)])  # only activation(0) + 1 window candle(1); no touch
    result = simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=1963.0)
    assert result.outcome == "window_incomplete"
    assert result.reason == "window_incomplete"
    assert len(result.candles) == 1


def test_zero_candles_available_is_window_incomplete():
    df = make_df([(1, 1)])  # only the activation bar exists, no window candles at all
    result = simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=1963.0)
    assert result.outcome == "window_incomplete"
    assert result.reason == "window_incomplete"
    assert len(result.candles) == 0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_invalid_direction_raises():
    df = make_df([(1, 1), (2010, 2005), (2010, 2005)])
    with pytest.raises(ValueError, match="direction must be one of"):
        simulate_entry(df, activation_idx=0, direction="up", entry=2000.0, stop=1963.0)


def test_activation_idx_non_int_raises():
    df = make_df([(1, 1), (2010, 2005), (2010, 2005)])
    with pytest.raises(TypeError, match="activation_idx must be an int"):
        simulate_entry(df, activation_idx=0.5, direction="buy", entry=2000.0, stop=1963.0)


def test_activation_idx_out_of_range_raises():
    df = make_df([(1, 1), (2010, 2005), (2010, 2005)])
    with pytest.raises(ValueError, match="activation_idx must be in"):
        simulate_entry(df, activation_idx=99, direction="buy", entry=2000.0, stop=1963.0)


def test_activation_idx_negative_raises():
    df = make_df([(1, 1), (2010, 2005), (2010, 2005)])
    with pytest.raises(ValueError, match="activation_idx must be in"):
        simulate_entry(df, activation_idx=-1, direction="buy", entry=2000.0, stop=1963.0)


def test_missing_low_column_raises():
    df = pd.DataFrame({"high": [1, 2010, 2010]})
    with pytest.raises(ValueError, match="missing required column"):
        simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=1963.0)


def test_entry_nan_raises():
    df = make_df([(1, 1), (2010, 2005), (2010, 2005)])
    with pytest.raises(ValueError, match="entry must be a finite number"):
        simulate_entry(df, activation_idx=0, direction="buy", entry=float("nan"), stop=1963.0)


def test_stop_inf_raises():
    df = make_df([(1, 1), (2010, 2005), (2010, 2005)])
    with pytest.raises(ValueError, match="stop must be a finite number"):
        simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=float("inf"))


def test_buy_stop_wrong_side_raises():
    df = make_df([(1, 1), (2010, 2005), (2010, 2005)])
    with pytest.raises(ValueError, match="stop .* must be < entry"):
        simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=2001.0)


def test_sell_stop_wrong_side_raises():
    df = make_df([(1, 1), (2010, 2005), (2010, 2005)])
    with pytest.raises(ValueError, match="stop .* must be > entry"):
        simulate_entry(df, activation_idx=0, direction="sell", entry=2000.0, stop=1999.0)


def test_nan_in_window_candle_raises():
    df = make_df([(1, 1), (np.nan, 2005), (2010, 2005)])
    with pytest.raises(ValueError, match="NaN"):
        simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=1963.0)


def test_high_below_low_in_window_candle_raises():
    df = make_df([(1, 1), (100, 200), (2010, 2005)])  # high < low
    with pytest.raises(ValueError, match="high < low"):
        simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=1963.0)


def test_nan_in_activation_bar_does_not_raise():
    df = make_df([(np.nan, np.nan), (2010, 1995), (5000, 4000)])
    result = simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=1963.0)
    assert result.outcome == "filled"


def test_nan_beyond_window_does_not_raise():
    df = make_df([(1, 1), (2010, 1995), (np.nan, np.nan)])  # candle1 fills; candle2 never read
    result = simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=1963.0)
    assert result.outcome == "filled"
    assert len(result.candles) == 1


# ---------------------------------------------------------------------------
# Look-ahead: data after the concluding candle must not affect the result
# ---------------------------------------------------------------------------


def test_no_lookahead_data_after_conclusion_does_not_affect_result():
    df = make_df([(1, 1), (2010, 1995), (5000, 4000)])  # fills at idx1; idx2 must never be read
    result_before = simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=1963.0)

    df_mutated = df.copy()
    df_mutated.loc[2, ["high", "low"]] = [np.nan, np.nan]  # would raise if ever read
    result_after = simulate_entry(df_mutated, activation_idx=0, direction="buy", entry=2000.0, stop=1963.0)

    assert result_before.outcome == result_after.outcome
    assert result_before.fill_idx == result_after.fill_idx
    assert result_before.fill_price == result_after.fill_price
    assert len(result_before.candles) == len(result_after.candles) == 1


def test_no_lookahead_expired_no_touch_data_after_window_does_not_affect_result():
    df = make_df([(1, 1), (2010, 2005), (2010, 2005), (5000, 4000)])
    result_before = simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=1963.0)

    df_mutated = df.copy()
    df_mutated.loc[3, ["high", "low"]] = [np.nan, np.nan]
    result_after = simulate_entry(df_mutated, activation_idx=0, direction="buy", entry=2000.0, stop=1963.0)

    assert result_before.outcome == "expired"
    assert result_before.reason == "no_touch"
    assert result_before.outcome == result_after.outcome
    assert result_before.reason == result_after.reason


# ---------------------------------------------------------------------------
# fill_ts: populated when df has a `timestamp` column, None when it doesn't
# ---------------------------------------------------------------------------


def test_fill_ts_populated_when_timestamp_column_present():
    df = pd.DataFrame(
        {
            "timestamp": ["2024-01-01T00:00:00Z", "2024-01-01T01:00:00Z", "2024-01-01T02:00:00Z"],
            "high": [1, 2010, 2010],
            "low": [1, 1995, 2005],
        }
    )
    result = simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=1963.0)
    assert result.outcome == "filled"
    assert result.fill_idx == 1
    assert result.fill_ts == "2024-01-01T01:00:00Z"


def test_fill_ts_none_when_no_timestamp_column():
    df = make_df([(1, 1), (2010, 1995), (2010, 2005)])
    result = simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=1963.0)
    assert result.outcome == "filled"
    assert result.fill_ts is None


# ---------------------------------------------------------------------------
# SELL mirror: same-bar conflict, no_touch, stop touched on 2nd candle
# ---------------------------------------------------------------------------


def test_sell_same_bar_entry_stop_conflict():
    # entry=2000, stop=2037 (sell). candle high>=stop and low<=entry -> conflict
    df = make_df([(1, 1), (2040, 1995), (2010, 2005)])
    result = simulate_entry(df, activation_idx=0, direction="sell", entry=2000.0, stop=2037.0)
    assert result.outcome == "expired"
    assert result.reason == "same_bar_entry_stop_conflict"
    assert result.fill_idx is None
    assert len(result.candles) == 1
    c = result.candles[0]
    assert c.entry_touched is True
    assert c.stop_touched is True


def test_sell_no_touch_both_candles():
    df = make_df([(1, 1), (2010, 2005), (2015, 2008)])  # neither candle touches entry(2000) or stop(2037)
    result = simulate_entry(df, activation_idx=0, direction="sell", entry=2000.0, stop=2037.0)
    assert result.outcome == "expired"
    assert result.reason == "no_touch"
    assert len(result.candles) == 2
    assert result.candles[0].entry_touched is False
    assert result.candles[0].stop_touched is False
    assert result.candles[1].entry_touched is False
    assert result.candles[1].stop_touched is False


def test_sell_stop_touched_on_second_candle_after_first_no_touch():
    df = make_df([(1, 1), (2010, 2005), (2040, 2038)])  # candle1 no touch, candle2 stop touch only (low>entry)
    result = simulate_entry(df, activation_idx=0, direction="sell", entry=2000.0, stop=2037.0)
    assert result.outcome == "expired"
    assert result.reason == "stop_touched_before_entry"
    assert len(result.candles) == 2
    assert result.candles[0].entry_touched is False
    assert result.candles[0].stop_touched is False
    assert result.candles[1].stop_touched is True
    assert result.candles[1].entry_touched is False


# ---------------------------------------------------------------------------
# Same-bar conflict occurring on the 2nd window candle (1st candle touches nothing)
# ---------------------------------------------------------------------------


def test_same_bar_conflict_on_second_candle_after_first_no_touch():
    # candle1 (buy): high<entry, low>stop -> no touch at all
    # candle2: touches both entry and stop -> conflict
    df = make_df([(1, 1), (1980, 1970), (2010, 1960)])
    result = simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=1963.0)
    assert result.outcome == "expired"
    assert result.reason == "same_bar_entry_stop_conflict"
    assert len(result.candles) == 2
    assert result.candles[0].entry_touched is False
    assert result.candles[0].stop_touched is False
    assert result.candles[1].entry_touched is True
    assert result.candles[1].stop_touched is True


# ---------------------------------------------------------------------------
# Stop and entry on the exact same tick -> raise (invalid setup, not a data case)
# ---------------------------------------------------------------------------


def test_buy_stop_equal_entry_tick_raises():
    df = make_df([(1, 1), (2010, 2005), (2010, 2005)])
    with pytest.raises(ValueError, match="stop .* must be < entry"):
        simulate_entry(df, activation_idx=0, direction="buy", entry=2000.0, stop=2000.0)


def test_sell_stop_equal_entry_tick_raises():
    df = make_df([(1, 1), (2010, 2005), (2010, 2005)])
    with pytest.raises(ValueError, match="stop .* must be > entry"):
        simulate_entry(df, activation_idx=0, direction="sell", entry=2000.0, stop=2000.0)
