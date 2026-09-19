"""Integration tests for the Dao Gam V1 signal pipeline orchestrator.

Per docs/DAO_GAM_RULES.md and docs/DATA_SCHEMA.md. Exercises
src/engine/dao_gam_engine.py against the real fixtures (tests/fixtures/*)
and a handful of synthetic in-memory variations. Does not modify any
fixture file on disk.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.indicators.atr import atr as compute_atr  # noqa: E402
from src.engine.dao_gam_engine import evaluate_sweep_candidate, run_engine  # noqa: E402

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")


def load_h1(name):
    return pd.read_csv(os.path.join(FIXTURES_DIR, name, "h1.csv"))


def load_m15(name):
    path = os.path.join(FIXTURES_DIR, name, "m15.csv")
    if os.path.isfile(path):
        return pd.read_csv(path)
    return pd.DataFrame(columns=["timestamp", "symbol", "timeframe", "open", "high", "low", "close", "volume"])


def evaluate(name, sweep_idx=22, **kwargs):
    h1 = load_h1(name)
    m15 = load_m15(name)
    atr = compute_atr(h1, period=14)
    return evaluate_sweep_candidate(h1, m15, atr, sweep_idx, **kwargs)


# ---------------------------------------------------------------------------
# Per-fixture status/stage at sweep_idx=22
# ---------------------------------------------------------------------------


def test_fixture_01_needs_manual_review_full_numbers():
    r = evaluate("01_buy_valid")
    assert r.status == "NEEDS_MANUAL_REVIEW"
    assert r.stage == "filled"
    assert r.direction == "buy"
    assert r.zone_center == pytest.approx(2000.0)
    assert r.zone_low == pytest.approx(1999.50)
    assert r.zone_high == pytest.approx(2000.50)
    assert r.entry == pytest.approx(2000.0)
    assert r.stop == pytest.approx(1963.0)
    assert r.tp1 == pytest.approx(2070.0)
    assert r.tp2 == pytest.approx(2105.0)
    assert r.entry_state == "filled"
    assert r.fill_idx == 24
    assert r.stop_breached_in_activation_hour is False


def test_fixture_02_needs_manual_review_full_numbers():
    r = evaluate("02_sell_valid")
    assert r.status == "NEEDS_MANUAL_REVIEW"
    assert r.stage == "filled"
    assert r.direction == "sell"
    assert r.zone_center == pytest.approx(2000.0)
    assert r.zone_low == pytest.approx(1999.50)
    assert r.zone_high == pytest.approx(2000.50)
    assert r.entry == pytest.approx(2000.0)
    assert r.stop == pytest.approx(2037.0)
    assert r.tp1 == pytest.approx(1930.0)
    assert r.tp2 == pytest.approx(1895.0)
    assert r.entry_state == "filled"
    assert r.fill_idx == 24
    assert r.stop_breached_in_activation_hour is False


def test_fixture_03_rejected_m15_no_reaction():
    r = evaluate("03_no_m15_reaction")
    assert r.status == "REJECTED_M15_NO_REACTION"
    assert r.stage == "m15_no_reaction"


def test_fixture_04_expired():
    r = evaluate("04_expired_no_entry_touch")
    assert r.status == "EXPIRED"
    assert r.stage == "expired"


def test_fixture_05_rejected_rr_below_threshold():
    r = evaluate("05_rr_below_threshold")
    assert r.status == "REJECTED_RR_BELOW_THRESHOLD"
    assert r.stage == "rr_below_threshold"


def test_fixture_06_expired_same_bar_conflict():
    r = evaluate("06_same_bar_entry_sl_conflict")
    assert r.status == "EXPIRED"
    assert r.stage == "expired"


def test_fixture_07_no_trap_no_status():
    r = evaluate("07_real_breakout_no_close_back")
    assert r.stage == "no_trap"
    assert r.status is None


# ---------------------------------------------------------------------------
# stop_breached_in_activation_hour diagnostic (does not change status)
# ---------------------------------------------------------------------------


def test_stop_breach_diagnostic_true_status_still_needs_manual_review():
    """Synthetic variation of fixture 01: the first M15 candle of the
    reaction hour (23:00) is edited in memory so its low touches the stop
    level (1963.0). The reaction still fires on the 2nd candle (23:15,
    unchanged), risk/reward and entry simulation are unaffected (they
    only read H1 data), so status must remain NEEDS_MANUAL_REVIEW even
    though the diagnostic flag is now True."""
    h1 = load_h1("01_buy_valid")
    m15 = load_m15("01_buy_valid")
    m15 = m15.copy()
    mask = m15["timestamp"] == "2024-01-02T23:00:00Z"
    # original 23:00 row: open=2005 high=2008 low=2003 close=2004
    # lower the low to 1960 (<= stop 1963), keep it a small-body candle
    # so condition b) still fails and the reaction still fires on 23:15.
    m15.loc[mask, "low"] = 1960.0
    atr = compute_atr(h1, period=14)
    r = evaluate_sweep_candidate(h1, m15, atr, sweep_idx=22)

    assert r.status == "NEEDS_MANUAL_REVIEW"
    assert r.stop_breached_in_activation_hour is True


# ---------------------------------------------------------------------------
# Synthetic: zone merging (two anchors, same band, on fixture 01's base)
# ---------------------------------------------------------------------------


def test_zone_merging_two_anchors_same_band_merged_into_one():
    h1 = load_h1("01_buy_valid")
    m15 = load_m15("01_buy_valid")
    atr = compute_atr(h1, period=14)
    r = evaluate_sweep_candidate(h1, m15, atr, sweep_idx=22)
    # Fixture 01's support zone is anchored on idx 5 AND idx 17 (both
    # low=2000.00, same band) -- the engine must merge these into ONE
    # candidate zone, not two separate ones, before running detect_sweep.
    # We verify this indirectly: the winning zone_candidates list has
    # exactly one *support* entry (not two), and merged_rows == 2.
    support_candidates = [c for c in r.zone_candidates if c["zone"]["side"] == "support"]
    assert len(support_candidates) == 1
    assert support_candidates[0]["zone"]["merged_rows"] == 2
    assert sorted(support_candidates[0]["zone"]["touch_idxs"]) == [5, 17]
    assert r.merged_rows == 2


# ---------------------------------------------------------------------------
# Synthetic: two different zones both trap -> selection order
# ---------------------------------------------------------------------------


def test_zone_selection_prefers_highest_touch_count():
    """Two overlapping-band support zones both trap the same sweep
    candle: zone A (anchored at idx 3, 9 -> touch_count=2, center=100.0)
    and zone B (anchored at idx 15, 21, 27 -> touch_count=3,
    center=100.9). Bands (width 1.0) are [99.5,100.5] and [100.4,101.4],
    overlapping on [100.4,100.5]; the sweep candle closes at 100.42, which
    is numerically CLOSER to zone A's center (distance 0.42) than to zone
    B's (distance 0.48). Despite that, the engine must pick zone B,
    because touch_count is compared before the price-distance tie-break
    (per ZONE SELECTION in the module docstring)."""
    lows = [
        150, 140, 130, 100, 130, 140, 150, 140, 130, 100, 130, 140, 150, 140, 130,
        100.9, 130, 140, 150, 140, 130, 100.9, 130, 140, 150, 140, 130, 100.9, 130, 140, 150,
    ]
    highs = [l + 50 for l in lows]
    closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    h1 = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-02-01T00:00:00Z", periods=len(highs), freq="h").astype(str),
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
        }
    )
    sweep_row = pd.DataFrame(
        [
            {
                "timestamp": (pd.Timestamp("2024-02-01T00:00:00Z") + pd.Timedelta(hours=len(highs))).isoformat(),
                "open": 130.0,
                "high": 132.0,
                "low": 50.0,
                "close": 100.42,
            }
        ]
    )
    h1 = pd.concat([h1, sweep_row], ignore_index=True)
    atr = compute_atr(h1, period=14)
    sweep_idx = len(h1) - 1

    empty_m15 = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    r = evaluate_sweep_candidate(h1, empty_m15, atr, sweep_idx)

    # Both support zones (100.0, touch_count=2) and (100.9, touch_count=3)
    # must appear as trapped candidates in the log...
    trapped = {
        round(c["zone"]["zone_center"], 4): c["zone"]["touch_count"]
        for c in r.zone_candidates
        if c["sweep_result"].is_trap and c["zone"]["side"] == "support"
    }
    assert trapped == {100.0: 2, 100.9: 3}

    # ...but the winner is the higher-touch_count zone (100.9), even
    # though 100.0 is numerically closer to the sweep close (100.42).
    assert r.touch_count == 3
    assert r.zone_center == pytest.approx(100.9)


# ---------------------------------------------------------------------------
# Synthetic: activation bar missing -> "activation_bar_missing"
# ---------------------------------------------------------------------------


def test_activation_bar_missing_when_next_h1_row_dropped():
    h1 = load_h1("01_buy_valid")
    m15 = load_m15("01_buy_valid")
    # drop idx 23 (the activation bar) -- idx 24 shifts up to become the
    # new "idx 23" position, whose timestamp is no longer exactly +1h
    # after the sweep candle's timestamp.
    h1_dropped = h1.drop(index=23).reset_index(drop=True)
    atr = compute_atr(h1_dropped, period=14)
    r = evaluate_sweep_candidate(h1_dropped, m15, atr, sweep_idx=22)
    assert r.status is None
    assert r.stage == "activation_bar_missing"


def test_activation_bar_missing_when_h1_ends_at_sweep():
    h1 = load_h1("01_buy_valid").iloc[:23].reset_index(drop=True)  # ends exactly at sweep_idx=22
    m15 = load_m15("01_buy_valid")
    atr = compute_atr(h1, period=14)
    r = evaluate_sweep_candidate(h1, m15, atr, sweep_idx=22)
    assert r.status is None
    assert r.stage == "activation_bar_missing"


# ---------------------------------------------------------------------------
# Synthetic: M15 window incomplete
# ---------------------------------------------------------------------------


def test_m15_window_incomplete_when_reaction_hour_candles_missing():
    h1 = load_h1("01_buy_valid")
    m15 = load_m15("01_buy_valid")
    # drop all 4 candles of the reaction hour (23:00-23:45), leaving only
    # the sweep hour's own M15 breakdown.
    m15_dropped = m15[~m15["timestamp"].str.startswith("2024-01-02T23:")].reset_index(drop=True)
    atr = compute_atr(h1, period=14)
    r = evaluate_sweep_candidate(h1, m15_dropped, atr, sweep_idx=22)
    assert r.status is None
    assert r.stage == "m15_window_incomplete"


# ---------------------------------------------------------------------------
# Synthetic: tp1_unavailable
# ---------------------------------------------------------------------------


def test_tp1_unavailable_when_no_qualifying_swing():
    """Take fixture 01's base history but shrink the swing high at idx 11
    so it no longer exceeds entry (2000.00) -- with no other qualifying
    swing high above entry, compute_risk_reward must report
    tp1_unavailable, and the engine must surface stage="tp1_unavailable"
    with status=None (no new status invented)."""
    h1 = load_h1("01_buy_valid").copy()
    h1[["open", "high", "low", "close"]] = h1[["open", "high", "low", "close"]].astype(float)
    # original idx11: open=2060 high=2070 low=2060 close=2060
    h1.loc[11, ["open", "high", "low", "close"]] = [1985.0, 1990.0, 1980.0, 1985.0]  # now below entry(2000)
    m15 = load_m15("01_buy_valid")
    atr = compute_atr(h1, period=14)
    r = evaluate_sweep_candidate(h1, m15, atr, sweep_idx=22)
    assert r.status is None
    assert r.stage == "tp1_unavailable"
    assert r.tp1 is None
    assert r.entry == pytest.approx(2000.0)
    assert r.stop is not None and r.stop < r.entry  # stop still computed, just tp1 is missing


# ---------------------------------------------------------------------------
# atr_unavailable: sweep_idx = 0 and 1
# ---------------------------------------------------------------------------


def test_atr_unavailable_sweep_idx_0():
    h1 = load_h1("01_buy_valid")
    m15 = load_m15("01_buy_valid")
    atr = compute_atr(h1, period=14)
    r = evaluate_sweep_candidate(h1, m15, atr, sweep_idx=0)
    assert r.status is None
    assert r.stage == "atr_unavailable"


def test_atr_unavailable_sweep_idx_1():
    h1 = load_h1("01_buy_valid")
    m15 = load_m15("01_buy_valid")
    atr = compute_atr(h1, period=14)
    assert pd.isna(atr.iloc[0])  # ATR(14) not defined until idx 13
    r = evaluate_sweep_candidate(h1, m15, atr, sweep_idx=1)
    assert r.status is None
    assert r.stage == "atr_unavailable"


# ---------------------------------------------------------------------------
# run_engine over full fixtures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected_status",
    [
        ("01_buy_valid", "NEEDS_MANUAL_REVIEW"),
        ("02_sell_valid", "NEEDS_MANUAL_REVIEW"),
        ("03_no_m15_reaction", "REJECTED_M15_NO_REACTION"),
        ("04_expired_no_entry_touch", "EXPIRED"),
        ("05_rr_below_threshold", "REJECTED_RR_BELOW_THRESHOLD"),
        ("06_same_bar_entry_sl_conflict", "EXPIRED"),
    ],
)
def test_run_engine_exactly_one_result_per_fixture(name, expected_status):
    h1 = load_h1(name)
    m15 = load_m15(name)
    results = run_engine(h1, m15)
    assert len(results) == 1
    assert results[0].sweep_idx == 22
    assert results[0].status == expected_status


def test_run_engine_zero_results_for_fixture_07():
    h1 = load_h1("07_real_breakout_no_close_back")
    m15 = load_m15("07_real_breakout_no_close_back")
    results = run_engine(h1, m15)
    assert results == []


def test_run_engine_include_no_signal_returns_more_rows():
    h1 = load_h1("07_real_breakout_no_close_back")
    m15 = load_m15("07_real_breakout_no_close_back")
    results = run_engine(h1, m15, include_no_signal=True)
    assert len(results) == len(h1)
    assert all(r.status is None for r in results)


# ---------------------------------------------------------------------------
# Look-ahead
# ---------------------------------------------------------------------------


def test_no_lookahead_h1_after_sweep_plus_2_and_m15_after_2h_do_not_affect_result():
    h1 = load_h1("01_buy_valid")
    m15 = load_m15("01_buy_valid")
    atr = compute_atr(h1, period=14)

    result_before = evaluate_sweep_candidate(h1, m15, atr, sweep_idx=22)

    # fixture 01's h1.csv ends exactly at idx 24 (sweep_idx+2), so there
    # is nothing to mutate past it on H1; extend with 2 more rows to
    # prove they truly aren't read.
    h1_mutated = h1.copy()
    h1_mutated[["open", "high", "low", "close"]] = h1_mutated[["open", "high", "low", "close"]].astype(float)
    extra_h1 = pd.DataFrame(
        [
            {
                "timestamp": "2024-01-03T01:00:00Z",
                "symbol": "XAUUSD",
                "timeframe": "H1",
                "open": np.nan,
                "high": np.nan,
                "low": np.nan,
                "close": np.nan,
                "volume": 0,
            },
            {
                "timestamp": "2024-01-03T02:00:00Z",
                "symbol": "XAUUSD",
                "timeframe": "H1",
                "open": -999.0,
                "high": -998.0,
                "low": -1000.0,
                "close": -999.0,
                "volume": 0,
            },
        ]
    )
    h1_mutated = pd.concat([h1_mutated, extra_h1], ignore_index=True)
    atr_mutated = compute_atr(h1.copy(), period=14)  # unaffected rows only, same as before at idx<=21

    m15_mutated = m15.copy()
    extra_m15 = pd.DataFrame(
        [
            {
                "timestamp": "2024-01-03T00:00:00Z",  # sweep_ts(22:00) + 2h -- must be ignored
                "symbol": "XAUUSD",
                "timeframe": "M15",
                "open": np.nan,
                "high": np.nan,
                "low": np.nan,
                "close": np.nan,
                "volume": 0,
            }
        ]
    )
    m15_mutated = pd.concat([m15_mutated, extra_m15], ignore_index=True)

    result_after = evaluate_sweep_candidate(h1_mutated, m15_mutated, atr_mutated, sweep_idx=22)

    assert result_before.status == result_after.status
    assert result_before.stage == result_after.stage
    assert result_before.entry_state == result_after.entry_state
    assert result_before.fill_idx == result_after.fill_idx
    assert result_before.entry == result_after.entry
    assert result_before.stop == result_after.stop
    assert result_before.tp1 == result_after.tp1
    assert result_before.tp2 == result_after.tp2


def test_truncated_data_at_lookahead_boundary_matches_full_data():
    h1 = load_h1("01_buy_valid")  # ends exactly at idx 24 = sweep_idx+2
    m15 = load_m15("01_buy_valid")
    atr_full = compute_atr(h1, period=14)
    result_full = evaluate_sweep_candidate(h1, m15, atr_full, sweep_idx=22)

    # truncate M15 to end exactly at sweep_ts+2h (exclusive boundary is
    # already respected by check_m15_reaction; here we just drop rows
    # that don't exist beyond the reaction hour anyway in this fixture).
    m15_truncated = m15[m15["timestamp"] < "2024-01-03T00:00:00Z"].reset_index(drop=True)
    result_truncated = evaluate_sweep_candidate(h1, m15_truncated, atr_full, sweep_idx=22)

    assert result_full.status == result_truncated.status
    assert result_full.stage == result_truncated.stage
    assert result_full.entry == result_truncated.entry
    assert result_full.stop == result_truncated.stop
    assert result_full.fill_idx == result_truncated.fill_idx
