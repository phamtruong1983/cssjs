"""Integration tests for the Dao Gam V1 signal pipeline orchestrator.

Per docs/DAO_GAM_RULES.md and docs/DATA_SCHEMA.md. Exercises
src/engine/dao_gam_engine.py against the real fixtures (tests/fixtures/*)
and a handful of synthetic in-memory variations. Does not modify any
fixture file on disk.
"""
import dataclasses
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.indicators.atr import atr as compute_atr  # noqa: E402
from src.engine.dao_gam_engine import (  # noqa: E402
    annotate_repeats,
    evaluate_sweep_candidate,
    run_engine,
    zone_width_from_atr,
)

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


@pytest.mark.parametrize("zone_width_atr", [None, 0.10])
def test_no_lookahead_h1_after_sweep_plus_3_and_m15_after_2h_do_not_affect_result(zone_width_atr):
    h1 = load_h1("01_buy_valid")
    m15 = load_m15("01_buy_valid")
    atr = compute_atr(h1, period=14)

    result_before = evaluate_sweep_candidate(h1, m15, atr, sweep_idx=22, zone_width_atr=zone_width_atr)

    # fixture 01's h1.csv ends exactly at idx 24 (this fixture only has 1
    # window candle, so it never reaches idx 25 = sweep_idx+3 anyway); the
    # general no-look-ahead boundary the engine promises is sweep_idx+3
    # (see module docstring), so we extend with 2 more rows to prove
    # rows past the actual data end truly aren't read.
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

    result_after = evaluate_sweep_candidate(
        h1_mutated, m15_mutated, atr_mutated, sweep_idx=22, zone_width_atr=zone_width_atr
    )

    assert result_before.status == result_after.status
    assert result_before.stage == result_after.stage
    assert result_before.entry_state == result_after.entry_state
    assert result_before.fill_idx == result_after.fill_idx
    assert result_before.entry == result_after.entry
    assert result_before.stop == result_after.stop
    assert result_before.tp1 == result_after.tp1
    assert result_before.tp2 == result_after.tp2


def test_fixture_04_exact_boundary_sweep_plus_3_is_actually_read():
    """Companion to the no-look-ahead test above: mutating H1 row idx 25
    (= sweep_idx+3, the LAST row of the entry-validity window) so it
    touches entry must flip the result from EXPIRED/no_touch to
    NEEDS_MANUAL_REVIEW/filled -- proving idx 25 really is read, not just
    that rows beyond it are ignored."""
    h1 = load_h1("04_expired_no_entry_touch")
    m15 = load_m15("04_expired_no_entry_touch")

    atr_before = compute_atr(h1, period=14)
    result_before = evaluate_sweep_candidate(h1, m15, atr_before, sweep_idx=22)
    assert result_before.status == "EXPIRED"
    assert result_before.stage == "expired"

    h1_mutated = h1.copy()
    h1_mutated[["open", "high", "low", "close"]] = h1_mutated[["open", "high", "low", "close"]].astype(float)
    h1_mutated.loc[25, "low"] = 2000.0  # idx 25 = sweep_idx+3 now touches entry(2000.0)
    atr_mutated = compute_atr(h1_mutated, period=14)
    result_after = evaluate_sweep_candidate(h1_mutated, m15, atr_mutated, sweep_idx=22)

    assert result_after.status == "NEEDS_MANUAL_REVIEW"
    assert result_after.stage == "filled"
    assert result_after.fill_idx == 25


# ---------------------------------------------------------------------------
# range_prefilter: True vs False must give identical status/stage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "01_buy_valid",
        "02_sell_valid",
        "03_no_m15_reaction",
        "04_expired_no_entry_touch",
        "05_rr_below_threshold",
        "06_same_bar_entry_sl_conflict",
        "07_real_breakout_no_close_back",
    ],
)
def test_range_prefilter_true_vs_false_identical_for_fixtures(name):
    h1 = load_h1(name)
    m15 = load_m15(name)
    atr = compute_atr(h1, period=14)
    for sweep_idx in range(len(h1)):
        if sweep_idx < 1 or pd.isna(atr.iloc[sweep_idx - 1]):
            continue
        r_on = evaluate_sweep_candidate(h1, m15, atr, sweep_idx, range_prefilter=True)
        r_off = evaluate_sweep_candidate(h1, m15, atr, sweep_idx, range_prefilter=False)
        if r_on.status is None and r_off.status is None:
            continue
        assert r_on.status == r_off.status, sweep_idx
        assert r_on.stage == r_off.stage, sweep_idx


