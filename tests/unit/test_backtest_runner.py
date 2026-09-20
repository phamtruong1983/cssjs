"""Tests for the fixed-grid backtest runner (src/backtest/backtest_runner.py).

Synthetic, hand-computed data only for the statistics tests (b) uses
run_engine + trade_simulator on the real fixture CSVs, per the task spec.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.backtest.backtest_runner import (  # noqa: E402
    Trade,
    apply_spread,
    build_trades,
    multi_trap_stats,
    select_trades,
    summarize,
    summarize_by,
)
from src.engine.dao_gam_engine import run_engine  # noqa: E402

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")


def load_h1(name):
    return pd.read_csv(os.path.join(FIXTURES_DIR, name, "h1.csv"))


def load_m15(name):
    path = os.path.join(FIXTURES_DIR, name, "m15.csv")
    if os.path.isfile(path):
        return pd.read_csv(path)
    return pd.DataFrame(columns=["timestamp", "symbol", "timeframe", "open", "high", "low", "close", "volume"])


def make_trade(
    r_gross,
    exit_idx,
    fill_idx=0,
    outcome="win",
    risk_price=1.0,
    both_touched=False,
    gap_through_stop=False,
    repeat_zone_within_24h=False,
    direction="buy",
    sweep_ts=None,
    bars_held=None,
):
    if bars_held is None:
        bars_held = (exit_idx - fill_idx) if exit_idx is not None else None
    return Trade(
        config="test",
        variant="TP1",
        sweep_idx=fill_idx,
        sweep_ts=sweep_ts,
        direction=direction,
        fill_idx=fill_idx,
        entry=100.0,
        stop=99.0,
        target=101.0,
        outcome=outcome,
        exit_idx=exit_idx,
        r_gross=r_gross,
        bars_held=bars_held,
        bars_evaluated=bars_held or 0,
        both_touched=both_touched,
        gap_through_stop=gap_through_stop,
        risk_price=risk_price,
        repeat_zone_within_24h=repeat_zone_within_24h,
    )


# ---------------------------------------------------------------------------
# (a) summarize on r_gross = [+2, -1, +3, -1, -1], exit_idx 1..5
# ---------------------------------------------------------------------------


def test_summarize_hand_computed_basic_stats():
    trades = [
        make_trade(2, exit_idx=1, outcome="win"),
        make_trade(-1, exit_idx=2, outcome="loss"),
        make_trade(3, exit_idx=3, outcome="win"),
        make_trade(-1, exit_idx=4, outcome="loss"),
        make_trade(-1, exit_idx=5, outcome="loss"),
    ]
    s = summarize(trades, spread=0)
    assert s["n_closed"] == 5
    assert s["n_win"] == 2
    assert s["n_loss"] == 3
    assert s["win_rate"] == pytest.approx(0.4)
    assert s["mean_r"] == pytest.approx(0.4)
    assert s["median_r"] == pytest.approx(-1.0)
    assert s["total_r"] == pytest.approx(2.0)
    assert s["profit_factor"] == pytest.approx(5 / 3)
    assert s["max_drawdown_r"] == pytest.approx(2.0)
    assert s["avg_win_r"] == pytest.approx(2.5)
    assert s["breakeven_win_rate"] == pytest.approx(1 / 3.5)


# ---------------------------------------------------------------------------
# (b) select_trades modes
# ---------------------------------------------------------------------------


def test_select_trades_one_at_a_time():
    A = make_trade(1, exit_idx=15, fill_idx=10)
    B = make_trade(1, exit_idx=20, fill_idx=12)
    C = make_trade(1, exit_idx=18, fill_idx=15)
    D = make_trade(1, exit_idx=30, fill_idx=16)
    E = make_trade(1, exit_idx=22, fill_idx=20)
    F = make_trade(1, exit_idx=None, fill_idx=40, outcome="open_at_end")
    G = make_trade(1, exit_idx=55, fill_idx=50)

    trades = [A, B, C, D, E, F, G]
    selected = select_trades(trades, "one_at_a_time")
    assert selected == [A, D, F]


def test_select_trades_no_repeat24h():
    A = make_trade(1, exit_idx=15, fill_idx=10, repeat_zone_within_24h=False)
    B = make_trade(1, exit_idx=20, fill_idx=12, repeat_zone_within_24h=True)
    C = make_trade(1, exit_idx=18, fill_idx=15, repeat_zone_within_24h=False)
    selected = select_trades([A, B, C], "no_repeat24h")
    assert selected == [A, C]


def test_select_trades_independent_keeps_all():
    trades = [
        make_trade(1, exit_idx=15, fill_idx=10),
        make_trade(1, exit_idx=20, fill_idx=12),
        make_trade(1, exit_idx=18, fill_idx=15),
        make_trade(1, exit_idx=30, fill_idx=16),
        make_trade(1, exit_idx=22, fill_idx=20),
        make_trade(1, exit_idx=None, fill_idx=40, outcome="open_at_end"),
        make_trade(1, exit_idx=55, fill_idx=50),
    ]
    assert select_trades(trades, "independent") == trades


def test_select_trades_invalid_mode_raises():
    with pytest.raises(ValueError, match="mode must be one of"):
        select_trades([], "bogus")


# ---------------------------------------------------------------------------
# (c) apply_spread
# ---------------------------------------------------------------------------


def test_apply_spread_win_and_loss():
    win = make_trade(2.0, exit_idx=1, outcome="win", risk_price=4.0)
    loss = make_trade(-1.0, exit_idx=2, outcome="loss", risk_price=4.0)
    r_net = apply_spread([win, loss], spread=0.20)
    assert r_net[0] == pytest.approx(2.0 - 0.20 / 4.0)
    assert r_net[0] == pytest.approx(1.95)
    assert r_net[1] == pytest.approx(-1.0 - 0.20 / 4.0)
    assert r_net[1] == pytest.approx(-1.05)


def test_apply_spread_zero_spread_unchanged():
    win = make_trade(2.0, exit_idx=1, outcome="win", risk_price=4.0)
    r_net = apply_spread([win], spread=0)
    assert r_net[0] == pytest.approx(2.0)


def test_apply_spread_open_at_end_has_no_r():
    t = make_trade(None, exit_idx=None, outcome="open_at_end")
    r_net = apply_spread([t], spread=0.20)
    assert r_net[0] is None


# ---------------------------------------------------------------------------
# (d) Bootstrap CI: deterministic, degenerate case, n_closed < 5 -> None
# ---------------------------------------------------------------------------


def test_bootstrap_ci_deterministic_same_seed():
    trades = [make_trade(v, exit_idx=i, outcome=("win" if v > 0 else "loss")) for i, v in enumerate([1, -1, 2, -1, 1, -2], start=1)]
    s1 = summarize(trades, spread=0)
    s2 = summarize(trades, spread=0)
    assert s1["mean_r_ci95"] == s2["mean_r_ci95"]
    assert s1["mean_r_ci95"] is not None


def test_bootstrap_ci_degenerate_all_equal_collapses_to_that_value():
    trades = [make_trade(1.0, exit_idx=i, outcome="win") for i in range(1, 6)]
    s = summarize(trades, spread=0)
    lo, hi = s["mean_r_ci95"]
    assert lo == pytest.approx(1.0)
    assert hi == pytest.approx(1.0)


def test_bootstrap_ci_none_when_fewer_than_5_closed():
    trades = [make_trade(1.0, exit_idx=i, outcome="win") for i in range(1, 5)]  # 4 closed
    s = summarize(trades, spread=0)
    assert s["n_closed"] == 4
    assert s["mean_r_ci95"] is None


# ---------------------------------------------------------------------------
# (e) profit_factor / win_rate None cases
# ---------------------------------------------------------------------------


def test_profit_factor_none_when_no_losses():
    trades = [make_trade(1.0, exit_idx=1, outcome="win"), make_trade(2.0, exit_idx=2, outcome="win")]
    s = summarize(trades, spread=0)
    assert s["profit_factor"] is None


def test_win_rate_none_when_no_closed_trades():
    trades = [make_trade(None, exit_idx=None, outcome="open_at_end")]
    s = summarize(trades, spread=0)
    assert s["win_rate"] is None
    assert s["n_closed"] == 0
    assert s["mean_r"] is None
    assert s["max_drawdown_r"] is None
    assert s["profit_factor"] is None


# ---------------------------------------------------------------------------
# (f) build_trades on real fixtures 01-07 via run_engine
# ---------------------------------------------------------------------------


def test_build_trades_fixtures_01_to_07():
    h1_01 = load_h1("01_buy_valid")
    results_01 = run_engine(h1_01, load_m15("01_buy_valid"), include_no_signal=True)
    trades_01_tp1 = build_trades(h1_01, results_01, "TP1", "test")
    assert len(trades_01_tp1) == 1
    t = trades_01_tp1[0]
    assert t.target == pytest.approx(2070.0)
    assert t.outcome == "open_at_end"
    assert t.bars_evaluated == 0

    trades_01_tp2 = build_trades(h1_01, results_01, "TP2", "test")
    assert trades_01_tp2[0].target == pytest.approx(2105.0)
    assert trades_01_tp2[0].outcome == "open_at_end"

    h1_02 = load_h1("02_sell_valid")
    results_02 = run_engine(h1_02, load_m15("02_sell_valid"), include_no_signal=True)
    trades_02_tp1 = build_trades(h1_02, results_02, "TP1", "test")
    assert trades_02_tp1[0].target == pytest.approx(1930.0)
    trades_02_tp2 = build_trades(h1_02, results_02, "TP2", "test")
    assert trades_02_tp2[0].target == pytest.approx(1895.0)

    for name in [
        "03_no_m15_reaction",
        "04_expired_no_entry_touch",
        "05_rr_below_threshold",
        "06_same_bar_entry_sl_conflict",
        "07_real_breakout_no_close_back",
    ]:
        h1 = load_h1(name)
        results = run_engine(h1, load_m15(name), include_no_signal=True)
        trades = build_trades(h1, results, "TP1", "test")
        assert trades == []


def test_build_trades_fixture_01_extended_wins_at_tp1_not_yet_tp2():
    h1_01 = load_h1("01_buy_valid")
    results_01 = run_engine(h1_01, load_m15("01_buy_valid"), include_no_signal=True)

    extended = h1_01[["open", "high", "low", "close", "timestamp"]].copy()
    extra = pd.DataFrame(
        [
            {
                "timestamp": "2024-01-03T01:00:00Z",
                "open": 2005.0,
                "high": 2069.99,
                "low": 2000.0,
                "close": 2069.99,
            },
            {
                "timestamp": "2024-01-03T02:00:00Z",
                "open": 2069.99,
                "high": 2070.00,
                "low": 2065.0,
                "close": 2070.00,
            },
        ]
    )
    extended = pd.concat([extended, extra], ignore_index=True)

    trades_tp1 = build_trades(extended, results_01, "TP1", "test")
    assert trades_tp1[0].outcome == "win"
    assert trades_tp1[0].r_gross == pytest.approx(70 / 37)

    trades_tp2 = build_trades(extended, results_01, "TP2", "test")
    assert trades_tp2[0].outcome == "open_at_end"


# ---------------------------------------------------------------------------
# (g) multi_trap_stats on hand-built EngineResult-like objects
# ---------------------------------------------------------------------------


class _FakeSweepResult:
    def __init__(self, is_trap):
        self.is_trap = is_trap


class _FakeResult:
    def __init__(self, status, zone_candidates):
        self.status = status
        self.zone_candidates = zone_candidates


def _cand(center, is_trap):
    return {"zone": {"zone_center": center}, "sweep_result": _FakeSweepResult(is_trap)}


def test_multi_trap_stats_hand_built():
    r1 = _FakeResult("REJECTED_M15_NO_REACTION", [_cand(100.0, True), _cand(102.0, True), _cand(105.0, False)])
    r2 = _FakeResult("EXPIRED", [_cand(200.0, True)])  # only 1 trap -> not counted
    r3 = _FakeResult(None, [_cand(50.0, True), _cand(60.0, True)])  # status None -> excluded
    r4 = _FakeResult("NEEDS_MANUAL_REVIEW", [_cand(10.0, True), _cand(14.0, True), _cand(20.0, True)])

    stats = multi_trap_stats([r1, r2, r3, r4])
    assert stats["count_multi_trap"] == 2
    # r1 span = 102-100=2.0 ; r4 span = 20-10=10.0
    assert stats["median_span"] == pytest.approx(6.0)
    assert stats["max_span"] == pytest.approx(10.0)


def test_multi_trap_stats_empty_when_none_qualify():
    r1 = _FakeResult("EXPIRED", [_cand(100.0, True)])
    stats = multi_trap_stats([r1])
    assert stats["count_multi_trap"] == 0
    assert stats["median_span"] is None
    assert stats["max_span"] is None


# ---------------------------------------------------------------------------
# summarize_by
# ---------------------------------------------------------------------------


def test_summarize_by_direction():
    buys = [make_trade(1.0, exit_idx=1, outcome="win", direction="buy")]
    sells = [make_trade(-1.0, exit_idx=2, outcome="loss", direction="sell")]
    grouped = summarize_by(buys + sells, lambda t: t.direction, spread=0)
    assert grouped["buy"]["n_closed"] == 1
    assert grouped["buy"]["n_win"] == 1
    assert grouped["sell"]["n_closed"] == 1
    assert grouped["sell"]["n_loss"] == 1


def test_build_trades_invalid_variant_raises():
    with pytest.raises(ValueError, match="variant must be one of"):
        build_trades(load_h1("01_buy_valid"), [], "TP3", "test")
