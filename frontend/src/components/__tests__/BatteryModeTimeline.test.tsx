import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import { BatteryModeTimeline } from '../BatteryModeTimeline'

// Regression tests for #486: the timeline color bar must always reflect true
// quarter-level intent, never an hourly "dominant intent" approximation —
// that approximation is what let a stale planned BATTERY_EXPORT outvote a
// genuinely observed LOAD_SUPPORT for an elapsed hour. The component now
// fetches its own quarter-hourly data instead of receiving page-resolution-
// dependent hourlyData/resolution props.
const quarters = [0, 1, 2, 3].map((period) => ({
  period,
  dataSource: 'actual',
  strategicIntent: period < 2 ? 'LOAD_SUPPORT' : 'BATTERY_EXPORT',
  observedIntent: period < 2 ? 'LOAD_SUPPORT' : 'BATTERY_EXPORT',
}))

let mockLoading = false

vi.mock('../../hooks/useDashboardData', () => ({
  useDashboardData: () => ({
    data: {
      currentPeriod: 0,
      hourlyData: quarters,
      tomorrowData: null,
      summary: {},
    },
    loading: mockLoading,
    error: null,
    refetch: vi.fn(),
  }),
}))

describe('BatteryModeTimeline', () => {
  it('renders each quarter-period as its own segment instead of collapsing a mixed hour into one dominant-intent block', () => {
    mockLoading = false
    const { container } = render(<BatteryModeTimeline currentHour={0} />)

    // Two quarters LOAD_SUPPORT followed by two quarters BATTERY_EXPORT
    // within the same clock hour must render as two distinct colored
    // segments (one rect each), not merge into a single hour-block.
    const rects = container.querySelectorAll('rect')
    expect(rects.length).toBe(2)
  })

  it('keeps showing the already-loaded timeline during a background refresh instead of blanking to a skeleton', () => {
    // useDashboardData sets loading=true on every periodic refetch, not just
    // the very first one. If data from a prior fetch is already available,
    // the timeline must keep rendering it rather than flashing a skeleton
    // every 60 seconds.
    mockLoading = true
    const { container } = render(<BatteryModeTimeline currentHour={0} />)

    const rects = container.querySelectorAll('rect')
    expect(rects.length).toBe(2)
  })
})