def test_range_prefilter_true_vs_false_identical_for_synthetic_run_engine():
    h1 = load_h1("01_buy_valid")
    m15 = load_m15("01_buy_valid")
    results_on = run_engine(h1, m15, include_no_signal=True, range_prefilter=True)
    results_off = run_engine(h1, m15, include_no_signal=True, range_prefilter=False)
    assert len(results_on) == len(results_off)
    for r_on, r_off in zip(results_on, results_off):
        assert r_on.status == r_off.status
        assert r_on.stage == r_off.stage


# ---------------------------------------------------------------------------
# activation_bar_missing: sweep-side numeric fields must still be populated
# ---------------------------------------------------------------------------


def test_activation_bar_missing_still_populates_sweep_numeric_fields():
    h1 = load_h1("01_buy_valid").iloc[:23].reset_index(drop=True)  # ends exactly at sweep_idx=22
    m15 = load_m15("01_buy_valid")
    atr = compute_atr(h1, period=14)
    r = evaluate_sweep_candidate(h1, m15, atr, sweep_idx=22)
    assert r.stage == "activation_bar_missing"
    assert r.status is None
    assert r.atr_h1_14 is not None
    assert r.h1_range is not None
    assert r.range_multiple is not None
    assert r.pierce_depth is not None
    assert r.sweep_extreme is not None


def test_activation_bar_missing_wrong_gap_still_populates_sweep_numeric_fields():
    h1 = load_h1("01_buy_valid")
    m15 = load_m15("01_buy_valid")
    h1_dropped = h1.drop(index=23).reset_index(drop=True)
    atr = compute_atr(h1_dropped, period=14)
    r = evaluate_sweep_candidate(h1_dropped, m15, atr, sweep_idx=22)
    assert r.stage == "activation_bar_missing"
    assert r.status is None
    assert r.atr_h1_14 is not None
    assert r.h1_range is not None
    assert r.range_multiple is not None
    assert r.pierce_depth is not None
    assert r.sweep_extreme is not None


# ---------------------------------------------------------------------------
# Zone selection: touch_count tie (distance decides), then anchor_idx tie
# ---------------------------------------------------------------------------


def _build_two_support_zones_h1(sweep_close: float) -> pd.DataFrame:
    """Two same-touch_count (2) support zones: A anchored idx3/9 at
    99.58 (band [99.08,100.08]), B anchored idx15/21 at 100.42 (band
    [99.92,100.92]); their bands overlap on [99.92,100.08], so a sweep
    candle closing in that overlap can trap both simultaneously."""
    lows = [
        150, 140, 130, 99.58, 130, 140, 150, 140, 130, 99.58, 130, 140, 150, 140, 130,
        100.42, 130, 140, 150, 140, 130, 100.42, 130, 140, 150, 140, 130, 130, 140, 150,
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
                "close": sweep_close,
            }
        ]
    )
    return pd.concat([h1, sweep_row], ignore_index=True)


def test_zone_selection_touch_count_tie_prefers_closer_zone():
    # sweep close 99.93 is closer to zone A's center (99.58, dist 0.35)
    # than zone B's (100.42, dist 0.49); both have touch_count=2.
    h1 = _build_two_support_zones_h1(99.93)
    atr = compute_atr(h1, period=14)
    sweep_idx = len(h1) - 1
    empty_m15 = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    r = evaluate_sweep_candidate(h1, empty_m15, atr, sweep_idx)

    trapped = {
        round(c["zone"]["zone_center"], 4): c["zone"]["touch_count"]
        for c in r.zone_candidates
        if c["sweep_result"].is_trap and c["zone"]["side"] == "support"
    }
    assert trapped == {99.58: 2, 100.42: 2}
    assert r.zone_center == pytest.approx(99.58)


def test_zone_selection_touch_count_and_distance_tie_prefers_larger_anchor_idx():
    # sweep close 100.0 is exactly equidistant (0.42) from both zone
    # centers (99.58 and 100.42), both touch_count=2 -> the tie-break
    # falls to the larger anchor_idx: zone B (anchor_idx=15) beats zone A
    # (anchor_idx=3).
    h1 = _build_two_support_zones_h1(100.0)
    atr = compute_atr(h1, period=14)
    sweep_idx = len(h1) - 1
    empty_m15 = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close"])
    r = evaluate_sweep_candidate(h1, empty_m15, atr, sweep_idx)

    trapped = {
        round(c["zone"]["zone_center"], 4): c["zone"]["touch_count"]
        for c in r.zone_candidates
        if c["sweep_result"].is_trap and c["zone"]["side"] == "support"
    }
    assert trapped == {99.58: 2, 100.42: 2}
    assert r.zone_center == pytest.approx(100.42)


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


