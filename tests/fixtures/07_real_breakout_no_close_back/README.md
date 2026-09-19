# Fixture 07 — Real breakout, no close back inside the zone → no signal

Same base history and zone as Fixture 01 (idx 0–21 identical: touches at
idx 5 and idx 17, `zone_center = 2000.00`, `atr_h1_14 = 10.00`). The final
candle (idx 22) pierces the zone by a wide margin, satisfying the raw
range/pierce thresholds, but is a genuine breakout: it does **not** close
back inside the zone.

## Candle (idx 22)

`open=2045, high=2050, low=1965, close=1980`.
- `h1_range = 85` (>= 1.5 * 10 = 15 ✓)
- `pierce_depth = 1999.5 - 1965 = 34.5` (>= 0.25 * 10 = 2.5 ✓)
- `close = 1980.0` — **below** `zone_low = 1999.5`, i.e. still outside the
  zone. Trap confirmation (`DAO_GAM_RULES.md` Section 3 rule 5 / Section 2)
  requires the candle to close back **inside** the zone; this fails that
  check.

## Expected engine outcome

**No signal.** Per `docs/DATA_SCHEMA.md` Section 8, the rules doc does not
define a named rejection status for "pierced but didn't close back in the
zone" — this is not the same as `REJECTED_M15_NO_REACTION` (that status
presupposes the H1 trap already confirmed). This fixture only asserts:
no record with `status = "NEEDS_MANUAL_REVIEW"` is produced from this
candle. Whether a future implementation also logs some other
"candidate seen but not confirmed" audit row is an open implementation
question, not specified in the rules doc, and this fixture takes no
position on it.

No M15 data is needed for this fixture — the setup is rejected at the H1
stage, before any M15 check would run.
