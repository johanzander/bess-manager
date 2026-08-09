import { describe, it, expect } from 'vitest'
import { formatFixed } from '../format'

describe('formatFixed', () => {
  // A locally-summed total (e.g. a day's export revenue across several
  // near-zero curtailed periods) can land on a tiny negative float that
  // rounds to zero -- must never display as "-0.00".
  it('never shows negative zero for a value that rounds to zero', () => {
    expect(formatFixed(-0.0004, 2)).toBe('0.00')
  })

  it('leaves a real negative value unaffected', () => {
    expect(formatFixed(-1.5, 2)).toBe('-1.50')
  })

  it('leaves a real positive value unaffected', () => {
    expect(formatFixed(1.5, 2)).toBe('1.50')
  })

  it('respects the requested precision', () => {
    expect(formatFixed(-0.00001, 1)).toBe('0.0')
  })
})
