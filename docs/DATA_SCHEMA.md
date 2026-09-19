# Dao Gam V1 — Data Schema

Companion to `docs/DAO_GAM_RULES.md`. Describes the concrete data shapes
used by the (not-yet-built) signal engine and backtest, and by the test
fixtures in `tests/fixtures/`. This document does not add or change any
V1 rule — it only formalizes field names, types, and units for rules
already locked in `DAO_GAM_RULES.md`.

## 1. OHLCV bar schema (H1 and M15)

Both timeframes share the same row schema; `timeframe` distinguishes them.

| Field | Type | Notes |
|---|---|---|
| `timestamp` | ISO 8601 datetime, UTC | See Section 2. |
| `symbol` | string | `"XAUUSD"` for V1 (single instrument, per rules doc scope). |
| `timeframe` | string enum: `"H1"`, `"M15"` | |
| `open` | float | |
| `high` | float | Must be `>= max(open, close, low)`. |
| `low` | float | Must be `<= min(open, close, high)`. |
| `close` | float | |
| `volume` | float, nullable | Tick volume if the feed provides it. **Not a required field and not a required condition** — per `DAO_GAM_RULES.md` Section 3 rule 2, missing or `0` is valid and must never reject a bar or a signal. Log it when present, informational only. |

An H1 bar's OHLC must be consistent with its four constituent M15 bars when
both are present for the same hour: `H1.open == M15[0].open`,
`H1.close == M15[3].close`, `H1.high == max(M15[i].high)`,
`H1.low == min(M15[i].low)`. Fixtures in this repo are constructed to
satisfy this exactly.

## 2. Timestamp and timezone

- All timestamps are stored in **UTC**, ISO 8601 (`YYYY-MM-DDTHH:MM:SSZ`).
- A timestamp marks the **open** time of the bar (H1 bar `08:00:00Z` covers
  `[08:00, 09:00)`).
- H1 timestamps must align to the top of the hour (`minute == 0`).
- M15 timestamps must align to `:00`, `:15`, `:30`, `:45` of each hour.
- Within a `(symbol, timeframe)` series, timestamps must be **strictly
  increasing** — no duplicates, no out-of-order rows. (Gaps, e.g. weekend
  closures, are allowed; only ordering and duplication are checked.)

## 3. Instrument metadata

| Field | V1 value | Notes |
|---|---|---|
| `symbol` | `XAUUSD` | Fixed for V1 per `DAO_GAM_RULES.md` scope. |
| `tick_size` | `0.01` | Minimum price increment for XAUUSD on a typical retail feed. |
| `point_size` | `0.01` | The "point" unit used when a rule is expressed in points; for XAUUSD this equals `tick_size`. All ATR/zone/buffer values in this schema are plain price units (e.g. `1.00` = 100 points = 1 full dollar move), not pips. |

`tick_size`/`point_size` are fixture/instrument configuration, not
`[V1_DECISION]` trading rules — they describe the data, not the strategy.

## 4. Zone fields (support/resistance)

Per `DAO_GAM_RULES.md` Section 3 rule 3: a zone is a band, not a single
price.

