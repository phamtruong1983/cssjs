"""Limit-order entry simulation at `zone_center` (`DAO_GAM_RULES.md` Section 5).

Simulates the resting limit order described in `DAO_GAM_RULES.md` Section
5 / `docs/DATA_SCHEMA.md` Section 9: a limit order at `entry` (the zone's
`zone_center`, computed elsewhere -- this module takes `entry` as a
plain float and does not know about zones), live for exactly the 2 H1
candles immediately after the activation bar. This module does not call
`sweep.py`, `m15_reaction.py`, `zones.py`, or `risk_reward.py` -- only
`TICK` is imported from `src.market_structure.zones` (a public constant,
not a private helper). It does not simulate SL/TP management after a
fill (that belongs to the backtest module).

VALIDITY WINDOW: exactly the H1 candles at positions `activation_idx + 1`
and `activation_idx + 2`. The activation bar itself (`activation_idx`) is
never read. No row at or after `activation_idx + 3` is ever read. If
fewer than 2 of those window positions exist in `df` (i.e. the data ends
before printing both), only the ones that exist are read.

TICK-INTEGER COMPARISON: `t(x) = round(x / TICK)` (`TICK` from
`src.market_structure.zones`). For each window candle, in order:
  - `entry_touched = low_t <= entry_t <= high_t` (inclusive)
  - `stop_touched`: BUY `low_t <= stop_t`; SELL `high_t >= stop_t`

DECISION RULE, evaluated candle by candle, stopping at the first
conclusion (see `docs/DAO_GAM_RULES.md` Section 5):
  1. `entry_touched and stop_touched` on the same candle -> conservative,
     no fill: `outcome="expired"`, `reason="same_bar_entry_stop_conflict"`
     (`DAO_GAM_RULES.md` Section 5, "Same-bar SL-before-entry").
  2. `entry_touched` only -> `outcome="filled"`, `fill_price=entry`
     (never open/close), `fill_idx`/`fill_ts` set to that candle.
  3. `stop_touched` only (entry not touched) -> `outcome="expired"`,
     `reason="stop_touched_before_entry"`. This is an INFERENCE from
     `DAO_GAM_RULES.md` Section 5's sentence "the setup is treated as
     invalidated from that point on ... and logged as EXPIRED, since ...
     the level the plan depends on has already been breached" -- that
     sentence is written for the same-bar-conflict case, but this module
     applies the same invalidation logic when the stop level alone is
     breached first (before entry ever touches), since the plan is
     broken either way. This is NOT a verbatim rule from the docs (see
     ASSUMPTIONS).
  4. Neither touched on this candle -> no conclusion yet; continue to the
     next window candle if one exists.
  5. Both window candles evaluated (2 candles read) with no conclusion
     -> `outcome="expired"`, `reason="no_touch"`.
  6. Fewer than 2 window candles exist and no conclusion was reached ->
     `outcome="window_incomplete"`, `reason="window_incomplete"`. The
     caller is responsible for only ever passing already-closed bars;
     this module cannot distinguish "data not printed yet" from "data
     genuinely absent".

This module never assigns a pipeline status -- `outcome="expired"` is a
local value; a future engine maps it to `EXPIRED`
(`docs/DATA_SCHEMA.md` Section 8).

ASSUMPTIONS (not specified verbatim in the docs, decided here):
  - Rule 3 above (`stop_touched_before_entry` -> `EXPIRED`-equivalent) is
    an inference from Section 5's same-bar-conflict sentence, applied to
    the stop-touched-alone case. See DECISION RULE item 3.
  - Threshold/touch comparisons use tick-rounding (consistent with
    `sweep.py`, `m15_reaction.py`, `risk_reward.py`).
  - The per-candle log records every window candle actually read (i.e.
    up to and including the concluding candle; never candles beyond it).
  - `fill_ts` is `None` when `df` has no `timestamp` column; otherwise
    it is the concluding candle's `timestamp` value, unconverted (this
    module does not parse or compare timestamps itself, unlike
    `m15_reaction.py` -- it only reports the raw value for logging).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.market_structure.zones import TICK

VALID_DIRECTIONS = ("buy", "sell")
REQUIRED_COLUMNS = ["high", "low"]
WINDOW_SIZE = 2


@dataclass
class WindowCandle:
    idx: int
    high: float
    low: float
    entry_touched: bool
    stop_touched: bool


@dataclass
class EntrySimulationResult:
    outcome: str  # "filled" | "expired" | "window_incomplete"
    reason: str  # "ok" | "no_touch" | "same_bar_entry_stop_conflict" | "stop_touched_before_entry" | "window_incomplete"
    fill_idx: int | None
    fill_price: float | None
    fill_ts: object | None
    direction: str
    entry: float
    stop: float
    candles: list = field(default_factory=list)


def _tick(x: float) -> int:
    return round(x / TICK)


def _validate_direction(direction: str) -> None:
    if direction not in VALID_DIRECTIONS:
        raise ValueError(f"direction must be one of {VALID_DIRECTIONS}, got {direction!r}")


def _validate_activation_idx(activation_idx: int, length: int) -> None:
    if not isinstance(activation_idx, int) or isinstance(activation_idx, bool):
        raise TypeError(f"activation_idx must be an int, got {type(activation_idx).__name__}")
    if activation_idx < 0 or activation_idx >= length:
        raise ValueError(f"activation_idx must be in [0, {length - 1}], got {activation_idx}")


def _validate_columns(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required column(s): {missing}")


def _validate_finite(name: str, value: float) -> float:
    v = float(value)
    if not np.isfinite(v):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return v


def _validate_entry_stop_side(direction: str, entry_t: int, stop_t: int, entry: float, stop: float) -> None:
    if direction == "buy":
        if stop_t >= entry_t:
            raise ValueError(f"for direction='buy', stop ({stop}) must be < entry ({entry})")
    else:
        if stop_t <= entry_t:
            raise ValueError(f"for direction='sell', stop ({stop}) must be > entry ({entry})")


def _validate_row(df: pd.DataFrame, idx: int) -> None:
    row = df.iloc[idx]
    for col in ("high", "low"):
        if pd.isna(row[col]):
            raise ValueError(f"column '{col}' is NaN at idx {idx}")
    if row["high"] < row["low"]:
        raise ValueError(f"invalid OHLC: high < low at idx {idx}")


def simulate_entry(
    df: pd.DataFrame,
    activation_idx: int,
    direction: str,
    entry: float,
    stop: float,
) -> EntrySimulationResult:
    """Simulate the resting limit order at `entry` over its 2-H1-candle window.

    Parameters
    ----------
    df : H1 OHLC DataFrame (at least `high`, `low` columns; `timestamp`
        optional). Only rows at positions `activation_idx + 1` and
        `activation_idx + 2` (whichever exist) are ever read.
    activation_idx : positional (0-based) index of the activation bar.
        Never read itself.
    direction : `"buy"` or `"sell"`.
    entry : the limit order price (= `zone_center`, computed elsewhere).
        Must be finite.
    stop : the stop-loss price. Must be finite and strictly on the
        correct side of `entry` (`stop < entry` for buy, `stop > entry`
        for sell), compared in ticks.

    Returns
    -------
    EntrySimulationResult. See module docstring for `outcome`/`reason`
    semantics.

    Raises
    ------
    TypeError / ValueError on an invalid `direction`, `activation_idx`,
    missing `high`/`low` columns, non-finite `entry`/`stop`, `stop` on
    the wrong side of `entry`, NaN in `high`/`low`, or `high < low` for
    any window candle actually read.
    """
    _validate_direction(direction)
    _validate_activation_idx(activation_idx, len(df))
    _validate_columns(df)

    entry = _validate_finite("entry", entry)
    stop = _validate_finite("stop", stop)

    entry_t = _tick(entry)
    stop_t = _tick(stop)
    _validate_entry_stop_side(direction, entry_t, stop_t, entry, stop)

    has_ts = "timestamp" in df.columns
    window_positions = [p for p in (activation_idx + 1, activation_idx + 2) if p < len(df)][:WINDOW_SIZE]

    candles: list[WindowCandle] = []

    for idx in window_positions:
        _validate_row(df, idx)
        row = df.iloc[idx]
        high, low = float(row["high"]), float(row["low"])
        high_t, low_t = _tick(high), _tick(low)

        entry_touched = low_t <= entry_t <= high_t
        if direction == "buy":
            stop_touched = low_t <= stop_t
        else:
            stop_touched = high_t >= stop_t

        candles.append(
            WindowCandle(idx=idx, high=high, low=low, entry_touched=entry_touched, stop_touched=stop_touched)
        )

        if entry_touched and stop_touched:
            return EntrySimulationResult(
                outcome="expired",
                reason="same_bar_entry_stop_conflict",
                fill_idx=None,
                fill_price=None,
                fill_ts=None,
                direction=direction,
                entry=entry,
                stop=stop,
                candles=candles,
            )

        if entry_touched:
            fill_ts = row["timestamp"] if has_ts else None
            return EntrySimulationResult(
                outcome="filled",
                reason="ok",
                fill_idx=idx,
                fill_price=entry,
                fill_ts=fill_ts,
                direction=direction,
                entry=entry,
                stop=stop,
                candles=candles,
            )

        if stop_touched:
            return EntrySimulationResult(
                outcome="expired",
                reason="stop_touched_before_entry",
                fill_idx=None,
                fill_price=None,
                fill_ts=None,
                direction=direction,
                entry=entry,
                stop=stop,
                candles=candles,
            )

    if len(candles) >= WINDOW_SIZE:
        outcome = "expired"
        reason = "no_touch"
    else:
        outcome = "window_incomplete"
        reason = "window_incomplete"

    return EntrySimulationResult(
        outcome=outcome,
        reason=reason,
        fill_idx=None,
        fill_price=None,
        fill_ts=None,
        direction=direction,
        entry=entry,
        stop=stop,
        candles=candles,
    )
