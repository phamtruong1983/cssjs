# Dao Gam (Dagger) V1 — Rule Specification

Scope of V1: signal engine + backtest only. No broker connection, no auto
trade, no order placement. Single instrument: XAUUSD. Setup detection on
H1, confirmation check on M15.

Labels:
- `[EXTRACTED]` — stated directly in "Forex Sinh Tu Ky Thu - Tap 2", chapter
  "Dao Gam - Bay Gia Ao".
- `[INFERRED]` — quantified/formalized by us so the pattern is machine
  checkable; not literally in the book.
- `[V1_DECISION]` — parameter value the user has explicitly chosen for V1.

---

## 1. Core pattern (mechanics)

- `[EXTRACTED]` Timeframe for setup detection: H1. The book states H1 is
  the most effective window because it's short enough for a shark to
  manipulate price yet is where ~90% of retail intraday traders operate.
- `[EXTRACTED]` Precondition: a prior strong impulsive move has established
  a clear support/resistance level (example in the book: a sharp drop that
  hits a support zone and bounces).
- `[EXTRACTED]` Sequence:
  1. Price returns to the previously established level.
  2. A high-range ("giat manh") candle pierces through the level.
  3. The crowd standing on the sidelines piles in, all in the direction of
     the piercing move (breakout traders).
  4. Price snaps back hard, sweeping through the stop-loss cluster the
     crowd just placed.
- `[EXTRACTED]` Entry: at the pierced level itself (the retest zone), not
  chasing price. Book example: support 25.200, entry 25.200–25.300.
- `[EXTRACTED]` Stop-loss: beyond the extreme of the sweep candle, by a
  margin (book example: sweep low 25.000, SL 24.950 → 50-price buffer).
- `[EXTRACTED]` Amplitude measurement: distance from the sweep extreme to
  the broken level, used later for TP2.
- `[EXTRACTED]` Two take-profit levels:
  - TP1 = nearest prior swing point on the reversal side (book example:
    25.950).
  - TP2 = TP1 + amplitude (book example: 25.950 + 600 = 26.550).
- `[EXTRACTED]` Exit rule: "you entered because of X, so exit because of
  X" — once price has completed the sweep of the nearest prior swing
  point, take the trade off; don't expect more.
- `[EXTRACTED]` The edge is explicitly **not** technical analysis
  (candles/levels/indicators) but reading crowd psychology and where stop
  clusters sit.
- `[EXTRACTED]` The book flags this as a high-risk ("mao hiem") technique,
  meant for strongly trending/volatile conditions, not applied blindly at
  all times.
- `[EXTRACTED]` The book mentions "pay attention to the first 15 minutes
  and last 15 minutes of the H1 candle" with no further specification of
  how to use it.

## 2. Quantification added for machine detection

- `[INFERRED]` "Strong support/resistance zone" = fractal-style swing
  high/low (N candles on each side), not a single hand-picked price on a
  chart.
- `[INFERRED]` "Strong sweep candle" = candle range relative to ATR(14) on
  H1, plus a minimum pierce depth relative to ATR(14). The book only says
  "giat manh" (a sharp jerk) with no numeric threshold.
- `[INFERRED]` "Trap confirmation" = the H1 candle must close back inside
  the zone after piercing it. The book shows this via a single chart
  example without a numeric closing tolerance.
- `[INFERRED]` Zones (not single price levels) with a configurable width,
  and a minimum touch count, to reduce false positives from a level that
  was only ever tested once. Not specified in the book.
- `[INFERRED]` A confirmation check on a lower timeframe (M15) that the
  reversal is real, beyond the H1 close alone. The book does not describe
  a lower-timeframe confirmation step at all — this is added for V1
  because pure H1-close confirmation was judged too noisy to backtest
  meaningfully. **This sub-rule needs a precise definition — see Section 4,
  marked `NEEDS_APPROVAL`.**
- `[INFERRED]` Minimum reward:risk gate on TP2 to filter marginal setups.
  Not in the book.

## 3. V1 decisions (locked parameters)

