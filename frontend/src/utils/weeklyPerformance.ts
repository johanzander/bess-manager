import { WeeklyPerformance } from '../types';

// Display direction is separate from the nonnegative EnergyData measurements.
export const weeklyFlowRows = (data: WeeklyPerformance, scenario: 'actual' | 'optimal') =>
  data.daily.map(({ date }) => {
    const energy = data.periods
      .filter(p => p.date === date)
      .map(p => (scenario === 'actual' ? p.actualEnergy : p.optimalEnergy));
    const total = (key: keyof (typeof energy)[number]) =>
      energy.reduce((sum, e) => sum + e[key], 0);
    return {
      date,
      solarHome: total('solarToHome'),
      batteryHome: total('batteryToHome'),
      gridHome: total('gridToHome'),
      solarExport: -total('solarToGrid'),
      batteryExport: -total('batteryToGrid'),
      discharge: total('batteryDischarged'),
      solarCharge: -total('solarToBattery'),
      gridCharge: -total('gridToBattery'),
    };
  });