# ---------------------------------------------------------------------------
# Module 8b -- D1: zone_width_atr
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "01_buy_valid",
        "02_sell_valid",
        "03_no_m15_reaction",
        "04_expired_no_entry_touch",
        "05_rr_below_threshold",
        "06_same_bar_entry_sl_conflict",
        "07_real_breakout_no_close_back",
    ],
)
def test_zone_width_atr_matches_default_when_atr_is_10(name):
    # Every fixture's base history has atr_h1_14 == 10.00 exactly at
    # sweep_idx=22, so zone_width_atr=0.10 -> effective width
    # 0.10*10.00 == 1.00, identical to the default absolute width.
    r_default = evaluate(name)
    r_atr = evaluate(name, zone_width_atr=0.10)

    assert r_atr.status == r_default.status
    assert r_atr.stage == r_default.stage
    assert r_atr.zone_low == r_default.zone_low
    assert r_atr.zone_high == r_default.zone_high
    assert r_atr.entry == r_default.entry
    assert r_atr.stop == r_default.stop
    assert r_atr.tp1 == r_default.tp1
    assert r_atr.tp2 == r_default.tp2
    assert r_atr.entry_state == r_default.entry_state
    assert r_atr.fill_idx == r_default.fill_idx

    assert r_atr.zone_width_used == pytest.approx(1.0)
    assert r_atr.zone_width_mode == "atr"
    assert r_default.zone_width_mode == "absolute"


def _scale_h1_m15(h1, m15, k):
    h1_scaled = h1.copy()
    h1_scaled[["open", "high", "low", "close"]] = h1_scaled[["open", "high", "low", "close"]].astype(float) * k
    m15_scaled = m15.copy()
    if not m15_scaled.empty:
        m15_scaled[["open", "high", "low", "close"]] = (
            m15_scaled[["open", "high", "low", "close"]].astype(float) * k
        )
    return h1_scaled, m15_scaled


@pytest.mark.parametrize("k", [2, 3])
def test_zone_width_atr_scale_invariant(k):
    h1 = load_h1("01_buy_valid")
    m15 = load_m15("01_buy_valid")
    r_base = evaluate_sweep_candidate(h1, m15, compute_atr(h1, period=14), sweep_idx=22, zone_width_atr=0.10)

    h1_scaled, m15_scaled = _scale_h1_m15(h1, m15, k)
    atr_scaled = compute_atr(h1_scaled, period=14)
    r_scaled = evaluate_sweep_candidate(h1_scaled, m15_scaled, atr_scaled, sweep_idx=22, zone_width_atr=0.10)

    assert r_scaled.status == r_base.status
    assert r_scaled.stage == r_base.stage
    assert r_scaled.entry_state == r_base.entry_state
    assert r_scaled.touch_idxs == r_base.touch_idxs

    assert r_scaled.zone_width_used == pytest.approx(r_base.zone_width_used * k)
    assert r_scaled.entry == pytest.approx(r_base.entry * k)
    assert r_scaled.stop == pytest.approx(r_base.stop * k, rel=1e-3)
    assert r_scaled.tp1 == pytest.approx(r_base.tp1 * k)
    assert r_scaled.tp2 == pytest.approx(r_base.tp2 * k, rel=1e-3)


@pytest.mark.parametrize("bad_value", [0, -1.0, float("nan"), float("inf"), True, "0.10"])
def test_zone_width_atr_invalid_raises(bad_value):
    with pytest.raises((TypeError, ValueError)):
        evaluate("01_buy_valid", zone_width_atr=bad_value)


@pytest.mark.parametrize(
    "name,expected_count",
    [
        ("01_buy_valid", 1),
        ("02_sell_valid", 1),
        ("03_no_m15_reaction", 1),
        ("04_expired_no_entry_touch", 1),
        ("05_rr_below_threshold", 1),
        ("06_same_bar_entry_sl_conflict", 1),
        ("07_real_breakout_no_close_back", 0),
    ],
)
def test_run_engine_zone_width_atr_matches_default_result_counts(name, expected_count):
    h1 = load_h1(name)
    m15 = load_m15(name)
    results = run_engine(h1, m15, zone_width_atr=0.10)
    assert len(results) == expected_count


