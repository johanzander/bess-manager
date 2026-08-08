import { describe, it, expect } from 'vitest'
import { getIntent, isCurtailed } from '../intent'

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

describe('isCurtailed', () => {
  it('is true for a SOLAR_EXPORT period the backend flagged as curtailed', () => {
    expect(
      isCurtailed({ dataSource: 'predicted', strategicIntent: 'SOLAR_EXPORT', curtailed: true })
    ).toBe(true)
  })

  it('is false for a SOLAR_EXPORT period the backend did not flag as curtailed', () => {
    expect(
      isCurtailed({ dataSource: 'predicted', strategicIntent: 'SOLAR_EXPORT', curtailed: false })
    ).toBe(false)
  })

  it('is true for a curtailed period even when the intent is SOLAR_STORAGE', () => {
    // Regression: a period still charging at its rate limit while the
    // surplus above that rate is curtailed classifies as SOLAR_STORAGE, not
    // SOLAR_EXPORT (battery_system_manager.py's should_curtail condition
    // applies "regardless of strategic_intent") -- isCurtailed must not
    // silently drop this case by gating on intent.
    expect(
      isCurtailed({ dataSource: 'predicted', strategicIntent: 'SOLAR_STORAGE', curtailed: true })
    ).toBe(true)
  })

  it('is false when curtailed is not set', () => {
    expect(
      isCurtailed({ dataSource: 'predicted', strategicIntent: 'IDLE' })
    ).toBe(false)
  })
})
