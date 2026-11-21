import { PerformanceResult } from '../types';

// Display direction is separate from the nonnegative EnergyData measurements.
export const weeklyFlowRows = (data: PerformanceResult, scenario: 'actual' | 'optimal') =>
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
      // Same direction as the main screen: charging up, discharging down.
      discharge: -total('batteryDischarged'),
      solarCharge: total('solarToBattery'),
      gridCharge: total('gridToBattery'),
    };
  });

const QUARTER_MS = 15 * 60 * 1000;

// Net battery power per quarter (discharge above zero, charge below), with a
// null row wherever quarters are unknown so lines break instead of bridging.
export const batteryPowerRows = (data: PerformanceResult, day?: string) => {
  const rows: {
    timestamp: string;
    buyPrice: number | null;
    actualPower: number | null;
    optimalPower: number | null;
  }[] = [];
  let previous: number | null = null;
  for (const p of data.periods.filter(row => !day || row.date === day)) {
    const start = new Date(p.timestamp).getTime();
    if (previous !== null && start - previous > QUARTER_MS) {
      rows.push({
        timestamp: new Date(previous + QUARTER_MS).toISOString(),
        buyPrice: null,
        actualPower: null,
        optimalPower: null,
      });
    }
    rows.push({
      timestamp: p.timestamp,
      buyPrice: p.buyPrice,
      actualPower: (p.actualEnergy.batteryDischarged - p.actualEnergy.batteryCharged) * 4,
      optimalPower: (p.optimalEnergy.batteryDischarged - p.optimalEnergy.batteryCharged) * 4,
    });
    previous = start;
  }
  return rows;
};

export interface StrategySide {
  chargedKwh: number;
  chargePrice: number | null;
  chargeHours: string;
  dischargedKwh: number;
  dischargePrice: number | null;
}

const hourRanges = (hours: number[]) => {
  const unique = [...new Set(hours)].sort((a, b) => a - b);
  const ranges: string[] = [];
  let start: number | null = null;
  let end = 0;
  for (const hour of unique) {
    if (start !== null && hour === end + 1) {
      end = hour;
      continue;
    }
    if (start !== null)
      ranges.push(`${String(start).padStart(2, '0')}–${String(end + 1).padStart(2, '0')}`);
    start = hour;
    end = hour;
  }
  if (start !== null)
    ranges.push(`${String(start).padStart(2, '0')}–${String(end + 1).padStart(2, '0')}`);
  return ranges.join(', ');
};

// Per day: how much each scenario charged and discharged, at what average
// import price, and in which local hours. Prices weight by energy moved.
export const dailyStrategy = (data: PerformanceResult) =>
  data.daily.map(day => {
    const rows = data.periods.filter(p => p.date === day.date);
    const hourOf = (timestamp: string) =>
      Number(
        new Date(timestamp).toLocaleString('en-GB', {
          timeZone: data.timezone,
          hour: '2-digit',
          hour12: false,
        })
      ) % 24;
    const side = (kind: 'actualEnergy' | 'optimalEnergy'): StrategySide => {
      const charged = rows.reduce((sum, p) => sum + p[kind].batteryCharged, 0);
      const discharged = rows.reduce((sum, p) => sum + p[kind].batteryDischarged, 0);
      return {
        chargedKwh: charged,
        chargePrice:
          charged > 0
            ? rows.reduce((sum, p) => sum + p[kind].batteryCharged * p.buyPrice, 0) / charged
            : null,
        // A quarter counts as charging from 1 kW upward, so trickle top-ups do
        // not fragment the reported windows.
        chargeHours: hourRanges(
          rows.filter(p => p[kind].batteryCharged >= 0.25).map(p => hourOf(p.timestamp))
        ),
        dischargedKwh: discharged,
        dischargePrice:
          discharged > 0
            ? rows.reduce((sum, p) => sum + p[kind].batteryDischarged * p.buyPrice, 0) / discharged
            : null,
      };
    };
    const actualCost = day.actualGridCost + (day.actualWearCost ?? 0);
    const optimalCost = day.optimalGridCost + (day.optimalWearCost ?? 0);
    return {
      date: day.date,
      actual: side('actualEnergy'),
      optimal: side('optimalEnergy'),
      costDifference: actualCost - optimalCost,
    };
  });

const HOUR_MS = 60 * 60 * 1000;

export interface HourlyStrategyRow {
  hour: string;
  date: string;
  buyPrice: number | null;
  actualKwh: number | null;
  optimalKwh: number | null;
  costDifference: number | null;
  band: 'cheap' | 'dear' | null;
}

const localDate = (timestamp: number, timeZone: string) =>
  new Date(timestamp).toLocaleDateString('en-CA', { timeZone });

