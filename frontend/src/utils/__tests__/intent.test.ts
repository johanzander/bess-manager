import { describe, it, expect } from 'vitest'
import { getIntent } from '../intent'

describe('getIntent', () => {
  it('prefers observedIntent over strategicIntent for actual periods', () => {
    // strategicIntent defaults to IDLE on the backend when no DP plan covered
    // the period, even though the period really did something (observedIntent
    // reflects the real sensor-derived outcome). See battery_system_manager.py's
    // `planned_intent or "IDLE"`.
    expect(
      getIntent({ dataSource: 'actual', strategicIntent: 'IDLE', observedIntent: 'BATTERY_EXPORT' })
    ).toBe('BATTERY_EXPORT')
  })

  it('falls back to strategicIntent for actual periods with no observedIntent', () => {
    expect(
      getIntent({ dataSource: 'actual', strategicIntent: 'LOAD_SUPPORT', observedIntent: undefined })
    ).toBe('LOAD_SUPPORT')
  })

  it('ignores observedIntent for predicted periods', () => {
    // Predicted/future periods shouldn't have observedIntent, but even if
    // present it must not override the plan for a period that hasn't happened.
    expect(
      getIntent({ dataSource: 'predicted', strategicIntent: 'SOLAR_STORAGE', observedIntent: 'BATTERY_EXPORT' })
    ).toBe('SOLAR_STORAGE')
  })

  it('defaults to IDLE when no intent is present', () => {
    expect(getIntent({})).toBe('IDLE')
  })
})