| # | Parameter | V1 value | Notes |
|---|---|---|---|
| 1 | D1/H4 trend filter | `[V1_DECISION]` **OFF** for V1 (no setups are rejected on trend grounds). D1/H4 structure (e.g. last swing high/low, direction) is still computed and written to the log for later offline analysis. | Not used as a gate in V1. |
| 2 | Volume spike | `[V1_DECISION]` **Not a required condition.** If the data source provides tick volume, log it (raw value + ratio to a rolling average) on every signal, but never reject a signal for volume. | XAUUSD tick volume via most retail feeds is a liquidity proxy, not real traded volume — treated as informational only. |
| 3 | Support/resistance zone | `[V1_DECISION]` Fractal swing high/low, **N = 3** candles each side, on H1. A level only qualifies as a "strong" zone if it has **≥ 2 prior touches**. The zone is a **band**, not one price: `[zone_center − zone_width/2, zone_center + zone_width/2]`, with `zone_width` configurable (in ATR(14) units or absolute price, to be set at implementation time). | "Touch" definition (wick vs. close, tolerance) to be pinned down in code but does not need separate approval — it follows directly from the zone band above. |
| 4 | Sweep candle | `[V1_DECISION]` ATR(14) computed on H1. Candle range must be **≥ 1.5 × ATR(14)**. The extreme (high for a resistance test, low for a support test) must pierce the zone boundary by **≥ 0.25 × ATR(14)**. | Both thresholds are user-locked for V1, not to be auto-tuned. |
| 5 | Trap confirmation | `[V1_DECISION]` The H1 sweep candle must **close back inside the zone**. Additionally, M15 must show the "reversal reaction" defined in Section 4 (fully specified, `[V1_DECISION]`, no longer pending). The "3 confirmation candles" rule is explicitly **not** used in V1, since the book's Dao Gam section does not specify it. | See Section 4 for the exact M15 conditions and the max-wait window. |
| 6 | Entry | `[V1_DECISION]` Signal is only created after the H1 candle that confirms the trap has **closed** AND the M15 reversal reaction (Section 4) has fired. Entry model is a **limit-order simulation at `zone_center`** (see Section 5 for the full fill/expiry logic) — never a market order, never the H1 close price. | Backtest must simulate this as a resting limit order, not an immediate fill. |
| 7 | Stop-loss | `[V1_DECISION]` Beyond the sweep candle's extreme, buffer = **0.20 × ATR(14)**. | Same ATR(14)/H1 series as rule 4. |
| 8 | Take-profit | `[V1_DECISION]` TP1 = nearest H1 swing high/low in the reversal direction. `key_zone_reference = zone_center` (chosen over near/far edge to avoid bias from variable zone width; `zone_low`/`zone_center`/`zone_high` are all stored on the signal for later sensitivity analysis). `sweep_amplitude = abs(sweep_extreme − zone_center)`. TP2 = `TP1 + sweep_amplitude` for BUY, `TP1 − sweep_amplitude` for SELL. **Signal is discarded (not logged as tradable) unless R:R to TP2 ≥ 2.0** (R:R computed against the `zone_center` entry price from rule 6/Section 5). | Formula and reference point are final for V1. |
| 9 | "First/last 15 minutes of H1" | `[V1_DECISION]` **Not used as a filter in V1.** If M15 data is available, log which intra-hour bucket (0–15, 15–30, 30–45, 45–60 min) the confirming H1 close and the M15 reaction fall into, for the user's own offline review. | Purely observational logging, no gating logic. |
| 10 | Other indicators | `[V1_DECISION]` No MA, RSI, MACD, Bollinger Bands, or any other strategy layered into V1. | Detection uses only swing/fractal structure + ATR(14). |

## 4. M15 "reversal reaction" — definition, `[V1_DECISION]` (approved)

**Status: fully specified and approved for V1. This is a `[V1_DECISION]`,
not a rule stated verbatim in the book** — the book does not describe any
lower-timeframe confirmation step; this section formalizes what "reversal
reaction" means so it can be checked mechanically.

Purpose: after the H1 candle closes back inside the zone (trap confirmed
on H1), require a lower-timeframe check that the reversal is actually
underway, rather than treating the H1 close alone as sufficient.

Common terms:
- `zone_center` — the midpoint of the support/resistance zone band (Section
  3, rule 3).
- `sweep_extreme` — the high (resistance case) or low (support case) of the
  H1 sweep candle.
- `body_size` — `abs(close − open)` of the M15 candle.
- `candle_range` — `high − low` of the M15 candle.
- `close_position_in_range` — `(close − low) / (high − low)` for the M15
  candle (0 = closed at the low, 1 = closed at the high).

**BUY case** (price swept below the zone, looking for upward reversal):

After the sweep, scan the M15 candles that follow, up to a maximum of
**4 M15 candles** (1 hour). The reversal reaction fires on the **first**
M15 candle in that window whose close satisfies **all** of:
  a) `close > zone_center`
  b) `body_size / candle_range >= 0.30`
  c) `close_position_in_range >= 0.60`
  d) not a doji (excluded by condition b/c already requiring a real body
     closing in the upper part of its range — no separate doji filter
     needed beyond a) through c))

