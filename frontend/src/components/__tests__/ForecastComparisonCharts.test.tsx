import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { ComparisonTooltip } from '../ForecastComparisonCharts'

const payloadFor = (actual: number, predicted: number) => [{
  payload: {
    hour: 10.5,
    periodNum: 10,
    actualConsumption: actual,
    predictedConsumption: predicted,
  },
}]

describe('ComparisonTooltip diff color semantics', () => {
  it('colors a positive diff RED when higher-than-planned is unfavorable (consumption)', () => {
    render(
      <ComparisonTooltip
        active
        payload={payloadFor(10.9, 6.552)}
        color="#ef4444"
        actualKey="actualConsumption"
        predictedKey="predictedConsumption"
        label="forecast"
        favorableDirection="lower"
      />
    )

    const diff = screen.getByText(/Diff: \+4\.348 kWh/i)
    expect(diff.className).toMatch(/text-red-600/)
  })

  it('colors a negative diff GREEN when lower-than-planned is favorable (consumption)', () => {
    render(
      <ComparisonTooltip
        active
        payload={payloadFor(3.0, 6.552)}
        color="#ef4444"
        actualKey="actualConsumption"
        predictedKey="predictedConsumption"
        label="forecast"
        favorableDirection="lower"
      />
    )

    const diff = screen.getByText(/Diff: -3\.552 kWh/i)
    expect(diff.className).toMatch(/text-green-600/)
  })

  it('still colors a positive diff GREEN when higher-than-forecast is favorable (solar, the default)', () => {
    render(
      <ComparisonTooltip
        active
        payload={payloadFor(10.9, 6.552).map(p => ({
          payload: { hour: 10.5, periodNum: 10, actualSolar: p.payload.actualConsumption, predictedSolar: p.payload.predictedConsumption },
        }))}
        color="#fbbf24"
        actualKey="actualSolar"
        predictedKey="predictedSolar"
        label="forecast"
      />
    )

    const diff = screen.getByText(/Diff: \+4\.348 kWh/i)
    expect(diff.className).toMatch(/text-green-600/)
  })
})
