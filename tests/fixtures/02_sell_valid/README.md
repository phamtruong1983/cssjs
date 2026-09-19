# Fixture 02 — SELL, valid signal

Mirror image of Fixture 01 (BUY valid), reflected around price `4000`
(`new_price = 4000 - old_price`) so the resistance-sweep-and-reject case
exercises the exact same arithmetic, thresholds, and margins. Resistance
zone instead of support; swing low (not high) is the reversal target.

## Structure (H1)

- idx 0–21: two fractal swing **highs** (N=3) at idx 5 and idx 17, both at
  `high = 2000.00` → 2 touches of the resistance zone. One fractal swing
  **low** at idx 11, `low = 1930.00`.
- Same TR/ATR construction as Fixture 01: `atr_h1_14 = 10.00` exactly at
  idx 22.
- idx 22: sweep candle. `open=1955, high=2035, low=1954, close=2000`.
  - `h1_range = 81` (>= 15 ✓)
  - `pierce_depth = high(2035) - zone_high(2000.5) = 34.5` (>= 2.5 ✓)
  - `close = 2000.0` inside `[1999.5, 2000.5]` → trap confirmed.
- idx 23: M15 reaction + entry-touch hour.

## Derived values

| Field | Value |
|---|---|
| `zone_center` | 2000.00 |
| `zone_low` / `zone_high` | 1999.50 / 2000.50 |
| `touch_count` | 2 |
| `atr_h1_14` | 10.00 |
| `sweep_extreme` | 2035.00 |
| `sweep_amplitude` | `abs(2035 - 2000) = 35.00` |
| `tp1` | 1930.00 (idx 11 swing low) |
| `entry` | 2000.00 |
| `stop` | `2035 + 0.20*10 = 2037.00` |
| `risk` | `2037 - 2000 = 37.00` |
| `tp2` | `1930 - 35 = 1895.00` |
| `rr1` | `70 / 37 = 1.89` |
| `rr2` | `105 / 37 = 2.84` (>= 2.0 ✓) |

## M15 reaction window (idx 23's hour)

Sweep extreme (`high = 2035`) is placed in the **last** M15 sub-candle of
the sweep hour (`22:45`), same "unambiguous under either reading"
construction as Fixture 01.

| Candle | close | body/range | close_position | passes? |
|---|---|---|---|---|
| 23:00 | 1999 | 1/4 = 0.25 | 0.25 | fails (body ratio < 0.30) |
| 23:15 | 1996 | 3/5 = 0.60 | (1996-1995)/5 = 0.20 | **fires** (close<2000, ratio>=0.30, close_position<=0.40) |

Reaction fires on the 2nd M15 candle, mirroring Fixture 01 exactly.

## Entry touch

idx 23 H1 range `[1985, 2002]` spans `entry = 2000.00` → touched within
the window. As with Fixture 01, this fixture stops at "entry touched," not
a full SL/TP resolution.

## Expected engine outcome

A signal with `status = "NEEDS_MANUAL_REVIEW"`, `direction = "sell"`.