If no M15 candle within the 4-candle window satisfies all conditions, the
setup is invalidated: no signal is emitted, and it is logged as
`REJECTED_M15_NO_REACTION`.

**SELL case** (price swept above the zone, looking for downward reversal):
mirror image of the BUY case, over the same 4-candle window:
  a) `close < zone_center`
  b) `body_size / candle_range >= 0.30`
  c) `close_position_in_range <= 0.40`
  d) same note as BUY(d) — no separate doji filter needed.

Additional V1 decisions for this section:
- Engulfing pattern is **not required** in V1.
- Tick volume is **not** a condition here either (consistent with Section
  3, rule 2) — log it if available, never gate on it.
- ATR15 is **not used** in this definition (superseded by the
  body/range-ratio and close-position conditions above); no separate
  ATR15 series needs to be computed for this check.
- The pipeline must always log the raw M15 candles evaluated in the
  window (OHLC, body_size, candle_range, close_position_in_range) whether
  or not the reaction fires, for later review.

## 5. Entry model — limit-order simulation, `[V1_DECISION]` (approved)

`key_zone_reference` (Section 3 open question) is resolved: **`zone_center`**
is used both as the TP2 reference (Section 3, rule 8) and as the entry
price below. This is a `[V1_DECISION]`, not a rule from the book.

- Entry price = **`zone_center`**. No market order, no fill at the H1 close
  price.
- The resting limit order becomes active only after: H1 sweep candle
  closed back inside the zone **AND** the M15 reversal reaction (Section
  4) has fired.
- **Validity window: 2 subsequent H1 candles (2 hours)** from the bar the
  order becomes active. If price does not trade at `zone_center` within
  that window, the order is marked **`EXPIRED`** and is **not counted as a
  trade** (excluded from win rate / R-multiple stats, logged separately for
  audit).
- **Same-bar SL-before-entry:** if, on an H1 candle within the validity
  window, price touches both `zone_center` (entry) and the stop-loss level,
  and there is no intrabar (sub-H1) data to establish order, treat it
  **conservatively as no fill** — the order is not considered triggered on
  that bar (it may still fill on a later bar within the window, if the SL
  level was not also breached in the meantime; if the SL level was already
  invalidated, the order expires/rejects — see note below).
- **Same-bar SL-vs-TP after entry:** once filled, if a later H1 (or M15,
  for the parts of the trade managed intrabar) candle touches both the
  stop-loss and a take-profit level with no intrabar ordering data
  available, assume **SL happens first** (conservative resolution).
- No market orders anywhere in this model; no use of H1 close price as a
  fill price at any stage.

Remaining implementation-detail (non-blocking, does not require separate
approval before coding, but noted for transparency):
- Exact "touch" definition for the ≥2-touch zone rule (wick-based vs.
  close-based, tolerance band) — to be pinned down in code following the
  zone-band definition in Section 3, rule 3.

## 6. Signal status and output contract (V1)

- Every emitted, tradable signal has `status = "NEEDS_MANUAL_REVIEW"`. V1
  output must never be labeled a recommendation or a certain trade.
- Non-tradable outcomes are logged (for audit, not as signals) with their
  own status, at minimum:
  - `REJECTED_M15_NO_REACTION` — H1 trap confirmed, but no M15 candle
    within the 4-candle window satisfied the reversal-reaction conditions
    (Section 4).
  - `EXPIRED` — H1 + M15 confirmed, limit order posted at `zone_center`,
    but price never traded there within the 2-H1-candle validity window
    (Section 5).
  - `RR_BELOW_THRESHOLD` — setup fully confirmed but R:R to TP2 < 2.0
    (Section 3, rule 8).
- Every record (signal or rejected/expired) includes a `reason` field
  (human-readable) and the concrete rule values that produced it: zone
  bounds (`zone_low`/`zone_center`/`zone_high`), touch count, ATR(14)
  value, H1 range multiple, pierce depth, `sweep_extreme`,
  `sweep_amplitude`, the M15 reaction candle's OHLC/body/close-position
  values, R:R to TP1 and TP2, D1/H4 structure snapshot, tick-volume
  snapshot if available, and the intra-hour bucket (0–15/15–30/30–45/45–60
  min) for both the H1 confirmation and the M15 reaction.
- Output formats: JSON, console log, and CSV log — all three, same
  underlying record (signals and rejected/expired entries alike).
- No broker connectivity, no order placement, no auto trading in V1.