// Hourly net battery energy (charge positive, discharge negative) for both
// scenarios. Hours without any observed quarter stay null so charts show gaps.
// costDifference is actual minus hindsight grid cost for the hour. Each day's
// cheapest and dearest quarter of known hours are marked as bands.
export const hourlyStrategyRows = (data: PerformanceResult, days?: string[]) => {
  const periods = data.periods.filter(p => !days || days.includes(p.date));
  if (!periods.length) return [] as HourlyStrategyRow[];
  const byHour = new Map<number, typeof periods>();
  for (const p of periods) {
    const start = new Date(p.timestamp).getTime();
    const hour = start - (start % HOUR_MS);
    byHour.set(hour, [...(byHour.get(hour) ?? []), p]);
  }
  const first = Math.min(...byHour.keys());
  const last = Math.max(...byHour.keys());
  const rows: HourlyStrategyRow[] = [];
  for (let hour = first; hour <= last; hour += HOUR_MS) {
    const quarters = byHour.get(hour);
    const net = (kind: 'actualEnergy' | 'optimalEnergy') =>
      quarters
        ? quarters.reduce((sum, p) => sum + p[kind].batteryCharged - p[kind].batteryDischarged, 0)
        : null;
    rows.push({
      hour: new Date(hour).toISOString(),
      date: quarters ? quarters[0].date : localDate(hour, data.timezone),
      buyPrice: quarters
        ? quarters.reduce((sum, p) => sum + p.buyPrice, 0) / quarters.length
        : null,
      actualKwh: net('actualEnergy'),
      optimalKwh: net('optimalEnergy'),
      costDifference: quarters
        ? quarters.reduce(
            (sum, p) =>
              sum +
              (p.actualEnergy.gridImported - p.optimalEnergy.gridImported) * p.buyPrice -
              (p.actualEnergy.gridExported - p.optimalEnergy.gridExported) * p.sellPrice,
            0
          )
        : null,
      band: null,
    });
  }
  for (const date of new Set(rows.map(row => row.date))) {
    const known = rows.filter(row => row.date === date && row.buyPrice != null);
    const sorted = known.map(row => row.buyPrice as number).sort((a, b) => a - b);
    if (sorted.length < 4) continue;
    const low = sorted[Math.floor((sorted.length - 1) * 0.25)];
    const high = sorted[Math.ceil((sorted.length - 1) * 0.75)];
    for (const row of known) {
      const value = row.buyPrice as number;
      row.band = value <= low ? 'cheap' : value >= high ? 'dear' : null;
    }
  }
  return rows;
};

// Consecutive hours sharing a band, as [first, last] hour keys for shading.
export const bandRuns = (rows: HourlyStrategyRow[]) => {
  const runs: { band: 'cheap' | 'dear'; from: string; to: string }[] = [];
  for (const row of rows) {
    const previous = runs[runs.length - 1];
    if (!row.band) continue;
    const index = rows.indexOf(row);
    if (previous && previous.band === row.band && rows[index - 1]?.hour === previous.to) {
      previous.to = row.hour;
    } else {
      runs.push({ band: row.band, from: row.hour, to: row.hour });
    }
  }
  return runs;
};

export type CoverageStatus = 'observed' | 'backup' | 'restart' | 'unknown' | 'invalid';

const coverageStatus = (reason: string): CoverageStatus =>
  reason.includes('reserve')
    ? 'backup'
    : reason.includes('restart')
      ? 'restart'
      : reason.includes('invalid')
        ? 'invalid'
        : 'unknown';

// Every expected quarter in time order, merged into runs of one status.
export const coverageRuns = (data: PerformanceResult) => {
  const quarters = [
    ...data.periods.map(p => ({ timestamp: p.timestamp, status: 'observed' as CoverageStatus })),
    ...(data.excludedIntervals ?? []).map(e => ({
      timestamp: e.timestamp,
      status: coverageStatus(e.reason),
    })),
  ].sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
  const runs: { status: CoverageStatus; start: string; quarters: number }[] = [];
  for (const quarter of quarters) {
    const last = runs[runs.length - 1];
    if (last && last.status === quarter.status) last.quarters += 1;
    else runs.push({ status: quarter.status, start: quarter.timestamp, quarters: 1 });
  }
  return runs;
};

// Running saving against solar only, for actual and hindsight, per observed
// quarter: solar-only cost minus grid cost minus wear (charged kWh x rate).
export const cumulativeSavings = (data: PerformanceResult, wearPerKwh: number) => {
  let actual = 0;
  let optimal = 0;
  return data.periods.map(p => {
    const solarOnly =
      Math.max(0, p.actualEnergy.homeConsumption - p.actualEnergy.solarProduction) * p.buyPrice -
      Math.max(0, p.actualEnergy.solarProduction - p.actualEnergy.homeConsumption) * p.sellPrice;
    const cost = (e: typeof p.actualEnergy) =>
      e.gridImported * p.buyPrice - e.gridExported * p.sellPrice + e.batteryCharged * wearPerKwh;
    actual += solarOnly - cost(p.actualEnergy);
    optimal += solarOnly - cost(p.optimalEnergy);
    return { timestamp: p.timestamp, actual, optimal };
  });
};

// Energy-weighted charging and discharging prices across the period.
export const tradingStats = (days: ReturnType<typeof dailyStrategy>) => {
  const side = (kind: 'actual' | 'optimal') => {
    const charged = days.reduce((sum, day) => sum + day[kind].chargedKwh, 0);
    const discharged = days.reduce((sum, day) => sum + day[kind].dischargedKwh, 0);
    const chargePrice =
      charged > 0
        ? days.reduce((sum, day) => sum + day[kind].chargedKwh * (day[kind].chargePrice ?? 0), 0) /
          charged
        : null;
    const dischargePrice =
      discharged > 0
        ? days.reduce(
            (sum, day) => sum + day[kind].dischargedKwh * (day[kind].dischargePrice ?? 0),
            0
          ) / discharged
        : null;
    return {
      chargePrice,
      dischargePrice,
      spread: chargePrice != null && dischargePrice != null ? dischargePrice - chargePrice : null,
    };
  };
  return { actual: side('actual'), optimal: side('optimal') };
};
