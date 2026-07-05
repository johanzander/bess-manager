import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { EnergyFlowChart, getSellPriceTooltipText } from '../EnergyFlowChart'
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

describe('getSellPriceTooltipText', () => {
  const sellPriceFormatted = { value: -0.03, display: '-0.03', unit: 'EUR', text: '-0.03 EUR' }

  it('returns null when showSellPrice is false', () => {
    expect(getSellPriceTooltipText({ sellPriceFormatted }, false)).toBeNull()
  })

  it('returns null when there is no sell price data', () => {
    expect(getSellPriceTooltipText({}, true)).toBeNull()
  })

  it('returns the formatted sell price text when enabled and present', () => {
    expect(getSellPriceTooltipText({ sellPriceFormatted }, true)).toBe('-0.03 EUR')
  })
})
