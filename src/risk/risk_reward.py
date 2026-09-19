"""Stop-loss, TP1, TP2, and R:R calculation for a confirmed sweep.

Implements `docs/DAO_GAM_RULES.md` Section 3 rules 7 and 8, and
`docs/DATA_SCHEMA.md` Sections 5-6, for exactly one sweep candle
(`sweep_idx`) whose `direction`, `zone_center`, `sweep_extreme`, and
`atr_h1_14` (= `atr.iloc[sweep_idx - 1]`, computed by the caller via
`src.indicators.atr.atr` and `src.signals.sweep.detect_sweep`) are
supplied directly. This module does NOT call `sweep.py`,
`m15_reaction.py`, or `zones.py`, and does not compute ATR itself -- it
only turns already-confirmed sweep facts into SL/TP1/TP2/R:R. It DOES
call `find_swings` (`src.market_structure.swings`) to determine TP1, and
imports `TICK` from `src.market_structure.zones` (the same public
constant other modules use, not a private helper).

CHỐNG LOOK-AHEAD / no-look-ahead: TP1 is chosen only from swings
confirmed using `df.iloc[:sweep_idx + 1]` -- the sweep candle is the last
closed H1 bar this function is allowed to know about. No row after
`sweep_idx` is ever read.

FIELD NAMES: match `docs/DATA_SCHEMA.md` Sections 5-6 where a field of
that name exists there (`direction`, `entry`, `stop`, `tp1`, `tp2`,
`risk`, `sweep_amplitude`, `atr_h1_14`, `sweep_extreme`, `zone_center`).
`tp1_idx`, `reward_to_tp1`, `rr_to_tp1`, `reward_to_tp2`, `rr_to_tp2`,
`tradable`, and `reason` are not named in `docs/DATA_SCHEMA.md` (see
ASSUMPTIONS). `docs/DAO_GAM_RULES.md` Section 3 rule 8 only gates on R:R
to TP2 -- `reward_to_tp1`/`rr_to_tp1` (this module's approximation of the
schema's `rr1`) are populated FOR REFERENCE ONLY and never affect
`tradable`/`reason`.

TP1 SELECTION (`DAO_GAM_RULES.md` Section 3 rule 8 / `docs/DATA_SCHEMA.md`
Section 6: "nearest H1 swing high/low in the reversal direction"): the
docs state "nearest" without specifying nearest in price or nearest in
time. Per the caller's explicit instruction, this module resolves it as
**nearest in time** -- among confirmed swings on the reversal side
(swing highs above `entry`, strictly, for BUY; swing lows below `entry`,
strictly, for SELL), the one with the **largest index** (most recently
confirmed) is TP1. This is an ASSUMPTION, not a literal quote from the
docs (see ASSUMPTIONS).

STOP-LOSS: `stop = sweep_extreme -/+ 0.20 * atr_h1_14` (minus for BUY,
plus for SELL), rounded to the nearest tick. `docs/DAO_GAM_RULES.md`
Section 3 rule 7 states the 0.20x buffer but not a rounding rule --
tick-rounding is this module's own ASSUMPTION, consistent with
`sweep.py` and `m15_reaction.py`.

R:R THRESHOLD: compared in integer ticks (`reward_t = tick(reward_to_tp2)`,
`risk_t = tick(risk)`): `reward_t >= 2 * risk_t` passes (`>=`, so exactly
2.0 passes), per `DAO_GAM_RULES.md` Section 3 rule 8 ("R:R to TP2 >= 2.0").
`tp2`, `risk`, and `reward_to_tp2` (and, for reference, `reward_to_tp1`)
are all rounded to the nearest tick (via this module's own `_round_tick`)
before `rr_to_tp2`/`rr_to_tp1` are computed from those rounded values --
this avoids binary floating-point noise propagating into the ratio.

SWING SELECTION COMPARISON: whether a swing qualifies "on the reversal
side, strictly beyond entry" is decided in integer ticks --
`tick(high) > tick(entry)` for BUY, `tick(low) < tick(entry)` for SELL --
not a raw float comparison, for the same floating-point-noise reason.

ASSUMPTIONS (not specified in the docs, decided here):
  - TP1 "nearest" = nearest in time (largest confirmed swing index) --
    see TP1 SELECTION above. This is the caller's explicit resolution of
    an ambiguity the docs leave open, not something inferred here.
  - Stop-loss rounded to the nearest tick (0.01).
  - `reason` codes (short, deliberately distinct from any pipeline status
    name): `"ok"` (tradable), `"tp1_unavailable"` (no swing qualifies on
    the reversal side), `"rr_below_threshold"` (TP1 exists but R:R to
    TP2 < 2.0). None of these is a pipeline status
    (`NEEDS_MANUAL_REVIEW` / `REJECTED_M15_NO_REACTION` / `EXPIRED` /
    `REJECTED_RR_BELOW_THRESHOLD`) -- a future engine maps
    `"rr_below_threshold"` to `REJECTED_RR_BELOW_THRESHOLD`, not this
    module.
  - When `reason == "tp1_unavailable"`, `tp1`, `tp1_idx`, `tp2`,
    `reward_to_tp2`, and `rr_to_tp2` are all `None` (there is nothing to
    compute them from); `entry`, `stop`, `risk`, `sweep_amplitude`,
    `atr_h1_14`, `sweep_extreme`, `zone_center` are still populated.
  - The "stop on the wrong side of entry" check (`DAO_GAM_RULES.md`
    Section 3 rule 8 / the caller's rule 6) is evaluated on
    **tick-rounded** `stop` vs. tick-rounded `entry` (`stop_t >= entry_t`
    for BUY, `stop_t <= entry_t` for SELL raises) -- this also catches
    the `risk_t == 0` case as a special case of "wrong side" (equal
    ticks), since a separate `risk_t > 0` check would be redundant with
    it.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.market_structure.swings import find_swings
from src.market_structure.zones import TICK

VALID_DIRECTIONS = ("buy", "sell")
REQUIRED_COLUMNS = ["high", "low", "close"]


@dataclass
class RiskRewardResult:
    tradable: bool
    reason: str  # "ok" | "rr_below_threshold" | "tp1_unavailable"
    direction: str
    entry: float
    stop: float
    tp1: float | None
    tp1_idx: int | None
    tp2: float | None
    sweep_amplitude: float
    risk: float
    reward_to_tp1: float | None
    rr_to_tp1: float | None
    reward_to_tp2: float | None
    rr_to_tp2: float | None
    atr_h1_14: float
    sweep_extreme: float
    zone_center: float


def _tick(x: float) -> int:
    return round(x / TICK)


def _round_tick(x: float) -> float:
    return round(_tick(x) * TICK, 10)


def _validate_direction(direction: str) -> None:
    if direction not in VALID_DIRECTIONS:
        raise ValueError(f"direction must be one of {VALID_DIRECTIONS}, got {direction!r}")


def _validate_sweep_idx(sweep_idx: int, length: int) -> None:
    if not isinstance(sweep_idx, int) or isinstance(sweep_idx, bool):
        raise TypeError(f"sweep_idx must be an int, got {type(sweep_idx).__name__}")
    if sweep_idx < 0 or sweep_idx >= length:
        raise ValueError(f"sweep_idx must be in [0, {length - 1}], got {sweep_idx}")


def _validate_columns(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required column(s): {missing}")


def _validate_close_column(df: pd.DataFrame) -> None:
    close = df["close"]
    if close.isna().any():
        bad_idx = df.index[close.isna()].tolist()
        raise ValueError(f"column 'close' contains NaN at row(s) {bad_idx}")


def _validate_finite(name: str, value: float) -> float:
    v = float(value)
    if not np.isfinite(v):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return v


def _validate_atr(atr_h1_14: float) -> float:
    value = _validate_finite("atr_h1_14", atr_h1_14)
    if value <= 0:
        raise ValueError(f"atr_h1_14 must be > 0, got {atr_h1_14!r}")
    return value


def _validate_sweep_side(direction: str, zone_center: float, sweep_extreme: float) -> None:
    if direction == "buy":
        if not (sweep_extreme < zone_center):
            raise ValueError(
                f"for direction='buy', sweep_extreme must be < zone_center; "
                f"got sweep_extreme={sweep_extreme}, zone_center={zone_center}"
            )
    else:
        if not (sweep_extreme > zone_center):
            raise ValueError(
                f"for direction='sell', sweep_extreme must be > zone_center; "
                f"got sweep_extreme={sweep_extreme}, zone_center={zone_center}"
            )


def compute_risk_reward(
    df: pd.DataFrame,
    sweep_idx: int,
    direction: str,
    zone_center: float,
    sweep_extreme: float,
    atr_h1_14: float,
    n: int = 3,
) -> RiskRewardResult:
    """Compute entry/stop/TP1/TP2/R:R for a confirmed sweep candle.

    Parameters
    ----------
    df : H1 OHLC DataFrame (at least `high`, `low`, `close` columns).
        Only `df.iloc[:sweep_idx + 1]` is ever read (no look-ahead).
    sweep_idx : positional (0-based) index of the sweep candle -- the
        last H1 bar this function may use.
    direction : `"buy"` or `"sell"`.
    zone_center : the zone's center price (used as `entry`). Must be
        finite and strictly on the correct side of `sweep_extreme`.
    sweep_extreme : the sweep candle's extreme (low for buy/support, high
        for sell/resistance). Must be finite.
    atr_h1_14 : `atr.iloc[sweep_idx - 1]` from the caller (this module
        does not compute ATR). Must be finite and `> 0`.
    n : fractal swing parameter forwarded to `find_swings` (default 3).

    Returns
    -------
    RiskRewardResult. See module docstring for `reason` codes and the
    `tp1_unavailable` field-nulling behavior.

    Raises
    ------
    TypeError / ValueError on an invalid `direction`, `sweep_idx`,
    missing `high`/`low`/`close` columns, non-finite `atr_h1_14` (or
    `<= 0`), non-finite `zone_center`/`sweep_extreme`, `sweep_extreme` on
    the wrong side of `zone_center`, or a computed `stop` on the wrong
    side of `entry` (see module docstring).
    """
    _validate_direction(direction)
    _validate_sweep_idx(sweep_idx, len(df))
    _validate_columns(df)

    used = df.iloc[: sweep_idx + 1]
    _validate_close_column(used)

    zone_center = _validate_finite("zone_center", zone_center)
    sweep_extreme = _validate_finite("sweep_extreme", sweep_extreme)
    atr_h1_14 = _validate_atr(atr_h1_14)
    _validate_sweep_side(direction, zone_center, sweep_extreme)

    entry = zone_center

    if direction == "buy":
        stop = _round_tick(sweep_extreme - 0.20 * atr_h1_14)
    else:
        stop = _round_tick(sweep_extreme + 0.20 * atr_h1_14)

    entry_t = _tick(entry)
    stop_t = _tick(stop)
    if direction == "buy":
        if stop_t >= entry_t:
            raise ValueError(f"computed stop ({stop}) is not below entry ({entry}) for direction='buy'")
    else:
        if stop_t <= entry_t:
            raise ValueError(f"computed stop ({stop}) is not above entry ({entry}) for direction='sell'")

    risk = _round_tick(abs(entry - stop))
    sweep_amplitude = abs(sweep_extreme - zone_center)

    # TP1: nearest-in-time confirmed swing on the reversal side (see
    # module docstring TP1 SELECTION / ASSUMPTIONS). Comparison against
    # entry is done in integer ticks (SWING SELECTION COMPARISON above).
    # Vectorized (numpy) instead of a per-row `.iloc[i]` Python loop --
    # same strict two-sided comparison, same N-candle edge bands (still
    # all False, unchanged, from find_swings), same tick-integer
    # comparison against entry; see tests/unit/test_risk_reward.py for
    # the brute-force equivalence tests.
    swings = find_swings(used, n=n)
    tp1 = None
    tp1_idx = None
    if direction == "buy":
        is_swing_high = swings["is_swing_high"].to_numpy()
        highs = used["high"].to_numpy()
        high_ticks = np.round(highs / TICK).astype(np.int64)
        candidate_idxs = np.flatnonzero(is_swing_high & (high_ticks > entry_t))
        if candidate_idxs.size:
            tp1_idx = int(candidate_idxs[-1])
            tp1 = float(highs[tp1_idx])
    else:
        is_swing_low = swings["is_swing_low"].to_numpy()
        lows = used["low"].to_numpy()
        low_ticks = np.round(lows / TICK).astype(np.int64)
        candidate_idxs = np.flatnonzero(is_swing_low & (low_ticks < entry_t))
        if candidate_idxs.size:
            tp1_idx = int(candidate_idxs[-1])
            tp1 = float(lows[tp1_idx])

    if tp1 is None:
        return RiskRewardResult(
            tradable=False,
            reason="tp1_unavailable",
            direction=direction,
            entry=entry,
            stop=stop,
            tp1=None,
            tp1_idx=None,
            tp2=None,
            sweep_amplitude=sweep_amplitude,
            risk=risk,
            reward_to_tp1=None,
            rr_to_tp1=None,
            reward_to_tp2=None,
            rr_to_tp2=None,
            atr_h1_14=atr_h1_14,
            sweep_extreme=sweep_extreme,
            zone_center=zone_center,
        )

    if direction == "buy":
        tp2 = tp1 + sweep_amplitude
    else:
        tp2 = tp1 - sweep_amplitude
    tp2 = _round_tick(tp2)

    reward_to_tp1 = _round_tick(abs(tp1 - entry))
    rr_to_tp1 = reward_to_tp1 / risk

    reward_to_tp2 = _round_tick(abs(tp2 - entry))
    rr_to_tp2 = reward_to_tp2 / risk

    risk_t = _tick(risk)
    reward_t = _tick(reward_to_tp2)
    rr_ok = reward_t >= 2 * risk_t

    return RiskRewardResult(
        tradable=rr_ok,
        reason="ok" if rr_ok else "rr_below_threshold",
        direction=direction,
        entry=entry,
        stop=stop,
        tp1=tp1,
        tp1_idx=tp1_idx,
        tp2=tp2,
        sweep_amplitude=sweep_amplitude,
        risk=risk,
        reward_to_tp1=reward_to_tp1,
        rr_to_tp1=rr_to_tp1,
        reward_to_tp2=reward_to_tp2,
        rr_to_tp2=rr_to_tp2,
        atr_h1_14=atr_h1_14,
        sweep_extreme=sweep_extreme,
        zone_center=zone_center,
    )