# ---------------------------------------------------------------------------
# Module 8b -- D2: annotate_repeats
# ---------------------------------------------------------------------------


def _make_result(sweep_ts, direction, zone_center, status="NEEDS_MANUAL_REVIEW"):
    base = evaluate("01_buy_valid")  # a real, fully-populated EngineResult to clone
    return dataclasses.replace(
        base,
        sweep_ts=pd.Timestamp(sweep_ts, tz="UTC"),
        direction=direction,
        zone_center=zone_center,
        status=status,
    )


def test_annotate_repeats_exact_24h_boundary_is_true():
    r1 = _make_result("2024-01-01T00:00:00Z", "buy", 2000.0)
    r2 = _make_result("2024-01-02T00:00:00Z", "buy", 2000.0)  # exactly 24h later
    out = annotate_repeats([r1, r2])
    assert out[0].repeat_zone_within_24h is False
    assert out[1].repeat_zone_within_24h is True
    assert out[1].repeat_zone_within_72h is True


def test_annotate_repeats_24h_plus_1min_is_false_for_24h_true_for_72h():
    r1 = _make_result("2024-01-01T00:00:00Z", "buy", 2000.0)
    r2 = _make_result("2024-01-02T00:01:00Z", "buy", 2000.0)  # 24h1m later
    out = annotate_repeats([r1, r2])
    assert out[1].repeat_zone_within_24h is False
    assert out[1].repeat_zone_within_72h is True


def test_annotate_repeats_different_direction_is_false():
    r1 = _make_result("2024-01-01T00:00:00Z", "buy", 2000.0)
    r2 = _make_result("2024-01-01T12:00:00Z", "sell", 2000.0)
    out = annotate_repeats([r1, r2])
    assert out[1].repeat_zone_within_24h is False
    assert out[1].repeat_zone_within_72h is False


def test_annotate_repeats_different_zone_center_by_one_tick_is_false():
    r1 = _make_result("2024-01-01T00:00:00Z", "buy", 2000.00)
    r2 = _make_result("2024-01-01T12:00:00Z", "buy", 2000.01)
    out = annotate_repeats([r1, r2])
    assert out[1].repeat_zone_within_24h is False
    assert out[1].repeat_zone_within_72h is False


def test_annotate_repeats_first_result_is_false():
    r1 = _make_result("2024-01-01T00:00:00Z", "buy", 2000.0)
    out = annotate_repeats([r1])
    assert out[0].repeat_zone_within_24h is False
    assert out[0].repeat_zone_within_72h is False


def test_annotate_repeats_status_none_gives_none_flags():
    r1 = _make_result("2024-01-01T00:00:00Z", "buy", 2000.0, status=None)
    out = annotate_repeats([r1])
    assert out[0].repeat_zone_within_24h is None
    assert out[0].repeat_zone_within_72h is None


def test_annotate_repeats_later_result_does_not_affect_earlier_result_flags():
    r1 = _make_result("2024-01-01T00:00:00Z", "buy", 2000.0)
    r2 = _make_result("2024-01-01T12:00:00Z", "buy", 2000.0)
    out = annotate_repeats([r1, r2])
    assert out[0].repeat_zone_within_24h is False
    assert out[0].repeat_zone_within_72h is False


def test_annotate_repeats_unordered_input_gives_correct_flags_and_preserves_order():
    r_early = _make_result("2024-01-01T00:00:00Z", "buy", 2000.0)
    r_late = _make_result("2024-01-01T12:00:00Z", "buy", 2000.0)
    # pass the LATE one first -- input order is deliberately not sorted
    out = annotate_repeats([r_late, r_early])
    # output preserves input order: out[0] is r_late, out[1] is r_early
    assert out[0].sweep_ts == r_late.sweep_ts
    assert out[1].sweep_ts == r_early.sweep_ts
    assert out[0].repeat_zone_within_24h is True  # r_late comes after r_early chronologically
    assert out[1].repeat_zone_within_24h is False  # r_early has nothing before it

    # original list must not be mutated
    assert r_late.repeat_zone_within_24h is None
    assert r_early.repeat_zone_within_24h is None


# ---------------------------------------------------------------------------
# Module 8b -- D3: window_max_gap_hours / window_spans_weekend
# ---------------------------------------------------------------------------


def test_window_gap_fixture_01_one_hour_no_weekend():
    r = evaluate("01_buy_valid")
    assert r.window_max_gap_hours == pytest.approx(1.0)
    assert r.window_spans_weekend is False