| Field | Type | Definition |
|---|---|---|
| `zone_low` | float | `zone_center - zone_width / 2` |
| `zone_center` | float | The fractal swing high/low price (N=3) that anchors the zone. |
| `zone_high` | float | `zone_center + zone_width / 2` |
| `zone_width` | float | Configurable (rules doc leaves the exact value open). **Fixture convention for V1 test data: `zone_width = 1.00`** (documented per-fixture; this is an implementation/fixture choice, not a `[V1_DECISION]` — the rules doc explicitly allows pinning this in code without separate approval). |
| `touch_count` | integer | Number of prior fractal swing points (same side) whose price falls within `[zone_low, zone_high]`. Must be `>= 2` for the zone to qualify (rules doc Section 3 rule 3). |
| `touch_definition` | string, fixed | **Fixture/implementation convention (not requiring separate approval per rules doc Section 3 rule 3 note): a "touch" is a fractal swing point (high or low, matching the zone's side) whose wick price lies within `[zone_low, zone_high]`.** |

## 5. Sweep fields

| Field | Type | Definition |
|---|---|---|
| `sweep_extreme` | float | The low (support case) or high (resistance case) of the H1 candle that pierces the zone. Per `DAO_GAM_RULES.md` Section 3 rule 4. |
| `sweep_amplitude` | float | `abs(sweep_extreme - zone_center)`. Per Section 3 rule 8 / Section 5. |
| `atr_h1_14` | float | ATR(14) computed on H1, the reference unit for the range/pierce/buffer thresholds (Section 3 rule 4, rule 7). |
| `h1_range` | float | `high - low` of the sweep candle; rule requires `>= 1.5 * atr_h1_14`. |
| `pierce_depth` | float | Distance the extreme moved past the zone boundary; rule requires `>= 0.25 * atr_h1_14`. |

## 6. Trade level fields

| Field | Type | Definition |
|---|---|---|
| `direction` | string enum: `"buy"`, `"sell"` | |
| `entry` | float | `= zone_center`. Limit-order reference price (Section 5) — never a market fill, never the H1 close. |
| `stop` | float | `sweep_extreme -/+ 0.20 * atr_h1_14` (minus for buy, plus for sell). Section 3 rule 7. |
| `tp1` | float | Nearest H1 swing high/low in the reversal direction. Section 3 rule 8. |
| `tp2` | float | `tp1 +/- sweep_amplitude` (plus for buy, minus for sell), referenced from `zone_center` per Section 3 rule 8 / Section 5. |
| `risk` | float | `abs(entry - stop)`. |
| `rr1` | float | `abs(tp1 - entry) / risk`. |
| `rr2` | float | `abs(tp2 - entry) / risk`. Signal requires `rr2 >= 2.0` (Section 3 rule 8) to be logged as tradable. |

## 7. M15 reaction fields (per candle evaluated in the confirmation window)

Per `DAO_GAM_RULES.md` Section 4.

| Field | Type | Definition |
|---|---|---|
| `m15_index_in_window` | integer, 1–4 | Position of this M15 candle within the up-to-4-candle confirmation window. |
| `body_size` | float | `abs(close - open)`. |
| `candle_range` | float | `high - low`. |
| `close_position_in_range` | float, 0–1 | `(close - low) / (high - low)`. |
| `reaction_fired` | boolean | Whether this candle satisfies all of conditions a–d for the setup's direction. |

## 8. Signal / audit record status

Every record (whether a tradable signal or a rejected/expired candidate)
carries one `status` value:

| Status | Meaning | Source |
|---|---|---|
| `NEEDS_MANUAL_REVIEW` | A fully confirmed, tradable V1 signal. Never a recommendation or certain trade. | `DAO_GAM_RULES.md` Section 6. |
| `REJECTED_M15_NO_REACTION` | H1 trap confirmed, but no M15 candle in the 4-candle window satisfied the reversal-reaction conditions. | Section 4 / Section 6. |
| `EXPIRED` | H1 + M15 confirmed, limit order posted at `zone_center`, but price never traded there within the 2-H1-candle validity window. Not counted as a trade. | Section 5 / Section 6. |
| `RR_BELOW_THRESHOLD` | Setup fully confirmed but R:R to TP2 `< 2.0`. | Section 3 rule 8 / Section 6. |

**Not a named status:** a candle that pierces the zone with sufficient
range/depth but does **not** close back inside the zone is, per the rules
doc, simply not a trap — Section 6 does not define an audit status for
this case. Fixture 7 (below) exercises this: the expected outcome is
"no signal, no rejection record with one of the above statuses" — whether
a future implementation additionally logs some other kind of
"candidate, never confirmed" audit trail is an open implementation
question, not specified here.

Every record also carries the fields listed in `DAO_GAM_RULES.md` Section
6 (`reason`, zone bounds, ATR value, range multiple, pierce depth,
`sweep_extreme`, `sweep_amplitude`, M15 reaction candle values, R:R to
TP1/TP2, D1/H4 structure snapshot, tick-volume snapshot if available,
intra-hour bucket for both the H1 confirmation and the M15 reaction).

## 9. Open question carried over from fixture construction

`DAO_GAM_RULES.md` Section 5 says the entry/SL validity window is "2
subsequent H1 candles ... from the bar the order becomes active," without
saying whether that count includes the activating bar itself or starts
strictly after it. This does not block the fixtures in this repo (see
`tests/fixtures/06_same_bar_entry_sl_conflict/README.md`), but it is
**not yet resolved** and must be pinned down before the entry/expiry logic
is implemented in code.
