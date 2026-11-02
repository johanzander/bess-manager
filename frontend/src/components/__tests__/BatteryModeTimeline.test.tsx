import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
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
  beforeEach(() => {
    localStorage.clear()
  })

  it('renders each quarter-period as its own segment instead of collapsing a mixed hour into one dominant-intent block', () => {
    mockLoading = false
    const { container } = render(<BatteryModeTimeline currentHour={0} />)

    // Two quarters LOAD_SUPPORT followed by two quarters BATTERY_EXPORT
    // within the same clock hour must render as two distinct colored
    // segments (one rect each), not merge into a single hour-block.
    const rects = container.querySelectorAll('[data-segment]')
    expect(rects.length).toBe(2)
  })

  it('keeps showing the already-loaded timeline during a background refresh instead of blanking to a skeleton', () => {
    // useDashboardData sets loading=true on every periodic refetch, not just
    // the very first one. If data from a prior fetch is already available,
    // the timeline must keep rendering it rather than flashing a skeleton
    // every 60 seconds.
    mockLoading = true
    const { container } = render(<BatteryModeTimeline currentHour={0} />)

    const rects = container.querySelectorAll('[data-segment]')
    expect(rects.length).toBe(2)
  })

  describe('layouts', () => {
    beforeEach(() => {
      mockLoading = false
    })

    it('defaults to the bar layout', () => {
      render(<BatteryModeTimeline currentHour={0} />)

      expect(screen.getByRole('tab', { name: 'Bar' })).toHaveAttribute('aria-selected', 'true')
    })

    it('remembers the chosen layout across remounts', () => {
      const { unmount } = render(<BatteryModeTimeline currentHour={0} />)
      fireEvent.click(screen.getByRole('tab', { name: 'Rows' }))
      unmount()

      render(<BatteryModeTimeline currentHour={0} />)

      expect(screen.getByRole('tab', { name: 'Rows' })).toHaveAttribute('aria-selected', 'true')
      expect(JSON.parse(localStorage.getItem('bess_user_preferences')!).scheduleLayout).toBe('rows')
    })

    it('list folds elapsed blocks away and marks the block in progress as Now', () => {
      localStorage.setItem('bess_user_preferences', JSON.stringify({ scheduleLayout: 'list' }))
      // 00:36 -- the LOAD_SUPPORT half-hour is over, BATTERY_EXPORT is running.
      const { container } = render(<BatteryModeTimeline currentHour={0.6} />)

      expect(screen.getByRole('button', { name: 'Show earlier today (1)' })).toBeInTheDocument()
      expect(container.querySelectorAll('li[data-segment]').length).toBe(1)
      expect(screen.getByText('Now')).toBeInTheDocument()

      fireEvent.click(screen.getByRole('button', { name: 'Show earlier today (1)' }))
      expect(container.querySelectorAll('li[data-segment]').length).toBe(2)
    })

    it('tapping a block shows its time range', () => {
      render(<BatteryModeTimeline currentHour={0} />)

      fireEvent.click(screen.getByRole('button', { name: 'Selling to Grid 00:30 to 01:00' }))

      expect(screen.getByText(/00:30–01:00/)).toBeInTheDocument()
    })

    it('keeps the block selected after a touch tap (mouseenter then click)', () => {
      render(<BatteryModeTimeline currentHour={0} />)
      const block = screen.getByRole('button', { name: 'Selling to Grid 00:30 to 01:00' })

      fireEvent.mouseEnter(block)
      fireEvent.click(block)

      expect(screen.getByText(/00:30–01:00/)).toBeInTheDocument()
    })
  })
})
