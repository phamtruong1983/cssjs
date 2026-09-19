# Fixture 01 — BUY, valid signal

Synthetic XAUUSD data. Support zone swept, H1 closes back inside the zone,
M15 reversal reaction fires, and price later touches the entry price. This
exercises the full happy path through `NEEDS_MANUAL_REVIEW`.

## Structure (H1, idx = row number, 0-indexed)

- idx 0–21: base price history. Two fractal swing lows (N=3) at
  idx 5 and idx 17, both at `low = 2000.00` → 2 touches of the same level.
  One fractal swing high (N=3) at idx 11, `high = 2070.00`.
- All bars idx 1–21 have `open == previous close` (no gaps) and
  `high - low == 10`, so True Range = 10 for every one of them. ATR(14)
  at idx 22 (computed from the 14 preceding bars) = **10.00 exactly**.
- idx 22: the sweep candle. `open=2045, high=2046, low=1965, close=2000`.
  - `h1_range = 81` (>= 1.5 * ATR = 15 ✓)
  - `pierce_depth = zone_low(1999.5) - low(1965) = 34.5` (>= 0.25 * ATR = 2.5 ✓)
  - `close = 2000.0` is inside `[zone_low, zone_high] = [1999.5, 2000.5]` → trap confirmed.
- idx 23: the hour where the M15 reaction fires and price also touches the
  entry price.

## Derived values

| Field | Value |
|---|---|
| `zone_center` | 2000.00 |
| `zone_low` / `zone_high` (width 1.00) | 1999.50 / 2000.50 |
| `touch_count` | 2 (idx 5, idx 17) |
| `atr_h1_14` | 10.00 |
| `sweep_extreme` | 1965.00 |
| `sweep_amplitude` | `abs(1965 - 2000) = 35.00` |
| `tp1` | 2070.00 (idx 11 swing high) |
| `entry` | 2000.00 |
| `stop` | `1965 - 0.20*10 = 1963.00` |
| `risk` | `2000 - 1963 = 37.00` |
| `tp2` | `2070 + 35 = 2105.00` |
| `rr1` | `70 / 37 = 1.89` |
| `rr2` | `105 / 37 = 2.84` (>= 2.0 ✓) |

## M15 reaction window (idx 23's hour, `m15.csv` rows 5–8)

The sweep extreme (idx 22 low = 1965) is placed in the **last** M15
sub-candle of the sweep hour (`22:45`), so "the M15 candles that follow
the sweep" are unambiguously the 4 candles of the next hour (`23:00`–
`23:45`) under either reading of the "after the sweep" wording in
`DAO_GAM_RULES.md` Section 4 — see the top-level chat note on this.

| Candle | close | body/range | close_position | passes? |
|---|---|---|---|---|
| 23:00 | 2001 | 1/4 = 0.25 | 0.75 | fails (body ratio < 0.30) |
| 23:15 | 2004 | 3/5 = 0.60 | (2004-2000)/5 = 0.80 | **fires** (a,b,c all pass) |
| 23:30 | (not reached) | | | |
| 23:45 | (not reached) | | | |

Note: the sweep hour's last M15 candle (`22:45`) is `open=1980, high=2000,
low=1965, close=2000` — the high was corrected to `2000` (from an earlier
draft's `1985`) because a candle cannot close above its own high; this was
caught by `tests/unit/test_data_schema.py`.

Reaction fires on the 2nd M15 candle → within the 4-candle limit.

## Entry touch

idx 23 H1 range is `[1998, 2015]`, which spans `entry = 2000.00` → the
order (a limit order at `zone_center`, per rules doc Section 5) is touched
within the validity window. This fixture stops here — it asserts entry is
touched, not a full SL/TP resolution (that is backtest-engine scope, not
yet built).

## Expected engine outcome (once implemented)

A signal with `status = "NEEDS_MANUAL_REVIEW"`, `direction = "buy"`, and
the level values above.
