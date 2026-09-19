# Fixture 05 — R:R to TP2 below 2.0 → RR_BELOW_THRESHOLD

Same base history and zone as Fixture 01 (`tp1 = 2070.00`, `atr_h1_14 =
10.00`), but the sweep goes much deeper, which lowers `rr2` below the
Section 3 rule 8 threshold even though the H1 trap confirms and the M15
reaction fires (identical M15 candles to Fixture 01, reused here so this
fixture is unambiguously about the R:R gate, not the M15 rule).

## Sweep candle (idx 22)

`open=2045, high=2046, low=1920, close=2000`.
- `h1_range = 126` (>= 15 ✓), `pierce_depth = 1999.5 - 1920 = 79.5` (>= 2.5 ✓)
- `close = 2000.0` inside the zone → trap confirmed.

## Derived values

| Field | Value |
|---|---|
| `sweep_extreme` | 1920.00 |
| `sweep_amplitude` | `abs(1920 - 2000) = 80.00` |
| `tp1` | 2070.00 (unchanged from Fixture 01) |
| `entry` | 2000.00 |
| `stop` | `1920 - 0.20*10 = 1918.00` |
| `risk` | `2000 - 1918 = 82.00` |
| `tp2` | `2070 + 80 = 2150.00` |
| `rr1` | `70 / 82 = 0.85` |
| `rr2` | `150 / 82 = 1.83` — **below the 2.0 threshold** |

## M15 reaction

Note: the sweep hour's last M15 candle (`22:45`) is `open=1960, high=2000,
low=1920, close=2000` (same OHLC correction as Fixture 01; caught by
`tests/unit/test_data_schema.py`).

Reuses Fixture 01's idx-23 M15 candles exactly; the reaction fires on the
2nd candle (`23:15`). Included so this fixture demonstrates the RR gate
applies **regardless of whether the R:R check happens before or after the
M15 check** — `DAO_GAM_RULES.md` does not specify that ordering, so this
fixture does not depend on it.

## Expected engine outcome

No tradable signal. Logged with `status = "RR_BELOW_THRESHOLD"` (per
`DAO_GAM_RULES.md` Section 6, exact string `RR_BELOW_THRESHOLD` — not
`REJECTED_RR_BELOW_THRESHOLD`; flagging this naming detail since the task
brief that requested this fixture used the latter spelling).
