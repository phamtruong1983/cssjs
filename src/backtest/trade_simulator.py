"""Post-fill trade outcome simulation (module 9b-1).

Pure function: given a FILLED entry (`fill_idx`, `entry`, `stop`,
`target`, `direction`), simulates what happens to that single position on
the H1 candles AFTER the fill, until it hits its stop, hits its target,
or the data runs out. This module does not run the signal engine and
does not run a multi-trade backtest loop -- it only resolves ONE already
-filled trade. It does not call `src.engine`, `src.signals`, or
`src.execution.entry_simulation` -- the caller is responsible for having
already determined `fill_idx`/`entry`/`stop` (e.g. from
`src.execution.entry_simulation.simulate_entry`'s `fill_idx` and
`src.risk.risk_reward.compute_risk_reward`'s `entry`/`stop`) and for
picking which take-profit level (`tp1` or `tp2`) to pass as `target` --
this module treats `target` as a single generic level, agnostic to which
TP it represents.

(a) SAME-BAR SL-vs-TP, SL FIRST: per `docs/DAO_GAM_RULES.md` Section 5
"Same-bar SL-vs-TP after entry" -- "once filled, if a later H1 (or M15,
for the parts of the trade managed intrabar) candle touches both the
stop-loss and a take-profit level with no intrabar ordering data
available, assume SL happens first (conservative resolution)." This
module only ever reads H1 data (see (d)), so on any candle where both the
stop and the target are touched, the outcome is unconditionally `"loss"`
at the stop price -- `both_touched=True` records that the target was ALSO
touched on that same candle, for reporting, but never changes the outcome
or `exit_price`.

(b) NOT MODELED: slippage, spread, gaps (beyond the informational
`gap_through_stop` flag), and commission/fees are entirely out of scope
here -- `docs/DAO_GAM_RULES.md` does not specify any of them (see the
module 9b-1 research pass). `exit_price` is always exactly `stop` (loss)
or exactly `target` (win), never adjusted for a gap past that level.
`gap_through_stop` is purely diagnostic: `True` when the resolving
candle's `open` already gapped past the stop level (BUY: `open_t <
stop_t`; SELL: `open_t > stop_t`), so a real fill would likely have been
worse than `stop` -- but this module still reports `exit_price = stop`
regardless, since modeling the actual worse fill is future scope.

(c) CHỐNG LOOK-AHEAD / no-look-ahead: only rows `fill_idx + 1` onward are
ever read, in order, stopping at (and including) the first candle that
resolves the trade (stop or target hit). `fill_idx` itself is never read
here -- the caller's fill simulation (e.g. `simulate_entry`) has already
fully accounted for that candle, including its own same-bar
conflict/ordering rules; re-reading it here would double-count it. No
candle after the resolving one is ever read, so mutating/NaN-ing data
beyond the resolution point can never change the result. Validation
(NaN, `high < low`) is therefore only ever applied to candles actually
read -- a bad row after the resolution point never raises.

(d) H1 ONLY: this module never reads or requires M15 data. The rules
doc's "or M15, for the parts of the trade managed intrabar" caveat in
Section 5 acknowledges intrabar M15 data COULD sharpen the same-bar
SL-vs-TP ordering, but implementing that is out of scope for this
function -- it always falls back to the documented SL-first assumption.

TICK-INTEGER COMPARISON: every price (`entry`, `stop`, `target`, and each
read candle's `high`/`low`/`open`) is converted to an integer tick via
`t(x) = round(x / TICK)` (`TICK` imported from
`src.market_structure.zones` -- the same public constant every other
module uses, not a private helper) before any comparison, to avoid
spurious pass/fail from binary floating-point noise (e.g.
`2000.0000000001`). `r_multiple` and `risk_ticks`/`reward_ticks` are also
computed from these integer tick counts.

FIELD SEMANTICS:
  - `outcome`: `"win"` (target hit, stop not hit first), `"loss"` (stop
    hit, whether or not target was also hit on the same candle), or
    `"open_at_end"` (data ran out with neither level hit).
  - `exit_idx`/`exit_price`/`exit_ts`: the resolving candle's position,
    the exact level hit (`stop` for a loss, `target` for a win -- never
    adjusted for slippage/gap), and that candle's raw `timestamp` column
    value (`None` if `df` has no `timestamp` column, or if
    `outcome == "open_at_end"`). All three are `None` for
    `"open_at_end"`.
  - `r_multiple`: `-1.0` for a loss (by definition: the position is
    stopped out for its full risk). For a win, `abs(target_t - entry_t) /
    abs(entry_t - stop_t)` -- a true (float) division of the two integer
    tick counts, not integer division. `None` for `"open_at_end"`.
  - `bars_held`: `exit_idx - fill_idx` (>= 1) for a resolved trade,
    `None` for `"open_at_end"`.
  - `bars_evaluated`: the number of candles actually read (from
    `fill_idx + 1` up to and including the resolving candle, or all
    remaining candles if `"open_at_end"`).
  - `both_touched`: `True` only when the resolving candle hit BOTH stop
    and target (always paired with `outcome == "loss"`, per (a)); `False`
    otherwise (including for `"win"` and `"open_at_end"`).
  - `gap_through_stop`: see (b). `None` whenever `df` has no `open`
    column, regardless of outcome. Otherwise `True` only when
    `outcome == "loss"` AND the resolving candle's open already gapped
    past `stop`; `False` in every other case (`"win"`, `"open_at_end"`,
    or a `"loss"` without a gap).
  - `direction`/`entry`/`stop`/`target`: echoed back from the arguments
    (post tick-noise-free float coercion).
  - `risk_ticks`/`reward_ticks`: `abs(entry_t - stop_t)` /
    `abs(target_t - entry_t)`, as integers.

ASSUMPTIONS (not specified in the docs, decided here):
  - `target` is a single generic level (the caller decides whether it is
    `tp1` or `tp2` -- this module does not know or care).
  - Only `high`/`low` are required columns; `open` and `timestamp` are
    both optional, independently of each other.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from src.market_structure.zones import TICK

VALID_DIRECTIONS = ("buy", "sell")
REQUIRED_COLUMNS = ["high", "low"]


@dataclass
class TradeResult:
    outcome: str  # "win" | "loss" | "open_at_end"
    exit_idx: int | None
    exit_price: float | None
    exit_ts: object | None
    r_multiple: float | None
    bars_held: int | None
    bars_evaluated: int
    both_touched: bool
    gap_through_stop: bool | None
    direction: str
    entry: float
    stop: float
    target: float
    risk_ticks: int
    reward_ticks: int


def _tick(x: float) -> int:
    return round(x / TICK)


def _validate_direction(direction: str) -> None:
    if direction not in VALID_DIRECTIONS:
        raise ValueError(f"direction must be one of {VALID_DIRECTIONS}, got {direction!r}")


def _validate_fill_idx(fill_idx: int, length: int) -> None:
    if not isinstance(fill_idx, int) or isinstance(fill_idx, bool):
        raise TypeError(f"fill_idx must be an int, got {type(fill_idx).__name__}")
    if fill_idx < 0 or fill_idx >= length:
        raise ValueError(f"fill_idx must be in [0, {length - 1}], got {fill_idx}")


def _validate_columns(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required column(s): {missing}")


def _validate_finite(name: str, value: float) -> float:
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return v


def _validate_row(df: pd.DataFrame, idx: int) -> None:
    row = df.iloc[idx]
    for col in ("high", "low"):
        if pd.isna(row[col]):
            raise ValueError(f"column '{col}' is NaN at idx {idx}")
    if row["high"] < row["low"]:
        raise ValueError(f"invalid OHLC: high < low at idx {idx}")


def simulate_trade(
    df: pd.DataFrame,
    fill_idx: int,
    direction: str,
    entry: float,
    stop: float,
    target: float,
) -> TradeResult:
    """Simulate the outcome of one already-filled trade on H1 candles
    after `fill_idx`.

    Parameters
    ----------
    df : H1 OHLC DataFrame (at least `high`, `low`; `open` and
        `timestamp` optional). Only rows at positions `fill_idx + 1`
        onward are ever read (see module docstring (c)).
    fill_idx : positional (0-based) index of the candle on which the
        entry was filled. Never read itself (see module docstring (c)).
    direction : `"buy"` or `"sell"`.
    entry, stop, target : the trade's levels. Must be finite and on the
        correct side of each other: for `"buy"`, `stop < entry < target`
        (tick-integer, strict); for `"sell"`, `target < entry < stop`.

    Returns
    -------
    TradeResult. See module docstring FIELD SEMANTICS.

    Raises
    ------
    TypeError / ValueError on an invalid `direction`, `fill_idx`, missing
    `high`/`low` columns, non-finite `entry`/`stop`/`target`, `stop`/
    `target` on the wrong side of `entry`, or (only for a candle actually
    read) NaN in `high`/`low` or `high < low`.
    """
    _validate_direction(direction)
    _validate_fill_idx(fill_idx, len(df))
    _validate_columns(df)

    entry = _validate_finite("entry", entry)
    stop = _validate_finite("stop", stop)
    target = _validate_finite("target", target)

    entry_t = _tick(entry)
    stop_t = _tick(stop)
    target_t = _tick(target)

    if direction == "buy":
        if not (stop_t < entry_t < target_t):
            raise ValueError(
                f"for direction='buy', must have stop < entry < target (in ticks); "
                f"got stop={stop}, entry={entry}, target={target}"
            )
    else:
        if not (target_t < entry_t < stop_t):
            raise ValueError(
                f"for direction='sell', must have target < entry < stop (in ticks); "
                f"got target={target}, entry={entry}, stop={stop}"
            )

    risk_ticks = abs(entry_t - stop_t)
    reward_ticks = abs(target_t - entry_t)

    has_ts = "timestamp" in df.columns
    has_open = "open" in df.columns

    bars_evaluated = 0
    for idx in range(fill_idx + 1, len(df)):
        _validate_row(df, idx)
        bars_evaluated += 1

        row = df.iloc[idx]
        high_t = _tick(float(row["high"]))
        low_t = _tick(float(row["low"]))

        if direction == "buy":
            stop_hit = low_t <= stop_t
            target_hit = high_t >= target_t
        else:
            stop_hit = high_t >= stop_t
            target_hit = low_t <= target_t

        if stop_hit:
            exit_ts = row["timestamp"] if has_ts else None
            if has_open:
                open_t = _tick(float(row["open"]))
                gap_through_stop = (open_t < stop_t) if direction == "buy" else (open_t > stop_t)
            else:
                gap_through_stop = None
            return TradeResult(
                outcome="loss",
                exit_idx=idx,
                exit_price=stop,
                exit_ts=exit_ts,
                r_multiple=-1.0,
                bars_held=idx - fill_idx,
                bars_evaluated=bars_evaluated,
                both_touched=target_hit,
                gap_through_stop=gap_through_stop,
                direction=direction,
                entry=entry,
                stop=stop,
                target=target,
                risk_ticks=risk_ticks,
                reward_ticks=reward_ticks,
            )

        if target_hit:
            exit_ts = row["timestamp"] if has_ts else None
            r_multiple = abs(target_t - entry_t) / abs(entry_t - stop_t)
            return TradeResult(
                outcome="win",
                exit_idx=idx,
                exit_price=target,
                exit_ts=exit_ts,
                r_multiple=r_multiple,
                bars_held=idx - fill_idx,
                bars_evaluated=bars_evaluated,
                both_touched=False,
                gap_through_stop=(None if not has_open else False),
                direction=direction,
                entry=entry,
                stop=stop,
                target=target,
                risk_ticks=risk_ticks,
                reward_ticks=reward_ticks,
            )

    return TradeResult(
        outcome="open_at_end",
        exit_idx=None,
        exit_price=None,
        exit_ts=None,
        r_multiple=None,
        bars_held=None,
        bars_evaluated=bars_evaluated,
        both_touched=False,
        gap_through_stop=(None if not has_open else False),
        direction=direction,
        entry=entry,
        stop=stop,
        target=target,
        risk_ticks=risk_ticks,
        reward_ticks=reward_ticks,
    )
