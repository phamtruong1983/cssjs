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

- idx 23 (`22:00Z`→ mislabelled, actually `23:00Z` per `h1.csv`):
  `low = 2003`, stays **above** `entry = 2000.00` — no touch.
- idx 24 (`2024-01-03T00:00:00Z`): `low = 2010`, still above `2000.00` —
  no touch.

Per `DAO_GAM_RULES.md` Section 5, the validity window is "2 subsequent H1
candles" from the bar the order becomes active; this fixture uses idx 23
and idx 24 as that window (the inclusive-vs-exclusive counting question
noted in `docs/DATA_SCHEMA.md` Section 9 does not affect this fixture,
since price never touches `2000.00` in **either** candle regardless of
which two-candle window is used).

## Expected engine outcome

No trade. Logged with `status = "EXPIRED"`. Excluded from win-rate / R
statistics per `DAO_GAM_RULES.md` Section 5.
