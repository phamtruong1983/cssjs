# Fixture 04 — M15 confirms, entry never touched → EXPIRED

Same base history, zone, ATR, and sweep candle as Fixture 01 (idx 0–22
identical). The M15 reaction **does** fire in the following hour, but
price never trades back down to `entry = zone_center = 2000.00` during the
subsequent H1 candles — the resting limit order expires.

## M15 window (idx 23's hour, `23:00`–`23:45`)

| Candle | close | body/range | close_position | passes? |
|---|---|---|---|---|
| 23:00 | 2004 | 1/7 = 0.14 | (2004-2003)/7=0.14 | fails |
| 23:15 | 2010 | 6/9 = 0.667 | (2010-2003)/9=0.778 | **fires** (a,b,c all pass) |

Reaction fires on the 2nd M15 candle, exactly like Fixture 01 — this
fixture is not testing the M15 rule, it's testing the entry-expiry rule.

Note: the sweep hour's last M15 candle (`22:45`) is `open=1980, high=2000,
low=1965, close=2000` (same correction as Fixture 01/03; caught by
`tests/unit/test_data_schema.py`).

## H1 bars after activation

- idx 23: the **activation bar** (M15 reaction fires there). Per
  `DAO_GAM_RULES.md` Section 5 (`[V1_DECISION]`, resolved), this bar does
  **not** count toward the validity window.
- idx 24 (`2024-01-03T00:00:00Z`, window candle 1): `low = 2010`, stays
  above `entry = 2000.00` — no touch.
- idx 25 (`2024-01-03T01:00:00Z`, window candle 2): `low = 2015`, still
  above `2000.00` — no touch.

The validity window is exactly `{idx 24, idx 25}` (activation bar idx 23
excluded, per the resolved rule in `docs/DATA_SCHEMA.md` Section 9). Price
never touches `2000.00` in either window candle.

## Expected engine outcome

No trade. Logged with `status = "EXPIRED"`. Excluded from win-rate / R
statistics per `DAO_GAM_RULES.md` Section 5.
