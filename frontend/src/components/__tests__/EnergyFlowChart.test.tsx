import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { EnergyFlowChart, getSellPriceTooltipText, getHomeLoadSplit } from '../EnergyFlowChart'
import type { HourlyData } from '../../types'

const dailyViewData: HourlyData[] = [
  {
    period: 0,
    dataSource: 'actual',
    solarProduction: { value: 0, display: '0', unit: 'kWh', text: '0 kWh' },
    homeConsumption: { value: 1, display: '1', unit: 'kWh', text: '1 kWh' },
    buyPrice: { value: 0.21, display: '0.21', unit: 'EUR', text: '0.21 EUR' },
    sellPrice: { value: -0.03, display: '-0.03', unit: 'EUR', text: '-0.03 EUR' },
  },
]

describe('EnergyFlowChart sell price toggle', () => {
  it('renders the sell price switch reflecting showSellPrice', () => {
    render(
      <EnergyFlowChart
        dailyViewData={dailyViewData}
        currentHour={0}
        resolution="hourly"
        showSellPrice={false}
        onShowSellPriceChange={vi.fn()}
      />
    )

    expect(screen.getByRole('switch', { name: /show sell price/i })).toHaveAttribute('aria-checked', 'false')
  })

  it('calls onShowSellPriceChange when clicked', () => {
    const onShowSellPriceChange = vi.fn()
    render(
      <EnergyFlowChart
        dailyViewData={dailyViewData}
        currentHour={0}
        resolution="hourly"
        showSellPrice={false}
        onShowSellPriceChange={onShowSellPriceChange}
      />
    )

    fireEvent.click(screen.getByRole('switch', { name: /show sell price/i }))

    expect(onShowSellPriceChange).toHaveBeenCalledWith(true)
  })
})

describe('getHomeLoadSplit', () => {
  const fv = (value: number) => ({ value, display: String(value), unit: 'kWh', text: `${value} kWh` })

  it('splits a future period into residual + planned that stack to the combined curve', () => {
    const split = getHomeLoadSplit(
      { dataSource: 'predicted', predictedResidualLoad: fv(0.25), plannedManagedLoad: fv(1.0) },
      1.25
    )
    // Consumption is drawn below the zero axis, so both are negative.
    expect(split.residual).toBe(-0.25)
    expect(split.planned).toBe(-1.0)
    expect(split.residual + split.planned).toBe(-1.25)
    expect(split.forecastTotal).toBeNull()  // no outline for the future -- it's already the solid stack
  })

  it('keeps an elapsed period at its measured total and exposes the frozen forecast shape', () => {
    // Measured 2.5 kWh, but the plan for that period was residual 0.25 + planned 1.0.
    const split = getHomeLoadSplit(
      { dataSource: 'actual', predictedResidualLoad: fv(0.25), plannedManagedLoad: fv(1.0) },
      2.5
    )
    expect(split.residual).toBe(-2.5)   // stack shows what was on the meter
    expect(split.planned).toBe(0)
    expect(split.forecastResidual).toBe(-0.25)  // outline's seam = where residual ended
    expect(split.forecastTotal).toBe(-1.25)     // outline's outer edge = what was planned
  })

  it('keeps the forecast outline null for an elapsed period with no plan declared', () => {
    // Ordinary hour, no overlay -- nothing to compare, so no outline.
    const split = getHomeLoadSplit(
      { dataSource: 'actual', predictedResidualLoad: fv(0.375), plannedManagedLoad: fv(0) },
      0.375
    )
    expect(split.forecastResidual).toBeNull()
    expect(split.forecastTotal).toBeNull()
  })

  it('falls back to all-residual when the breakdown is absent', () => {
    const split = getHomeLoadSplit(undefined, 1.25)
    expect(split.residual).toBe(-1.25)
    expect(split.planned).toBe(0)
    expect(split.forecastResidual).toBeNull()
    expect(split.forecastTotal).toBeNull()
  })

  it('keeps a negative planned block (away-from-home subtract) intact for the future', () => {
    const split = getHomeLoadSplit(
      { dataSource: 'predicted', predictedResidualLoad: fv(1.0), plannedManagedLoad: fv(-0.4) },
      0.6
    )
    expect(split.residual).toBe(-1.0)
    expect(split.planned).toBe(0.4)
  })
})

describe('getSellPriceTooltipText', () => {
  const sellPriceFormatted = { value: -0.03, display: '-0.03', unit: 'EUR', text: '-0.03 EUR' }

  it('returns null when there is no sell price data', () => {
    expect(getSellPriceTooltipText({})).toBeNull()
  })

  it('returns the formatted sell price text whenever it is present, regardless of the line toggle', () => {
    expect(getSellPriceTooltipText({ sellPriceFormatted })).toBe('-0.03 EUR')
  })
})
