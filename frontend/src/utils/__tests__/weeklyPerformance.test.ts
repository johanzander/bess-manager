import { describe, expect, it } from 'vitest';
import { WeeklyPerformance } from '../../types';
import { weeklyFlowRows } from '../weeklyPerformance';

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
      batteryDischarged: 1.5,
    };
    const data = {
      daily: [{ date: '2026-09-07', actualGridCost: -1, optimalGridCost: -2 }],
      periods: [{ date: '2026-09-07', actualEnergy: energy, optimalEnergy: energy }],
    } as WeeklyPerformance;
    const row = weeklyFlowRows(data, 'actual')[0];
    expect(row.solarExport).toBe(-2);
    expect(row.batteryExport).toBe(-0.5);
    expect(row.solarHome + row.batteryHome + row.gridHome).toBe(3);
    expect(row.gridHome).toBe(1);
    expect(row.gridCharge).toBe(-4);
    expect(energy.solarToGrid).toBe(2);
    expect(energy.gridToBattery).toBe(4);
  });
});
