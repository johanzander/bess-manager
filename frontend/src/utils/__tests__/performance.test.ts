import { describe, expect, it } from 'vitest';
import { PerformanceResult } from '../../types';
import { dailyStrategy, hourlyStrategyRows, weeklyFlowRows } from '../performance';

describe('weekly chart energy destinations', () => {
  it('exports below zero without changing raw energy or counting grid charging as home supply', () => {
    const energy = {
      homeConsumption: 3,
      solarToHome: 1,
      batteryToHome: 1,
      gridToHome: 1,
      solarToGrid: 2,
      batteryToGrid: 0.5,
      solarToBattery: 1,
      gridToBattery: 4,
      batteryCharged: 5,
      batteryDischarged: 1.5,
    };
    const data = {
      daily: [{ date: '2026-09-07', actualGridCost: -1, optimalGridCost: -2 }],
      periods: [{ date: '2026-09-07', actualEnergy: energy, optimalEnergy: energy }],
    } as PerformanceResult;
    const row = weeklyFlowRows(data, 'actual')[0];
    expect(row.solarExport).toBe(-2);
    expect(row.batteryExport).toBe(-0.5);
    expect(row.solarHome + row.batteryHome + row.gridHome).toBe(3);
    expect(row.gridHome).toBe(1);
    expect(row.gridCharge).toBe(4);
    expect(row.discharge).toBe(-1.5);
    expect(energy.solarToGrid).toBe(2);
    expect(energy.gridToBattery).toBe(4);
  });
});

describe('hindsight strategy summary', () => {
  const quiet = {
    homeConsumption: 1,
    gridImported: 1,
    gridExported: 0,
    solarToHome: 0,
    batteryToHome: 0,
    gridToHome: 1,
    solarToGrid: 0,
    batteryToGrid: 0,
    solarToBattery: 0,
    gridToBattery: 0,
    batteryCharged: 0,
    batteryDischarged: 0,
  };
  const charge = { ...quiet, gridImported: 3, gridToBattery: 2, batteryCharged: 2 };
  const discharge = {
    ...quiet,
    gridImported: 0,
    batteryToHome: 1,
    gridToHome: 0,
    batteryDischarged: 1,
  };
  const data = {
    timezone: 'Europe/Helsinki',
    daily: [
      {
        date: '2026-11-09',
        actualGridCost: 3,
        optimalGridCost: 2,
        actualWearCost: 0.1,
        optimalWearCost: 0.05,
      },
    ],
    periods: [
      // 02:00 and 02:15 local, cheap: hindsight charges, actual idles.
      {
        date: '2026-11-09',
        timestamp: '2026-11-09T00:00:00Z',
        buyPrice: 0.05,
        sellPrice: 0,
        actualEnergy: quiet,
        optimalEnergy: charge,
      },
      {
        date: '2026-11-09',
        timestamp: '2026-11-09T00:15:00Z',
        buyPrice: 0.07,
        sellPrice: 0,
        actualEnergy: quiet,
        optimalEnergy: charge,
      },
      // 18:00 local, dear: both discharge; then an unknown hour.
      {
        date: '2026-11-09',
        timestamp: '2026-11-09T16:00:00Z',
        buyPrice: 0.3,
        sellPrice: 0,
        actualEnergy: discharge,
        optimalEnergy: discharge,
      },
    ],
  } as unknown as PerformanceResult;

  it('weights prices by energy and names local charging hours', () => {
    const [day] = dailyStrategy(data);
    expect(day.optimal.chargedKwh).toBe(4);
    expect(day.optimal.chargePrice).toBeCloseTo(0.06);
    expect(day.optimal.chargeHours).toBe('02–03');
    expect(day.actual.chargePrice).toBeNull();
    expect(day.optimal.dischargePrice).toBeCloseTo(0.3);
    expect(day.costDifference).toBeCloseTo(1.05);
  });

  it('aggregates hours, keeps unknown hours empty and prices the difference', () => {
    const rows = hourlyStrategyRows(data);
    expect(rows).toHaveLength(17);
    expect(rows[0].optimalKwh).toBe(4);
    expect(rows[0].actualKwh).toBe(0);
    expect(rows[1].actualKwh).toBeNull();
    expect(rows[16].optimalKwh).toBe(-1);
    // Hindsight imported 2 kWh more in each charging quarter.
    expect(rows[0].costDifference).toBeCloseTo(-(2 * 0.05 + 2 * 0.07));
  });
});
