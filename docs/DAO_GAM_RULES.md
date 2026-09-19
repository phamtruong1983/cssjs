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
| 5 | Trap confirmation | `[V1_DECISION]` The H1 sweep candle must **close back inside the zone**. Additionally, M15 must show a defined "reversal reaction" — **definition pending, see Section 4, `NEEDS_APPROVAL`.** The "3 confirmation candles" rule is explicitly **not** used in V1, since the book's Dao Gam section does not specify it. | No code may implement the M15 check until Section 4 is approved. |
| 6 | Entry | `[V1_DECISION]` Signal is only created after the H1 candle that confirms the trap has **closed**. Entry price is a **reference price at the old zone** (i.e., the zone band from rule 3), not a market order and not a price chased far from the zone. | Backtest must treat entry as a limit-style reference at the zone, filled only if price later revisits it (see open question in Section 5). |
| 7 | Stop-loss | `[V1_DECISION]` Beyond the sweep candle's extreme, buffer = **0.20 × ATR(14)**. | Same ATR(14)/H1 series as rule 4. |
| 8 | Take-profit | `[V1_DECISION]` TP1 = nearest H1 swing high/low in the reversal direction. TP2 = `TP1 ± abs(extreme_sweep − key_zone_reference)` (sign per BUY/SELL direction). **Signal is discarded (not logged as tradable) unless R:R to TP2 ≥ 2.0.** | `key_zone_reference` = the zone boundary that was pierced (see Section 5 for the exact reference point to use, since the zone is a band not a single price). |
| 9 | "First/last 15 minutes of H1" | `[V1_DECISION]` **Not used as a filter in V1.** If M15 data is available, log which intra-hour bucket (0–15, 15–30, 30–45, 45–60 min) the confirming H1 close and the M15 reaction fall into, for the user's own offline review. | Purely observational logging, no gating logic. |
| 10 | Other indicators | `[V1_DECISION]` No MA, RSI, MACD, Bollinger Bands, or any other strategy layered into V1. | Detection uses only swing/fractal structure + ATR(14). |

## 4. M15 "reversal reaction" — definition, `NEEDS_APPROVAL`

**Status: not implemented. No code may reference or check this rule until
the user approves a specific definition below (or a revision of it).**

Purpose: after the H1 candle closes back inside the zone (trap confirmed
on H1), we want a lower-timeframe check that the reversal is actually
happening, rather than treating the H1 close alone as sufficient.

Proposed definition (draft, for the user to accept/reject/edit — labeled
`[INFERRED]`, not derived from the book):

> Reversal reaction (M15) = within the **first K completed M15 candles**
> after the confirming H1 candle's close, price prints **at least one M15
> candle** whose close moves **back toward the zone/away from the sweep
> extreme** by at least `X × ATR15(period)`, **without** any M15 candle in
> that window closing beyond the H1 sweep extreme (i.e., the trap is not
> invalidated by a fresh, deeper sweep on M15).

Open parameters inside this draft that also need the user's decision once
the general shape is approved:
- `K` — how many M15 candles constitute the confirmation window (candidate:
  K = 2, i.e. up to 30 minutes after the H1 close).
- `X` — minimum M15 close displacement, in ATR15 units (candidate: 0.3).
- Whether "closing beyond the H1 sweep extreme" invalidates the setup
  outright, or only downgrades confidence (V1 currently assumes outright
  invalidation — signal is not emitted, only logged as
  `REJECTED_M15_INVALIDATED` for audit).
- ATR period on M15 (candidate: same 14, i.e. ATR15(14), independent series
  from the H1 ATR(14) used elsewhere).

Until this section is approved, the pipeline may compute and log raw M15
values (closes, highs/lows, ATR15) for the confirmation window, but must
**not** use them to accept/reject a signal, and must not claim the M15
check has been "passed."

## 5. Open implementation questions (not blocking, tracked for later)

- Exact "touch" definition for the ≥2-touch zone rule (wick-based vs.
  close-based, tolerance band).
- Which zone boundary (near edge vs. center vs. far edge of the band) is
  `key_zone_reference` in the TP2 formula, and which edge is the entry
  reference price.
- In backtest, how an "entry at the zone" reference price is treated if
  price never returns exactly to it after the confirming H1 close (does
  the signal expire, and after how long).

## 6. Signal status and output contract (V1)

- Every emitted signal has `status = "NEEDS_MANUAL_REVIEW"`. V1 output must
  never be labeled a recommendation or a certain trade.
- Every signal record includes a `reason` field (human-readable) and the
  concrete rule values that triggered it (zone bounds, ATR(14) value,
  range multiple, pierce depth, sweep extreme, R:R to TP2, D1/H4 structure
  snapshot, tick-volume snapshot if available, M15 bucket timing).
- Output formats: JSON, console log, and CSV log — all three, same signal
  data.
- No broker connectivity, no order placement, no auto trading in V1.
