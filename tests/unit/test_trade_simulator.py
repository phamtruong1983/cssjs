"""Tests for post-fill trade outcome simulation (src/backtest/trade_simulator.py).

Per docs/DAO_GAM_RULES.md Section 5 "Same-bar SL-vs-TP after entry".
Pure function -- does not call src.engine, src.signals, or
src.execution.entry_simulation.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.backtest.trade_simulator import simulate_trade  # noqa: E402
from src.market_structure.zones import TICK  # noqa: E402

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")


def load_fixture_h1(name):
    return pd.read_csv(os.path.join(FIXTURES_DIR, name, "h1.csv"))


def make_df(rows, columns=("high", "low")):
    return pd.DataFrame(rows, columns=list(columns))


def append_rows(df, rows, start_ts, columns):
    """Append rows (dicts) to df, with `timestamp` auto-incrementing by
    1h from start_ts if `timestamp` is one of `columns` and not given."""
    new_rows = []
    ts = pd.Timestamp(start_ts)
    for i, r in enumerate(rows):
        row = dict(r)
        if "timestamp" in columns and "timestamp" not in row:
            row["timestamp"] = (ts + pd.Timedelta(hours=i + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        new_rows.append(row)
    extra = pd.DataFrame(new_rows, columns=list(columns))
    return pd.concat([df[list(columns)], extra], ignore_index=True)


# ---------------------------------------------------------------------------
# (a) Fixture 01 (buy): entry=2000, stop=1963, tp1=2070, tp2=2105, fill_idx=24
# ---------------------------------------------------------------------------


def _fixture_01_base_cols():
    h1 = load_fixture_h1("01_buy_valid")
    return h1[["open", "high", "low", "close", "timestamp"]].copy()


def test_fixture_01_buy_win_at_tp1_not_yet_then_hit():
    base = _fixture_01_base_cols()
    df = append_rows(
        base,
        [
            {"open": 2005.0, "high": 2069.99, "low": 2000.0, "close": 2069.99},  # not yet
            {"open": 2069.99, "high": 2070.00, "low": 2065.0, "close": 2070.00},  # hits tp1 exactly
        ],
        start_ts="2024-01-03T00:00:00Z",
        columns=["open", "high", "low", "close", "timestamp"],
    )
    result = simulate_trade(df, fill_idx=24, direction="buy", entry=2000.0, stop=1963.0, target=2070.0)
    assert result.outcome == "win"
    assert result.exit_idx == 26
    assert result.exit_price == pytest.approx(2070.0)
    assert result.bars_held == 2
    assert result.bars_evaluated == 2
    assert result.r_multiple == pytest.approx(70 / 37)
    assert result.both_touched is False


def test_fixture_01_buy_win_at_tp2():
    base = _fixture_01_base_cols()
    df = append_rows(
        base,
        [
            {"open": 2005.0, "high": 2069.99, "low": 2000.0, "close": 2069.99},
            {"open": 2069.99, "high": 2105.00, "low": 2065.0, "close": 2105.00},  # hits tp2 exactly
        ],
        start_ts="2024-01-03T00:00:00Z",
        columns=["open", "high", "low", "close", "timestamp"],
    )
    result = simulate_trade(df, fill_idx=24, direction="buy", entry=2000.0, stop=1963.0, target=2105.0)
    assert result.outcome == "win"
    assert result.exit_price == pytest.approx(2105.0)
    assert result.r_multiple == pytest.approx(105 / 37)


def test_fixture_01_buy_stop_exact_boundary_is_loss():
    base = _fixture_01_base_cols()
    df = append_rows(
        base,
        [{"open": 1990.0, "high": 2000.0, "low": 1963.00, "close": 1970.0}],
        start_ts="2024-01-03T00:00:00Z",
        columns=["open", "high", "low", "close", "timestamp"],
    )
    result = simulate_trade(df, fill_idx=24, direction="buy", entry=2000.0, stop=1963.0, target=2070.0)
    assert result.outcome == "loss"
    assert result.exit_price == pytest.approx(1963.0)
    assert result.r_multiple == -1.0
    assert result.both_touched is False


def test_fixture_01_buy_stop_one_tick_above_not_loss_yet():
    base = _fixture_01_base_cols()
    df = append_rows(
        base,
        [{"open": 1990.0, "high": 2000.0, "low": 1963.01, "close": 1970.0}],
        start_ts="2024-01-03T00:00:00Z",
        columns=["open", "high", "low", "close", "timestamp"],
    )
    result = simulate_trade(df, fill_idx=24, direction="buy", entry=2000.0, stop=1963.0, target=2070.0)
    assert result.outcome == "open_at_end"
    assert result.bars_evaluated == 1


def test_fixture_01_buy_both_touched_same_candle_is_loss():
    base = _fixture_01_base_cols()
    df = append_rows(
        base,
        [{"open": 1990.0, "high": 2075.0, "low": 1960.0, "close": 1970.0}],
        start_ts="2024-01-03T00:00:00Z",
        columns=["open", "high", "low", "close", "timestamp"],
    )
    result = simulate_trade(df, fill_idx=24, direction="buy", entry=2000.0, stop=1963.0, target=2070.0)
    assert result.outcome == "loss"
    assert result.exit_price == pytest.approx(1963.0)
    assert result.both_touched is True


# ---------------------------------------------------------------------------
# (b) Fixture 02 (sell), mirrored: entry=2000, stop=2037, tp1=1930, tp2=1895
# ---------------------------------------------------------------------------


def _fixture_02_base_cols():
    h1 = load_fixture_h1("02_sell_valid")
    return h1[["open", "high", "low", "close", "timestamp"]].copy()


def test_fixture_02_sell_win_at_tp1_not_yet_then_hit():
    base = _fixture_02_base_cols()
    df = append_rows(
        base,
        [
            {"open": 1995.0, "high": 2000.0, "low": 1930.01, "close": 1930.01},  # not yet
            {"open": 1930.01, "high": 1935.0, "low": 1930.00, "close": 1930.00},  # hits tp1 exactly
        ],
        start_ts="2024-01-03T00:00:00Z",
        columns=["open", "high", "low", "close", "timestamp"],
    )
    result = simulate_trade(df, fill_idx=24, direction="sell", entry=2000.0, stop=2037.0, target=1930.0)
    assert result.outcome == "win"
    assert result.exit_idx == 26
    assert result.exit_price == pytest.approx(1930.0)
    assert result.bars_held == 2
    assert result.r_multiple == pytest.approx(70 / 37)


def test_fixture_02_sell_win_at_tp2():
    base = _fixture_02_base_cols()
    df = append_rows(
        base,
        [
            {"open": 1995.0, "high": 2000.0, "low": 1930.01, "close": 1930.01},
            {"open": 1930.01, "high": 1935.0, "low": 1895.00, "close": 1895.00},  # hits tp2 exactly
        ],
        start_ts="2024-01-03T00:00:00Z",
        columns=["open", "high", "low", "close", "timestamp"],
    )
    result = simulate_trade(df, fill_idx=24, direction="sell", entry=2000.0, stop=2037.0, target=1895.0)
    assert result.outcome == "win"
    assert result.exit_price == pytest.approx(1895.0)
    assert result.r_multiple == pytest.approx(105 / 37)


def test_fixture_02_sell_stop_exact_boundary_is_loss():
    base = _fixture_02_base_cols()
    df = append_rows(
        base,
        [{"open": 2010.0, "high": 2037.00, "low": 2000.0, "close": 2030.0}],
        start_ts="2024-01-03T00:00:00Z",
        columns=["open", "high", "low", "close", "timestamp"],
    )
    result = simulate_trade(df, fill_idx=24, direction="sell", entry=2000.0, stop=2037.0, target=1930.0)
    assert result.outcome == "loss"
    assert result.exit_price == pytest.approx(2037.0)


def test_fixture_02_sell_stop_one_tick_below_not_loss_yet():
    base = _fixture_02_base_cols()
    df = append_rows(
        base,
        [{"open": 2010.0, "high": 2036.99, "low": 2000.0, "close": 2030.0}],
        start_ts="2024-01-03T00:00:00Z",
        columns=["open", "high", "low", "close", "timestamp"],
    )
    result = simulate_trade(df, fill_idx=24, direction="sell", entry=2000.0, stop=2037.0, target=1930.0)
    assert result.outcome == "open_at_end"


def test_fixture_02_sell_both_touched_same_candle_is_loss():
    base = _fixture_02_base_cols()
    df = append_rows(
        base,
        [{"open": 2010.0, "high": 2040.0, "low": 1925.0, "close": 2030.0}],
        start_ts="2024-01-03T00:00:00Z",
        columns=["open", "high", "low", "close", "timestamp"],
    )
    result = simulate_trade(df, fill_idx=24, direction="sell", entry=2000.0, stop=2037.0, target=1930.0)
    assert result.outcome == "loss"
    assert result.exit_price == pytest.approx(2037.0)
    assert result.both_touched is True


# ---------------------------------------------------------------------------
# (c) Fill candle itself never read, even if it "would have" won
# ---------------------------------------------------------------------------


def test_fill_candle_high_above_target_is_never_counted():
    # idx0: activation-ish filler; idx1: fill candle -- its own high (5000)
    # is >= target(2070), but this candle must never be read; idx2: no touch
    df = make_df([(1, 1), (5000, 1995), (2010, 2005)])
    result = simulate_trade(df, fill_idx=1, direction="buy", entry=2000.0, stop=1963.0, target=2070.0)
    assert result.outcome == "open_at_end"
    assert result.bars_evaluated == 1


# ---------------------------------------------------------------------------
# (d) open_at_end: zero and multiple no-touch candles after fill_idx
# ---------------------------------------------------------------------------


def test_open_at_end_zero_candles_after_fill():
    df = make_df([(1, 1), (2010, 1995)])  # fill_idx is the last row
    result = simulate_trade(df, fill_idx=1, direction="buy", entry=2000.0, stop=1963.0, target=2070.0)
    assert result.outcome == "open_at_end"
    assert result.exit_idx is None
    assert result.exit_price is None
    assert result.r_multiple is None
    assert result.bars_held is None
    assert result.bars_evaluated == 0
    assert result.both_touched is False


def test_open_at_end_three_no_touch_candles():
    df = make_df(
        [
            (1, 1),
            (2010, 1995),  # fill candle
            (2010, 1990),
            (2015, 1985),
            (2020, 1980),
        ]
    )
    result = simulate_trade(df, fill_idx=1, direction="buy", entry=2000.0, stop=1963.0, target=2070.0)
    assert result.outcome == "open_at_end"
    assert result.bars_evaluated == 3


# ---------------------------------------------------------------------------
# (e) gap_through_stop
# ---------------------------------------------------------------------------


def test_gap_through_stop_true_buy():
    df = pd.DataFrame(
        [
            {"open": 2000.0, "high": 2010.0, "low": 1995.0},  # fill candle
            {"open": 1960.0, "high": 1965.0, "low": 1955.0},  # gaps below stop(1963) at open
        ],
        columns=["open", "high", "low"],
    )
    result = simulate_trade(df, fill_idx=0, direction="buy", entry=2000.0, stop=1963.0, target=2070.0)
    assert result.outcome == "loss"
    assert result.exit_price == pytest.approx(1963.0)  # still exactly stop, no slippage modeled
    assert result.gap_through_stop is True


def test_gap_through_stop_none_without_open_column():
    df = make_df([(2010.0, 1995.0), (1965.0, 1955.0)])  # no 'open' column
    result = simulate_trade(df, fill_idx=0, direction="buy", entry=2000.0, stop=1963.0, target=2070.0)
    assert result.outcome == "loss"
    assert result.gap_through_stop is None


def test_gap_through_stop_false_when_open_above_stop_buy():
    df = pd.DataFrame(
        [
            {"open": 2000.0, "high": 2010.0, "low": 1995.0},  # fill candle
            {"open": 1970.0, "high": 1975.0, "low": 1960.0},  # open above stop, low touches it
        ],
        columns=["open", "high", "low"],
    )
    result = simulate_trade(df, fill_idx=0, direction="buy", entry=2000.0, stop=1963.0, target=2070.0)
    assert result.outcome == "loss"
    assert result.gap_through_stop is False


# ---------------------------------------------------------------------------
# (f) Look-ahead
# ---------------------------------------------------------------------------


def test_no_lookahead_data_after_resolution_does_not_affect_result():
    df = make_df([(1, 1), (2010, 1995), (2010, 1990), (5000, 4000)])  # resolves at idx2 (no touch, then...)
    # Actually make idx2 the resolving (stop) candle so idx3 is strictly after resolution.
    df = make_df([(1, 1), (2010, 1995), (1970, 1960), (5000, 4000)])
    result_before = simulate_trade(df, fill_idx=0, direction="buy", entry=2000.0, stop=1963.0, target=2070.0)
    assert result_before.outcome == "loss"
    assert result_before.exit_idx == 2

    df_mutated = df.copy()
    df_mutated.loc[3, ["high", "low"]] = [np.nan, np.nan]
    result_after = simulate_trade(df_mutated, fill_idx=0, direction="buy", entry=2000.0, stop=1963.0, target=2070.0)
    assert result_after.outcome == result_before.outcome
    assert result_after.exit_idx == result_before.exit_idx
    assert result_after.exit_price == result_before.exit_price


def test_nan_in_already_read_candle_before_resolution_raises():
    # idx1 (fill_idx+1) must be read (no touch) before idx2 resolves (target hit).
    df = make_df([(1, 1), (2010, 1995), (2075.0, 2065.0)])
    result = simulate_trade(df, fill_idx=0, direction="buy", entry=2000.0, stop=1963.0, target=2070.0)
    assert result.outcome == "win"
    assert result.exit_idx == 2

    df_mutated = df.copy()
    df_mutated.loc[1, ["high", "low"]] = [np.nan, np.nan]  # idx1 was already read -> must raise
    with pytest.raises(ValueError, match="NaN"):
        simulate_trade(df_mutated, fill_idx=0, direction="buy", entry=2000.0, stop=1963.0, target=2070.0)


# ---------------------------------------------------------------------------
# (g) Validation / raises
# ---------------------------------------------------------------------------


def test_invalid_direction_raises():
    df = make_df([(1, 1), (2010, 1995)])
    with pytest.raises(ValueError, match="direction must be one of"):
        simulate_trade(df, fill_idx=0, direction="up", entry=2000.0, stop=1963.0, target=2070.0)


def test_fill_idx_non_int_raises():
    df = make_df([(1, 1), (2010, 1995)])
    with pytest.raises(TypeError, match="fill_idx must be an int"):
        simulate_trade(df, fill_idx=0.5, direction="buy", entry=2000.0, stop=1963.0, target=2070.0)


def test_fill_idx_out_of_range_raises():
    df = make_df([(1, 1), (2010, 1995)])
    with pytest.raises(ValueError, match="fill_idx must be in"):
        simulate_trade(df, fill_idx=99, direction="buy", entry=2000.0, stop=1963.0, target=2070.0)


def test_missing_low_column_raises():
    df = pd.DataFrame({"high": [1, 2010]})
    with pytest.raises(ValueError, match="missing required column"):
        simulate_trade(df, fill_idx=0, direction="buy", entry=2000.0, stop=1963.0, target=2070.0)


def test_entry_nan_raises():
    df = make_df([(1, 1), (2010, 1995)])
    with pytest.raises(ValueError, match="entry must be a finite number"):
        simulate_trade(df, fill_idx=0, direction="buy", entry=float("nan"), stop=1963.0, target=2070.0)


def test_target_inf_raises():
    df = make_df([(1, 1), (2010, 1995)])
    with pytest.raises(ValueError, match="target must be a finite number"):
        simulate_trade(df, fill_idx=0, direction="buy", entry=2000.0, stop=1963.0, target=float("inf"))


def test_buy_stop_wrong_side_raises():
    df = make_df([(1, 1), (2010, 1995)])
    with pytest.raises(ValueError, match="stop < entry < target"):
        simulate_trade(df, fill_idx=0, direction="buy", entry=2000.0, stop=2001.0, target=2070.0)


def test_buy_target_wrong_side_raises():
    df = make_df([(1, 1), (2010, 1995)])
    with pytest.raises(ValueError, match="stop < entry < target"):
        simulate_trade(df, fill_idx=0, direction="buy", entry=2000.0, stop=1963.0, target=1999.0)


def test_sell_target_wrong_side_raises():
    df = make_df([(1, 1), (2010, 1995)])
    with pytest.raises(ValueError, match="target < entry < stop"):
        simulate_trade(df, fill_idx=0, direction="sell", entry=2000.0, stop=2037.0, target=2001.0)


def test_sell_stop_wrong_side_raises():
    df = make_df([(1, 1), (2010, 1995)])
    with pytest.raises(ValueError, match="target < entry < stop"):
        simulate_trade(df, fill_idx=0, direction="sell", entry=2000.0, stop=1999.0, target=1930.0)


def test_high_below_low_in_read_candle_raises():
    df = make_df([(1, 1), (100, 200)])  # idx1 (read): high < low
    with pytest.raises(ValueError, match="high < low"):
        simulate_trade(df, fill_idx=0, direction="buy", entry=2000.0, stop=1963.0, target=2070.0)


# ---------------------------------------------------------------------------
# (h) r_multiple: uneven division, and tick-quantization under float noise
# ---------------------------------------------------------------------------


def test_r_multiple_uneven_division_70_over_37():
    df = make_df([(1, 1), (2010, 1995), (2075.0, 2065.0)])
    result = simulate_trade(df, fill_idx=0, direction="buy", entry=2000.0, stop=1963.0, target=2070.0)
    assert result.outcome == "win"
    assert result.r_multiple == pytest.approx(70 / 37)
    assert result.risk_ticks == 3700
    assert result.reward_ticks == 7000


def test_r_multiple_correct_under_float_noise_in_levels():
    noisy_entry = 2000.0000000001
    noisy_stop = 1963.0000000001
    noisy_target = 2070.0000000001
    df = make_df([(1, 1), (2010, 1995), (2075.0, 2065.0)])
    result = simulate_trade(df, fill_idx=0, direction="buy", entry=noisy_entry, stop=noisy_stop, target=noisy_target)
    assert result.outcome == "win"
    assert result.r_multiple == pytest.approx(70 / 37)
    assert result.risk_ticks == 3700
    assert result.reward_ticks == 7000