def test_window_gap_fixture_04_one_hour_no_weekend():
    r = evaluate("04_expired_no_entry_touch")
    assert r.window_max_gap_hours == pytest.approx(1.0)
    assert r.window_spans_weekend is False
    assert r.status == "EXPIRED"


def test_window_gap_fixture_04_shifted_48h_spans_weekend():
    h1 = load_h1("04_expired_no_entry_touch")
    m15 = load_m15("04_expired_no_entry_touch")
    h1_shifted = h1.copy()
    ts = pd.to_datetime(h1_shifted["timestamp"], utc=True)
    ts.iloc[24:] = ts.iloc[24:] + pd.Timedelta(hours=48)
    h1_shifted["timestamp"] = ts.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    atr = compute_atr(h1_shifted, period=14)

    r = evaluate_sweep_candidate(h1_shifted, m15, atr, sweep_idx=22)
    assert r.window_max_gap_hours == pytest.approx(49.0)
    assert r.window_spans_weekend is True
    assert r.status == "EXPIRED"


def test_window_gap_fixture_04_shifted_1h_no_weekend():
    h1 = load_h1("04_expired_no_entry_touch")
    m15 = load_m15("04_expired_no_entry_touch")
    h1_shifted = h1.copy()
    ts = pd.to_datetime(h1_shifted["timestamp"], utc=True)
    ts.iloc[24:] = ts.iloc[24:] + pd.Timedelta(hours=1)
    h1_shifted["timestamp"] = ts.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    atr = compute_atr(h1_shifted, period=14)

    r = evaluate_sweep_candidate(h1_shifted, m15, atr, sweep_idx=22)
    assert r.window_max_gap_hours == pytest.approx(2.0)
    assert r.window_spans_weekend is False


# ---------------------------------------------------------------------------
# Module 8b -- D4: stop_breached_in_activation_hour still present
# ---------------------------------------------------------------------------


def test_d4_stop_breach_field_present_via_run_engine():
    h1 = load_h1("01_buy_valid")
    m15 = load_m15("01_buy_valid")
    results = run_engine(h1, m15)
    assert len(results) == 1
    assert results[0].stop_breached_in_activation_hour is False


# ---------------------------------------------------------------------------
# Module 8b -- zone_width_from_atr (even-tick ATR-relative zone width)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "zone_width_atr,atr_prev,expected",
    [
        (0.10, 10.0, 1.00),
        (0.10, 6.9, 0.70),  # 0.69 sits between 0.68/0.70 -> round-half-up
        (0.10, 6.8, 0.68),
        (0.10, 0.05, 0.02),  # floor of 2 ticks (1 half-tick)
        (0.20, 2.63465, 0.52),  # 0.52693/0.02 = 26.35 -> rounds to 26
    ],
)
def test_zone_width_from_atr_hand_computed(zone_width_atr, atr_prev, expected):
    assert zone_width_from_atr(zone_width_atr, atr_prev) == pytest.approx(expected)


@pytest.mark.parametrize("seed", list(range(50)))
def test_zone_width_from_atr_always_even_tick_multiple(seed):
    rng = np.random.default_rng(seed)
    zone_width_atr = float(rng.uniform(0.01, 2.0))
    atr_prev = float(rng.uniform(0.001, 200.0))
    width = zone_width_from_atr(zone_width_atr, atr_prev)
    ticks = width / 0.02
    assert ticks == pytest.approx(round(ticks)), (zone_width_atr, atr_prev, width)
    assert width >= 0.02 - 1e-9


@pytest.mark.parametrize("k", [2, 3])
def test_zone_width_from_atr_scale_invariant_via_fixture_01(k):
    h1 = load_h1("01_buy_valid")
    m15 = load_m15("01_buy_valid")
    r_base = evaluate_sweep_candidate(h1, m15, compute_atr(h1, period=14), sweep_idx=22, zone_width_atr=0.10)

    h1_scaled, m15_scaled = _scale_h1_m15(h1, m15, k)
    atr_scaled = compute_atr(h1_scaled, period=14)
    r_scaled = evaluate_sweep_candidate(h1_scaled, m15_scaled, atr_scaled, sweep_idx=22, zone_width_atr=0.10)

    assert r_scaled.status == r_base.status
    assert r_scaled.stage == r_base.stage
    assert r_scaled.zone_width_used == pytest.approx(r_base.zone_width_used * k)
