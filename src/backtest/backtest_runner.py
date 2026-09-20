"""Fixed-grid backtest runner and statistics (module 9b-2).

Consumes a list of ALREADY-COMPUTED `src.engine.dao_gam_engine.EngineResult`
(produced elsewhere by `run_engine`/`evaluate_sweep_candidate` +
`annotate_repeats`) and `src.backtest.trade_simulator.simulate_trade` to
build `Trade` records and summary statistics, for a FIXED, externally
chosen parameter grid. This module adds NO configuration, filtering, or
variant of its own beyond what the caller passes in (`config`, `variant`,
`spread`, `mode`) -- it is pure aggregation/statistics over whatever
`EngineResult`s and parameters it is given.

ASSUMPTIONS / CAVEATS (repeated from upstream modules, restated here for
this module's own readers):
  - SL-BEFORE-TP: every `Trade`'s `r_gross`/`outcome` comes straight from
    `simulate_trade`, which (per `docs/DAO_GAM_RULES.md` Section 5) always
    resolves a same-candle stop-and-target touch as a loss (SL first).
    This module does not re-derive or second-guess that.
  - SPREAD IS NOT REAL TRANSACTION-COST MODELING: `apply_spread`/
    `summarize`'s `spread` parameter is a single illustrative price-unit
    charge subtracted from a closed trade's R (`spread / risk_price`),
    not a real bid/ask spread, slippage, or commission model --
    `docs/DAO_GAM_RULES.md` does not specify any of those (see the
    module 9b research pass). Treat any non-zero-spread number here as a
    what-if illustration, not a cost estimate.
  - BID-ONLY DATA, BUY OPTIMISM: the underlying price feed
    (`data/processed/XAUUSD*/`) is bid-side only (Dukascopy). A real BUY
    fill would execute on the ask, which is at or above the bid at every
    instant -- so every BUY entry/stop/target level here is implicitly a
    little easier to fill and a little easier to hit favorably than a
    real ask-side fill would be. This module does not correct for that.
  - FIXED GRID: `config`/`variant` are opaque labels the caller supplies
    (e.g. `"atr0.10"` / `"TP1"`) -- this module does not enumerate,
    search, or optimize over any grid; it only aggregates what it is
    given.
  - SMALL SAMPLE: with a V1 sweep rate on the order of tens of trades per
    grid cell (see module 9b research pass), every statistic here is
    DESCRIPTIVE of the specific historical sample evaluated, not a
    reliable estimate of future performance -- `mean_r_ci95` exists
    precisely to make that sampling uncertainty visible, not to declare
    significance.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from src.backtest.trade_simulator import simulate_trade
from src.market_structure.zones import TICK

VALID_VARIANTS = ("TP1", "TP2")
VALID_MODES = ("independent", "one_at_a_time", "no_repeat24h")


@dataclass
class Trade:
    config: str
    variant: str
    sweep_idx: int
    sweep_ts: object
    direction: str
    fill_idx: int
    entry: float
    stop: float
    target: float
    outcome: str  # "win" | "loss" | "open_at_end"
    exit_idx: int | None
    r_gross: float | None
    bars_held: int | None
    bars_evaluated: int
    both_touched: bool
    gap_through_stop: bool | None
    risk_price: float
    repeat_zone_within_24h: bool | None


def _validate_variant(variant: str) -> None:
    if variant not in VALID_VARIANTS:
        raise ValueError(f"variant must be one of {VALID_VARIANTS}, got {variant!r}")


def _validate_mode(mode: str) -> None:
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {VALID_MODES}, got {mode!r}")


def build_trades(h1_df, results, variant: str, config: str) -> list[Trade]:
    """Build `Trade` records from `EngineResult`s that reached a filled
    entry.

    Only results with `status == "NEEDS_MANUAL_REVIEW"` AND
    `entry_state == "filled"` produce a `Trade` -- `entry_state ==
    "pending"` (still-open at scan time) and every other `status` are
    excluded entirely (never partially represented). For each such
    result, `target` is `result.tp1` (variant `"TP1"`) or `result.tp2`
    (`"TP2"`), and `simulate_trade(h1_df, result.fill_idx,
    result.direction, result.entry, result.stop, target)` resolves the
    outcome. `risk_price = simulate_trade`'s own `risk_ticks * TICK`
    (`TICK` from `src.market_structure.zones`).

    Returns
    -------
    list[Trade], sorted by `fill_idx` ascending.
    """
    _validate_variant(variant)

    trades: list[Trade] = []
    for r in results:
        if r.status != "NEEDS_MANUAL_REVIEW" or r.entry_state != "filled":
            continue

        target = r.tp1 if variant == "TP1" else r.tp2
        sim = simulate_trade(h1_df, r.fill_idx, r.direction, r.entry, r.stop, target)
        risk_price = sim.risk_ticks * TICK

        trades.append(
            Trade(
                config=config,
                variant=variant,
                sweep_idx=r.sweep_idx,
                sweep_ts=r.sweep_ts,
                direction=r.direction,
                fill_idx=r.fill_idx,
                entry=r.entry,
                stop=r.stop,
                target=target,
                outcome=sim.outcome,
                exit_idx=sim.exit_idx,
                r_gross=sim.r_multiple,
                bars_held=sim.bars_held,
                bars_evaluated=sim.bars_evaluated,
                both_touched=sim.both_touched,
                gap_through_stop=sim.gap_through_stop,
                risk_price=risk_price,
                repeat_zone_within_24h=r.repeat_zone_within_24h,
            )
        )

    trades.sort(key=lambda t: t.fill_idx)
    return trades


def select_trades(trades: list[Trade], mode: str) -> list[Trade]:
    """Filter `trades` (already sorted, or re-sorted here, by
    `fill_idx`) under one of three overlap-handling modes.

    - `"independent"`: every trade kept as-is (no overlap handling --
      trades may occupy overlapping bar ranges).
    - `"one_at_a_time"`: at most one open position at a time. Walking
      `trades` in `fill_idx` order, a trade is kept only if its
      `fill_idx` is STRICTLY greater than the `exit_idx` of the most
      recently KEPT trade that is still open (an `"open_at_end"` trade
      is treated as open forever, so no later trade can ever be kept
      once one is selected). The strict `>` (not `>=`) is deliberate:
      since there is no intrabar ordering data, a new fill on the exact
      same candle the previous trade exited cannot be ruled out as
      happening before that exit, so it is conservatively excluded too.
    - `"no_repeat24h"`: drops every trade with `repeat_zone_within_24h
      is True`; otherwise independent (no overlap handling).
    """
    _validate_mode(mode)

    if mode == "independent":
        return list(trades)

    if mode == "no_repeat24h":
        return [t for t in trades if t.repeat_zone_within_24h is not True]

    # one_at_a_time
    ordered = sorted(trades, key=lambda t: t.fill_idx)
    selected: list[Trade] = []
    open_exit_idx: float | None = None  # None = no open trade; float("inf") = open_at_end
    for t in ordered:
        if open_exit_idx is None or t.fill_idx > open_exit_idx:
            selected.append(t)
            open_exit_idx = float("inf") if t.outcome == "open_at_end" else float(t.exit_idx)
    return selected


def apply_spread(trades: list[Trade], spread: float) -> list[float | None]:
    """Return, in the same order as `trades`, the spread-adjusted R
    (`r_net = r_gross - spread / risk_price`) for each CLOSED trade
    (`outcome` `"win"`/`"loss"`), or `None` for an `"open_at_end"` trade
    (it has no realized R to adjust). `spread == 0` reproduces
    `r_gross` exactly. See module docstring for what `spread` does and
    does not model.
    """
    out: list[float | None] = []
    for t in trades:
        if t.outcome == "open_at_end":
            out.append(None)
        else:
            out.append(t.r_gross - spread / t.risk_price)
    return out


def _percentile(values: list[float], p: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), p))


def summarize(trades: list[Trade], spread: float) -> dict:
    """Summary statistics computed ONLY over CLOSED trades (`outcome`
    `"win"`/`"loss"`) -- `n_open_at_end` and `n_distinct_fill_days` are
    the only two fields below that also look at (resp. do not care
    about) open trades, as noted per-field.

    Fields
    ------
    n_closed, n_win, n_loss, n_open_at_end : counts.
    win_rate : `n_win / n_closed`, `None` if `n_closed == 0`.
    avg_win_r : mean of `r_gross` (NOT spread-adjusted) over winning
        trades only, `None` if there are no wins.
    breakeven_win_rate : `1 / (1 + avg_win_r)`, `None` if `avg_win_r` is
        `None`.
    mean_r, median_r, total_r : mean/median/sum of the spread-adjusted
        `r_net` (see `apply_spread`) over closed trades, `None` if
        `n_closed == 0`.
    profit_factor : `sum(positive r_net) / abs(sum(negative r_net))`,
        `None` if there are no losing trades (by `outcome`) or no closed
        trades at all.
    max_drawdown_r : trades ordered by `exit_idx` ascending; walking the
        cumulative sum of `r_net` in that order, tracking a running peak
        (starting at 0) and the largest peak-to-trough drop seen so far;
        `None` if `n_closed == 0`.
    mean_r_ci95 : `(p2.5, p97.5)` of the bootstrap distribution of the
        mean of `r_net` (10000 resamples WITH replacement,
        `numpy.random.default_rng(20260920)`), `None` if `n_closed < 5`.
    bars_held_p10, bars_held_p50, bars_held_p90 : percentiles of
        `bars_held` over closed trades, `None` if `n_closed == 0`.
    both_touched_count, gap_through_stop_count : counts over closed
        trades where the flag is `True`.
    n_distinct_fill_days : number of distinct UTC calendar dates among
        ALL trades' (closed and open) fill events. `Trade` has no
        `fill_ts` field (only `sweep_ts`/`fill_idx`), so this ALWAYS
        derives the date from `sweep_ts` (the "use sweep_ts only when
        there is no fill timestamp" caveat always applies here, since a
        fill timestamp is never available on `Trade`).
    n_by_direction : `{"buy": n, "sell": n}` over closed trades.
    """
    closed = [t for t in trades if t.outcome in ("win", "loss")]
    n_closed = len(closed)
    n_win = sum(1 for t in closed if t.outcome == "win")
    n_loss = sum(1 for t in closed if t.outcome == "loss")
    n_open_at_end = sum(1 for t in trades if t.outcome == "open_at_end")

    win_rate = (n_win / n_closed) if n_closed > 0 else None

    win_r_gross = [t.r_gross for t in closed if t.outcome == "win"]
    avg_win_r = (sum(win_r_gross) / len(win_r_gross)) if win_r_gross else None
    breakeven_win_rate = (1.0 / (1.0 + avg_win_r)) if avg_win_r is not None else None

    r_net_by_trade = {id(t): (t.r_gross - spread / t.risk_price) for t in closed}
    r_net_list = [r_net_by_trade[id(t)] for t in closed]

    if n_closed > 0:
        mean_r = float(np.mean(r_net_list))
        median_r = float(np.median(r_net_list))
        total_r = float(np.sum(r_net_list))
        bars_held_list = [t.bars_held for t in closed]
        bars_held_p10 = _percentile(bars_held_list, 10)
        bars_held_p50 = _percentile(bars_held_list, 50)
        bars_held_p90 = _percentile(bars_held_list, 90)
    else:
        mean_r = median_r = total_r = None
        bars_held_p10 = bars_held_p50 = bars_held_p90 = None

    if n_loss == 0 or n_closed == 0:
        profit_factor = None
    else:
        pos_sum = sum(x for x in r_net_list if x > 0)
        neg_sum = sum(x for x in r_net_list if x < 0)
        profit_factor = (pos_sum / abs(neg_sum)) if neg_sum != 0 else None

    if n_closed > 0:
        closed_by_exit = sorted(closed, key=lambda t: t.exit_idx)
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in closed_by_exit:
            cumulative += r_net_by_trade[id(t)]
            peak = max(peak, cumulative)
            max_dd = max(max_dd, peak - cumulative)
        max_drawdown_r = max_dd
    else:
        max_drawdown_r = None

    if n_closed >= 5:
        rng = np.random.default_rng(20260920)
        arr = np.asarray(r_net_list, dtype=float)
        boot_means = np.empty(10000, dtype=float)
        for i in range(10000):
            sample = rng.choice(arr, size=n_closed, replace=True)
            boot_means[i] = sample.mean()
        mean_r_ci95 = (float(np.percentile(boot_means, 2.5)), float(np.percentile(boot_means, 97.5)))
    else:
        mean_r_ci95 = None

    both_touched_count = sum(1 for t in closed if t.both_touched)
    gap_through_stop_count = sum(1 for t in closed if t.gap_through_stop is True)

    def _fill_date(t: Trade):
        ts = t.sweep_ts
        if ts is None:
            return None
        return str(ts)[:10]  # UTC calendar date portion of the ISO-like string/Timestamp

    n_distinct_fill_days = len({_fill_date(t) for t in trades if _fill_date(t) is not None})

    n_by_direction: dict[str, int] = defaultdict(int)
    for t in closed:
        n_by_direction[t.direction] += 1

    return {
        "n_closed": n_closed,
        "n_win": n_win,
        "n_loss": n_loss,
        "n_open_at_end": n_open_at_end,
        "win_rate": win_rate,
        "avg_win_r": avg_win_r,
        "breakeven_win_rate": breakeven_win_rate,
        "mean_r": mean_r,
        "median_r": median_r,
        "total_r": total_r,
        "profit_factor": profit_factor,
        "max_drawdown_r": max_drawdown_r,
        "mean_r_ci95": mean_r_ci95,
        "bars_held_p10": bars_held_p10,
        "bars_held_p50": bars_held_p50,
        "bars_held_p90": bars_held_p90,
        "both_touched_count": both_touched_count,
        "gap_through_stop_count": gap_through_stop_count,
        "n_distinct_fill_days": n_distinct_fill_days,
        "n_by_direction": dict(n_by_direction),
    }


def summarize_by(trades: list[Trade], key_fn, spread: float) -> dict:
    """Group `trades` by `key_fn(trade)` and call `summarize` on each
    group. `key_fn` is caller-supplied (e.g. `lambda t: t.direction`, or
    `lambda t: pd.Timestamp(t.sweep_ts).year` for a by-year breakdown) --
    this module does not hardcode any particular grouping."""
    groups: dict = defaultdict(list)
    for t in trades:
        groups[key_fn(t)].append(t)
    return {k: summarize(v, spread) for k, v in groups.items()}


def multi_trap_stats(results) -> dict:
    """Among `results` with a non-`None` `status`, count how many have
    `>= 2` entries in `zone_candidates` whose `sweep_result.is_trap` is
    `True`, and for exactly those results, the median/max of
    `max(zone_center) - min(zone_center)` across their trapped zones
    (price units)."""
    count_multi_trap = 0
    spans: list[float] = []
    for r in results:
        if r.status is None:
            continue
        trapped_centers = [c["zone"]["zone_center"] for c in r.zone_candidates if c["sweep_result"].is_trap]
        if len(trapped_centers) >= 2:
            count_multi_trap += 1
            spans.append(max(trapped_centers) - min(trapped_centers))

    return {
        "count_multi_trap": count_multi_trap,
        "median_span": float(np.median(spans)) if spans else None,
        "max_span": float(max(spans)) if spans else None,
    }
