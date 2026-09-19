"""Tests for SL/TP1/TP2/R:R calculation (src/risk/risk_reward.py).

Per docs/DAO_GAM_RULES.md Section 3 rules 7, 8 and docs/DATA_SCHEMA.md
Sections 5-6. Does not call src/signals/sweep.py, src/signals/m15_reaction.py,
or src/market_structure/zones.create_zones.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.indicators.atr import atr as compute_atr  # noqa: E402
from src.risk.risk_reward import compute_risk_reward  # noqa: E402
from src.market_structure.zones import TICK  # noqa: E402

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")


def load_fixture_h1(name):
    return pd.read_csv(os.path.join(FIXTURES_DIR, name, "h1.csv"))


def make_df(highs, lows, closes=None):
    if closes is None:
        closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    return pd.DataFrame({"high": highs, "low": lows, "close": closes})


# ---------------------------------------------------------------------------
# Fixture 01 (BUY) -- real h1.csv + real atr.py output
# ---------------------------------------------------------------------------


def test_fixture_01_buy_tradable():
    df = load_fixture_h1("01_buy_valid")
    atr = compute_atr(df, period=14)
    atr_h1_14 = float(atr.iloc[21])  # atr[sweep_idx - 1], sweep_idx=22
    sweep_extreme = float(df.loc[22, "low"])  # sourced from the CSV, not hardcoded

    result = compute_risk_reward(
        df, sweep_idx=22, direction="buy", zone_center=2000.0, sweep_extreme=sweep_extreme, atr_h1_14=atr_h1_14
    )

    assert sweep_extreme == pytest.approx(1965.0)
    assert atr_h1_14 == pytest.approx(10.0)
    assert result.entry == pytest.approx(2000.0)
    assert result.stop == pytest.approx(1963.0)  # 1965 - 0.20*10
    assert result.risk == pytest.approx(37.0)
    assert result.tp1 == pytest.approx(2070.0)  # idx 11 swing high
    assert result.tp1_idx == 11
    assert result.sweep_amplitude == pytest.approx(35.0)  # |1965-2000|
    assert result.tp2 == pytest.approx(2105.0)  # 2070+35
    assert result.reward_to_tp2 == pytest.approx(105.0)
    assert result.rr_to_tp2 == pytest.approx(105 / 37)  # ~2.8378
    assert result.tradable is True
    assert result.reason == "ok"


def test_fixture_01_reward_and_rr_to_tp1():
    """reward_to_tp1 / rr_to_tp1 are reference-only fields, per R1(c):
    reward_to_tp1 = |tp1 - entry| = |2070 - 2000| = 70; rr_to_tp1 =
    70 / 37 (using the same tick-rounded risk as rr_to_tp2)."""
    df = load_fixture_h1("01_buy_valid")
    atr = compute_atr(df, period=14)
    atr_h1_14 = float(atr.iloc[21])
    sweep_extreme = float(df.loc[22, "low"])

    result = compute_risk_reward(
        df, sweep_idx=22, direction="buy", zone_center=2000.0, sweep_extreme=sweep_extreme, atr_h1_14=atr_h1_14
    )

    assert result.reward_to_tp1 == pytest.approx(70.0)
    assert result.rr_to_tp1 == pytest.approx(70 / 37)
    # reference-only: does not affect tradable/reason, which are gated on rr_to_tp2 alone.
    assert result.tradable is True
    assert result.reason == "ok"


def test_tp2_is_a_tick_multiple():
    df = load_fixture_h1("01_buy_valid")
    atr = compute_atr(df, period=14)
    atr_h1_14 = float(atr.iloc[21])
    sweep_extreme = float(df.loc[22, "low"])

    result = compute_risk_reward(
        df, sweep_idx=22, direction="buy", zone_center=2000.0, sweep_extreme=sweep_extreme, atr_h1_14=atr_h1_14
    )
    ticks = result.tp2 / TICK
    assert ticks == pytest.approx(round(ticks), abs=1e-6)


# ---------------------------------------------------------------------------
# Fixture 02 (SELL) -- mirror of fixture 01
# ---------------------------------------------------------------------------


def test_fixture_02_sell_tradable():
    df = load_fixture_h1("02_sell_valid")
    atr = compute_atr(df, period=14)
    atr_h1_14 = float(atr.iloc[21])
    sweep_extreme = float(df.loc[22, "high"])  # sourced from the CSV, not hardcoded

    result = compute_risk_reward(
        df, sweep_idx=22, direction="sell", zone_center=2000.0, sweep_extreme=sweep_extreme, atr_h1_14=atr_h1_14
    )

    assert sweep_extreme == pytest.approx(2035.0)
    assert atr_h1_14 == pytest.approx(10.0)
    assert result.entry == pytest.approx(2000.0)
    assert result.stop == pytest.approx(2037.0)  # 2035 + 0.20*10
    assert result.risk == pytest.approx(37.0)
    assert result.tp1 == pytest.approx(1930.0)  # idx 11 swing low
    assert result.tp1_idx == 11
    assert result.sweep_amplitude == pytest.approx(35.0)
    assert result.tp2 == pytest.approx(1895.0)  # 1930-35
    assert result.reward_to_tp2 == pytest.approx(105.0)
    assert result.rr_to_tp2 == pytest.approx(105 / 37)
    assert result.tradable is True
    assert result.reason == "ok"


# ---------------------------------------------------------------------------
# Fixture 05 -- deep sweep, R:R below 2.0
# ---------------------------------------------------------------------------


def test_fixture_05_rr_below_threshold():
    df = load_fixture_h1("05_rr_below_threshold")
    atr = compute_atr(df, period=14)
    atr_h1_14 = float(atr.iloc[21])
    sweep_extreme = float(df.loc[22, "low"])  # sourced from the CSV, not hardcoded

    result = compute_risk_reward(
        df, sweep_idx=22, direction="buy", zone_center=2000.0, sweep_extreme=sweep_extreme, atr_h1_14=atr_h1_14
    )

    assert sweep_extreme == pytest.approx(1920.0)
    assert atr_h1_14 == pytest.approx(10.0)
    assert result.stop == pytest.approx(1918.0)  # 1920 - 0.20*10
    assert result.risk == pytest.approx(82.0)
    assert result.tp1 == pytest.approx(2070.0)  # unchanged from fixture 01
    assert result.sweep_amplitude == pytest.approx(80.0)  # |1920-2000|
    assert result.tp2 == pytest.approx(2150.0)  # 2070+80
    assert result.reward_to_tp2 == pytest.approx(150.0)
    assert result.rr_to_tp2 == pytest.approx(150 / 82)  # ~1.829
    assert result.tradable is False
    assert result.reason == "rr_below_threshold"


# ---------------------------------------------------------------------------
# Look-ahead: swing high idx 21 (2050) must NOT be used as TP1 at sweep_idx=22
# ---------------------------------------------------------------------------


def test_fixture_01_lookahead_swing_idx21_not_confirmed_at_sweep():
    df = load_fixture_h1("01_buy_valid")
    atr = compute_atr(df, period=14)
    atr_h1_14 = float(atr.iloc[21])

    result = compute_risk_reward(
        df, sweep_idx=22, direction="buy", zone_center=2000.0, sweep_extreme=1965.0, atr_h1_14=atr_h1_14
    )
    # idx 21 (high=2050) needs idx+n=24 <= sweep_idx=22 to confirm -- it
    # does not, so tp1 must be idx 11 (2070), not idx 21 (2050).
    assert result.tp1_idx == 11
    assert result.tp1 == pytest.approx(2070.0)
    assert result.tp1 != pytest.approx(2050.0)


def test_no_lookahead_data_after_sweep_idx_does_not_affect_result():
    df = load_fixture_h1("01_buy_valid")
    atr = compute_atr(df, period=14)
    atr_h1_14 = float(atr.iloc[21])

    result_before = compute_risk_reward(
        df, sweep_idx=22, direction="buy", zone_center=2000.0, sweep_extreme=1965.0, atr_h1_14=atr_h1_14
    )

    df_mutated = df.copy()
    df_mutated[["open", "high", "low", "close"]] = df_mutated[["open", "high", "low", "close"]].astype(float)
    df_mutated.loc[23:, ["open", "high", "low", "close"]] = [
        [1.0, 2.0, 0.5, 1.5],
        [500.0, 600.0, 400.0, 550.0],
    ]

    result_after = compute_risk_reward(
        df_mutated, sweep_idx=22, direction="buy", zone_center=2000.0, sweep_extreme=1965.0, atr_h1_14=atr_h1_14
    )

    assert result_before == result_after


# ---------------------------------------------------------------------------
# R:R boundary: exactly 2.0 passes, one tick under fails
#
# Manual construction: highs=[10,20,30,100,30,20,10] (7 bars) -> the only
# fractal swing high (n=3) is at idx 3 (high=100), confirmed once the full
# 7-bar slice is used (find_swings only evaluates positions 3..(7-3-1)=3).
# zone_center(entry)=50, direction=buy, sweep_extreme=40 (< entry, valid).
# sweep_amplitude = |40-50| = 10. With tp1=100: tp2=100+10=110,
# reward=|110-50|=60. Choosing atr_h1_14=100: stop=40-0.2*100=20,
# risk=50-20=30. rr = 60/30 = 2.0 exactly -> tradable.
# ---------------------------------------------------------------------------


def test_rr_exactly_2_0_is_tradable():
    df = make_df([10, 20, 30, 100, 30, 20, 10], [5, 15, 25, 95, 25, 15, 5])
    result = compute_risk_reward(df, sweep_idx=6, direction="buy", zone_center=50.0, sweep_extreme=40.0, atr_h1_14=100.0)
    assert result.tp1 == pytest.approx(100.0)
    assert result.stop == pytest.approx(20.0)
    assert result.risk == pytest.approx(30.0)
    assert result.reward_to_tp2 == pytest.approx(60.0)
    assert result.rr_to_tp2 == pytest.approx(2.0)
    assert result.tradable is True
    assert result.reason == "ok"


def test_rr_one_tick_under_2_0_is_not_tradable():
    # Same setup, but tp1 (the swing high price) is 99.99 instead of 100 ->
    # sweep_amplitude still 10, tp2=109.99, reward=59.99 (1 tick short of 60).
    df = make_df([10, 20, 30, 99.99, 30, 20, 10], [5, 15, 25, 94.99, 25, 15, 5])
    result = compute_risk_reward(df, sweep_idx=6, direction="buy", zone_center=50.0, sweep_extreme=40.0, atr_h1_14=100.0)
    assert result.tp1 == pytest.approx(99.99)
    assert result.reward_to_tp2 == pytest.approx(59.99)
    assert result.risk == pytest.approx(30.0)
    assert result.rr_to_tp2 == pytest.approx(59.99 / 30)
    assert result.tradable is False
    assert result.reason == "rr_below_threshold"


# ---------------------------------------------------------------------------
# TP1 selection: no qualifying swing -> tp1_unavailable
# ---------------------------------------------------------------------------


def test_no_qualifying_swing_gives_tp1_unavailable():
    # Monotonic increasing highs -> no fractal swing high at all.
    highs = list(range(10, 24))
    lows = [h - 5 for h in highs]
    df = make_df(highs, lows)
    result = compute_risk_reward(df, sweep_idx=13, direction="buy", zone_center=5.0, sweep_extreme=0.0, atr_h1_14=1.0)
    assert result.tradable is False
    assert result.reason == "tp1_unavailable"
    assert result.tp1 is None
    assert result.tp1_idx is None
    assert result.tp2 is None
    assert result.reward_to_tp2 is None
    assert result.rr_to_tp2 is None
    # entry/stop/risk/sweep_amplitude/atr/sweep_extreme/zone_center still populated
    assert result.entry == pytest.approx(5.0)
    assert result.sweep_amplitude == pytest.approx(5.0)


def test_swing_on_wrong_side_of_entry_not_selected():
    # Swing high at idx3 (100) is ABOVE entry(150) -- wrong side for BUY
    # reversal target (must be > entry, and 100 < 150) -- but include
    # another later swing high below entry too, to confirm it also isn't
    # picked purely because of recency.
    highs = [10, 20, 30, 100, 30, 20, 10, 20, 30, 40, 30, 20, 10]
    lows = [h - 5 for h in highs]
    df = make_df(highs, lows)
    # zone_center=150 -> no swing high exceeds 150 anywhere -> tp1_unavailable
    result = compute_risk_reward(
        df, sweep_idx=12, direction="buy", zone_center=150.0, sweep_extreme=100.0, atr_h1_14=1.0
    )
    assert result.reason == "tp1_unavailable"


def test_multiple_qualifying_swings_picks_largest_idx():
    # Two swing highs above entry(50): idx3 (100) and idx11 (200).
    highs = [10, 20, 30, 100, 30, 20, 10, 20, 30, 200, 30, 20, 10, 20, 30]
    lows = [h - 5 for h in highs]
    df = make_df(highs, lows)
    result = compute_risk_reward(df, sweep_idx=14, direction="buy", zone_center=50.0, sweep_extreme=10.0, atr_h1_14=1.0)
    assert result.tp1_idx == 9
    assert result.tp1 == pytest.approx(200.0)


def test_nearest_in_time_not_highest_price():
    """Distinguishes 'nearest in time' from 'highest price': an EARLIER
    swing high (idx3=200, higher price) and a LATER swing high (idx9=80,
    lower price but still > entry=50) both qualify -- TP1 must be the
    later one (idx9=80), proving selection is by recency, not magnitude."""
    highs = [10, 20, 30, 200, 30, 20, 10, 20, 30, 80, 30, 20, 10, 20, 30]
    lows = [h - 5 for h in highs]
    df = make_df(highs, lows)
    result = compute_risk_reward(df, sweep_idx=14, direction="buy", zone_center=50.0, sweep_extreme=10.0, atr_h1_14=1.0)
    assert result.tp1_idx == 9
    assert result.tp1 == pytest.approx(80.0)
    assert result.tp1 != pytest.approx(200.0)


def test_more_recent_swing_on_wrong_side_is_skipped_valid_one_still_chosen():
    """A later swing high (idx9=40) is on the WRONG side of entry(50)
    (40 <= 50, not a valid BUY reversal target) -- it must be skipped
    even though it is more recent than the earlier, valid swing high
    (idx3=100, which is > 50)."""
    highs = [10, 20, 30, 100, 30, 20, 10, 20, 30, 40, 30, 20, 10, 20, 30]
    lows = [h - 5 for h in highs]
    df = make_df(highs, lows)
    result = compute_risk_reward(df, sweep_idx=14, direction="buy", zone_center=50.0, sweep_extreme=10.0, atr_h1_14=1.0)
    assert result.tp1_idx == 3
    assert result.tp1 == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# SELL mirror: R:R boundary and largest-idx selection
# ---------------------------------------------------------------------------


def test_sell_rr_exactly_2_0_is_tradable():
    # Mirrors test_rr_exactly_2_0_is_tradable: swing low at idx3=0 (< entry=50).
    # sweep_extreme=60 (>50, valid for sell). sweep_amplitude=|60-50|=10.
    # tp2=tp1-amplitude=0-10=-10, reward=|-10-50|=60. stop=60+0.2*100=80,
    # risk=|50-80|=30. rr=60/30=2.0 exactly.
    lows = [90, 80, 70, 0, 70, 80, 90]
    highs = [l + 5 for l in lows]
    df = make_df(highs, lows)
    result = compute_risk_reward(df, sweep_idx=6, direction="sell", zone_center=50.0, sweep_extreme=60.0, atr_h1_14=100.0)
    assert result.tp1 == pytest.approx(0.0)
    assert result.stop == pytest.approx(80.0)
    assert result.risk == pytest.approx(30.0)
    assert result.reward_to_tp2 == pytest.approx(60.0)
    assert result.rr_to_tp2 == pytest.approx(2.0)
    assert result.tradable is True
    assert result.reason == "ok"


def test_sell_rr_one_tick_under_2_0_is_not_tradable():
    # tp1 raised by 1 tick (0.01) -> reward shrinks by 1 tick (59.99).
    lows = [90, 80, 70, 0.01, 70, 80, 90]
    highs = [l + 5 for l in lows]
    df = make_df(highs, lows)
    result = compute_risk_reward(df, sweep_idx=6, direction="sell", zone_center=50.0, sweep_extreme=60.0, atr_h1_14=100.0)
    assert result.tp1 == pytest.approx(0.01)
    assert result.reward_to_tp2 == pytest.approx(59.99)
    assert result.risk == pytest.approx(30.0)
    assert result.tradable is False
    assert result.reason == "rr_below_threshold"


def test_sell_multiple_qualifying_swings_picks_largest_idx():
    # Two swing lows below entry(50): idx3=10 and idx9=-100.
    lows = [90, 80, 70, 10, 70, 80, 90, 80, 70, -100, 70, 80, 90, 80, 70]
    highs = [l + 50 for l in lows]
    df = make_df(highs, lows)
    result = compute_risk_reward(df, sweep_idx=14, direction="sell", zone_center=50.0, sweep_extreme=60.0, atr_h1_14=1.0)
    assert result.tp1_idx == 9
    assert result.tp1 == pytest.approx(-100.0)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_invalid_direction_raises():
    df = make_df([10, 20, 30, 100, 30, 20, 10], [5, 15, 25, 95, 25, 15, 5])
    with pytest.raises(ValueError, match="direction must be one of"):
        compute_risk_reward(df, sweep_idx=6, direction="up", zone_center=50.0, sweep_extreme=40.0, atr_h1_14=1.0)


def test_sweep_idx_negative_raises():
    df = make_df([10, 20, 30, 100, 30, 20, 10], [5, 15, 25, 95, 25, 15, 5])
    with pytest.raises(ValueError, match="sweep_idx must be in"):
        compute_risk_reward(df, sweep_idx=-1, direction="buy", zone_center=50.0, sweep_extreme=40.0, atr_h1_14=1.0)


def test_sweep_idx_out_of_range_raises():
    df = make_df([10, 20, 30, 100, 30, 20, 10], [5, 15, 25, 95, 25, 15, 5])
    with pytest.raises(ValueError, match="sweep_idx must be in"):
        compute_risk_reward(df, sweep_idx=999, direction="buy", zone_center=50.0, sweep_extreme=40.0, atr_h1_14=1.0)


def test_sweep_idx_non_int_raises():
    df = make_df([10, 20, 30, 100, 30, 20, 10], [5, 15, 25, 95, 25, 15, 5])
    with pytest.raises(TypeError, match="sweep_idx must be an int"):
        compute_risk_reward(df, sweep_idx=6.5, direction="buy", zone_center=50.0, sweep_extreme=40.0, atr_h1_14=1.0)


def test_missing_close_column_raises():
    df = pd.DataFrame({"high": [10, 20, 30, 100, 30, 20, 10], "low": [5, 15, 25, 95, 25, 15, 5]})
    with pytest.raises(ValueError, match="missing required column"):
        compute_risk_reward(df, sweep_idx=6, direction="buy", zone_center=50.0, sweep_extreme=40.0, atr_h1_14=1.0)


def test_nan_in_used_slice_raises():
    df = make_df([10, 20, 30, 100, 30, 20, 10], [5, 15, 25, 95, 25, 15, 5])
    df.loc[2, "high"] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        compute_risk_reward(df, sweep_idx=6, direction="buy", zone_center=50.0, sweep_extreme=40.0, atr_h1_14=1.0)


def test_nan_in_close_column_raises():
    df = make_df([10, 20, 30, 100, 30, 20, 10], [5, 15, 25, 95, 25, 15, 5])
    df.loc[2, "close"] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        compute_risk_reward(df, sweep_idx=6, direction="buy", zone_center=50.0, sweep_extreme=40.0, atr_h1_14=1.0)


def test_atr_zero_raises():
    df = make_df([10, 20, 30, 100, 30, 20, 10], [5, 15, 25, 95, 25, 15, 5])
    with pytest.raises(ValueError, match="atr_h1_14 must be > 0"):
        compute_risk_reward(df, sweep_idx=6, direction="buy", zone_center=50.0, sweep_extreme=40.0, atr_h1_14=0.0)


def test_atr_negative_raises():
    df = make_df([10, 20, 30, 100, 30, 20, 10], [5, 15, 25, 95, 25, 15, 5])
    with pytest.raises(ValueError, match="atr_h1_14 must be > 0"):
        compute_risk_reward(df, sweep_idx=6, direction="buy", zone_center=50.0, sweep_extreme=40.0, atr_h1_14=-1.0)


def test_atr_nan_raises():
    df = make_df([10, 20, 30, 100, 30, 20, 10], [5, 15, 25, 95, 25, 15, 5])
    with pytest.raises(ValueError, match="atr_h1_14 must be a finite number"):
        compute_risk_reward(df, sweep_idx=6, direction="buy", zone_center=50.0, sweep_extreme=40.0, atr_h1_14=float("nan"))


def test_zone_center_nan_raises():
    df = make_df([10, 20, 30, 100, 30, 20, 10], [5, 15, 25, 95, 25, 15, 5])
    with pytest.raises(ValueError, match="zone_center must be a finite number"):
        compute_risk_reward(df, sweep_idx=6, direction="buy", zone_center=float("nan"), sweep_extreme=40.0, atr_h1_14=1.0)


def test_sweep_extreme_nan_raises():
    df = make_df([10, 20, 30, 100, 30, 20, 10], [5, 15, 25, 95, 25, 15, 5])
    with pytest.raises(ValueError, match="sweep_extreme must be a finite number"):
        compute_risk_reward(df, sweep_idx=6, direction="buy", zone_center=50.0, sweep_extreme=float("nan"), atr_h1_14=1.0)


def test_sweep_extreme_wrong_side_buy_raises():
    df = make_df([10, 20, 30, 100, 30, 20, 10], [5, 15, 25, 95, 25, 15, 5])
    # buy requires sweep_extreme < zone_center; here it's above
    with pytest.raises(ValueError, match="sweep_extreme must be < zone_center"):
        compute_risk_reward(df, sweep_idx=6, direction="buy", zone_center=50.0, sweep_extreme=60.0, atr_h1_14=1.0)


def test_sweep_extreme_wrong_side_sell_raises():
    df = make_df([10, 20, 30, 100, 30, 20, 10], [5, 15, 25, 95, 25, 15, 5])
    with pytest.raises(ValueError, match="sweep_extreme must be > zone_center"):
        compute_risk_reward(df, sweep_idx=6, direction="sell", zone_center=50.0, sweep_extreme=40.0, atr_h1_14=1.0)


def test_stop_wrong_side_raises_due_to_tick_rounding_collision():
    """Contrived case: sweep_extreme (1999.996) is strictly below
    zone_center (2000.00) as raw floats (passes the sweep-side check),
    but with a tiny atr (0.005 -> buffer 0.001) the computed stop
    (1999.995) rounds, via banker's rounding to the nearest tick, to the
    SAME tick as entry (200000 ticks = 2000.00) -- so stop_t >= entry_t
    for direction='buy', which must raise."""
    df = make_df([10, 20, 30, 100, 30, 20, 10], [5, 15, 25, 95, 25, 15, 5])
    with pytest.raises(ValueError, match="computed stop .* is not below entry"):
        compute_risk_reward(
            df, sweep_idx=6, direction="buy", zone_center=2000.0, sweep_extreme=1999.996, atr_h1_14=0.005
        )
