// frontend/src/hooks/__tests__/useSavingsAggregate.test.ts
import { renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useSavingsAggregate } from '../useSavingsAggregate';
import * as scheduleApi from '../../api/scheduleApi';

describe('useSavingsAggregate', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('fetches buckets for the given period and exposes them as data', async () => {
    const fetchSpy = vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [
        {
          label: '2026-W28',
          startDate: '2026-07-06',
          endDate: '2026-07-12',
          dayCount: 1,
          importKwh: { value: 1, display: '1.0', unit: 'kWh', text: '1.0 kWh' },
          importEur: { value: 2, display: '2.00', unit: 'EUR', text: '2.00 EUR' },
          exportKwh: { value: 2, display: '2.0', unit: 'kWh', text: '2.0 kWh' },
          exportEur: { value: 2, display: '2.00', unit: 'EUR', text: '2.00 EUR' },
          gridCost: { value: 0, display: '0.00', unit: 'EUR', text: '0.00 EUR' },
          gridOnlyCost: { value: 3, display: '3.00', unit: 'EUR', text: '3.00 EUR' },
          netSavings: { value: 3, display: '3.00', unit: 'EUR', text: '3.00 EUR' },
          solarSavings: { value: 2, display: '2.00', unit: 'EUR', text: '2.00 EUR' },
          batterySavings: { value: 1, display: '1.00', unit: 'EUR', text: '1.00 EUR' },
          batteryCycleCost: { value: 0.1, display: '0.10', unit: 'EUR', text: '0.10 EUR' },
          savingsVsGridOnly: { value: 3, display: '3.00', unit: 'EUR', text: '3.00 EUR' },
          solarKwh: { value: 1, display: '1.0', unit: 'kWh', text: '1.0 kWh' },
          batteryChargedKwh: { value: 0, display: '0.0', unit: 'kWh', text: '0.0 kWh' },
          batteryDischargedKwh: { value: 0, display: '0.0', unit: 'kWh', text: '0.0 kWh' },
        },
      ],
      count: 1,
    });

    const { result } = renderHook(() => useSavingsAggregate('week', 1));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(fetchSpy).toHaveBeenCalledWith('week', 1, undefined);
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].label).toBe('2026-W28');
    expect(result.current.error).toBeNull();
  });

  it('fetches the day period', async () => {
    const fetchSpy = vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [
        {
          label: '2026-07-11',
          startDate: '2026-07-11',
          endDate: '2026-07-11',
          dayCount: 1,
          importKwh: { value: 1, display: '1.0', unit: 'kWh', text: '1.0 kWh' },
          importEur: { value: 2, display: '2.00', unit: 'EUR', text: '2.00 EUR' },
          exportKwh: { value: 2, display: '2.0', unit: 'kWh', text: '2.0 kWh' },
          exportEur: { value: 2, display: '2.00', unit: 'EUR', text: '2.00 EUR' },
          gridCost: { value: 0, display: '0.00', unit: 'EUR', text: '0.00 EUR' },
          gridOnlyCost: { value: 3, display: '3.00', unit: 'EUR', text: '3.00 EUR' },
          netSavings: { value: 3, display: '3.00', unit: 'EUR', text: '3.00 EUR' },
          solarSavings: { value: 2, display: '2.00', unit: 'EUR', text: '2.00 EUR' },
          batterySavings: { value: 1, display: '1.00', unit: 'EUR', text: '1.00 EUR' },
          batteryCycleCost: { value: 0.1, display: '0.10', unit: 'EUR', text: '0.10 EUR' },
          savingsVsGridOnly: { value: 3, display: '3.00', unit: 'EUR', text: '3.00 EUR' },
          solarKwh: { value: 1, display: '1.0', unit: 'kWh', text: '1.0 kWh' },
          batteryChargedKwh: { value: 0, display: '0.0', unit: 'kWh', text: '0.0 kWh' },
          batteryDischargedKwh: { value: 0, display: '0.0', unit: 'kWh', text: '0.0 kWh' },
        },
      ],
      count: 1,
    });

    const { result } = renderHook(() => useSavingsAggregate('day', 1));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(fetchSpy).toHaveBeenCalledWith('day', 1, undefined);
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].label).toBe('2026-07-11');
    expect(result.current.error).toBeNull();
  });

  it('surfaces an error message when the fetch rejects', async () => {
    vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockRejectedValue(new Error('boom'));

    const { result } = renderHook(() => useSavingsAggregate('month'));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe('boom');
    expect(result.current.data).toBeNull();
  });

  it('passes the date param through to fetchSavingsAggregate', async () => {
    const fetchSpy = vi.spyOn(scheduleApi, 'fetchSavingsAggregate').mockResolvedValue({
      buckets: [],
      count: 0,
    });

    const { result } = renderHook(() => useSavingsAggregate('month', undefined, '2026-05-01'));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(fetchSpy).toHaveBeenCalledWith('month', undefined, '2026-05-01');
  });

  it('does not fetch when enabled is false', async () => {
    const fetchSpy = vi.spyOn(scheduleApi, 'fetchSavingsAggregate');

    const { result } = renderHook(() => useSavingsAggregate('day', 1, undefined, false));

    expect(result.current.loading).toBe(false);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
