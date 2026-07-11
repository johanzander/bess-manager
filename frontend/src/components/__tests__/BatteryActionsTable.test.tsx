import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BatteryActionsTable } from '../BatteryActionsTable'

const fv = (value: number, display: string, unit = 'kWh') => ({
  value,
  display,
  unit,
  text: `${display} ${unit}`,
})

const baseHour = {
  period: 86,
  dataSource: 'actual',
  batteryCharged: fv(0, '0.00'),
  batteryDischarged: fv(0.84, '0.84'),
  batterySocEnd: fv(50, '50'),
  batterySoeEnd: fv(7.3, '7.3'),
  gridImported: fv(0, '0.00'),
  gridExported: fv(0.04, '0.04'),
  gridToHome: fv(0, '0.00'),
  gridToBattery: fv(0, '0.00'),
  solarToBattery: fv(0, '0.00'),
  solarToGrid: fv(0, '0.00'),
  batteryToHome: fv(0.8, '0.80'),
  // Below the frontend's old 0.05 kWh display threshold, but above the
  // backend's 0.01 kWh BATTERY_EXPORT classification threshold — this is
  // the exact mismatch reported in issue #247. Uses a display value distinct
  // from every other field in this fixture so the assertion can't pass by
  // matching an unrelated cell.
  batteryToGrid: fv(0.0403, '0.04-export-badge'),
  strategicIntent: 'BATTERY_EXPORT',
  buyPrice: fv(1, '1.00', 'SEK'),
  homeConsumption: fv(1, '1.00'),
  hourlyCost: fv(0, '0.00', 'SEK'),
  hourlySavings: fv(0, '0.00', 'SEK'),
}

let mockHour: Record<string, unknown> = baseHour

vi.mock('../../hooks/useDashboardData', () => ({
  useDashboardData: () => ({
    data: {
      currentPeriod: 86,
      hourlyData: [mockHour],
      summary: {},
      tomorrowData: null,
    },
    loading: false,
    error: null,
    refetch: vi.fn(),
  }),
}))

describe('BatteryActionsTable grid-export badge', () => {
  it('shows the battery-to-grid badge when the backend classified the period as BATTERY_EXPORT, even below the old 0.05 kWh display threshold', () => {
    mockHour = baseHour
    render(<BatteryActionsTable resolution="quarter-hourly" />)

    // The badge renders the batteryToGrid display value only when the
    // period is recognized as an export period. It should appear (Battery
    // column and Grid Export column) even though 0.0403 < the old 0.05 kWh
    // frontend threshold.
    expect(screen.getAllByText('0.04-export-badge').length).toBeGreaterThan(0)
  })

  it('prefers observedIntent over strategicIntent for actual periods, matching BatteryModeTimeline', () => {
    // strategicIntent defaults to IDLE when no DP plan covered this period
    // (see battery_system_manager.py's `planned_intent or "IDLE"`), but the
    // period actually exported to the grid — observedIntent reflects the
    // real sensor-derived outcome and must win for actual data.
    mockHour = {
      ...baseHour,
      strategicIntent: 'IDLE',
      observedIntent: 'BATTERY_EXPORT',
    }
    render(<BatteryActionsTable resolution="quarter-hourly" />)

    expect(screen.getAllByText('0.04-export-badge').length).toBeGreaterThan(0)
  })
})

describe('BatteryActionsTable cost breakdown columns', () => {
  it('shows import cost, export revenue and wear in separate columns', () => {
    mockHour = {
      ...baseHour,
      importCost: fv(0.14, '0.14', 'EUR'),
      exportRevenue: fv(0.02, '0.02', 'EUR'),
      batteryCycleCost: fv(0.02, '0.02', 'EUR'),
    }
    render(<BatteryActionsTable resolution="quarter-hourly" />)

    expect(screen.getByText('Import Cost')).toBeInTheDocument()
    expect(screen.getByText('Export Revenue')).toBeInTheDocument()
    expect(screen.getByText('Wear')).toBeInTheDocument()
    expect(screen.getAllByText('0.14').length).toBeGreaterThan(0)
    expect(screen.getAllByText('0.02').length).toBeGreaterThan(0)
  })
})
