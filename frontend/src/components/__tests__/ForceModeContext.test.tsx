import { act, render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../../api/scheduleApi', () => ({
  getForceMode: vi.fn(),
  clearForceMode: vi.fn(),
  setForceMode: vi.fn(),
}));

import ForceModeBanner from '../ForceModeBanner';
import ForceModeControl from '../ForceModeControl';
import { ForceModeProvider } from '../ForceModeContext';
import { getForceMode, setForceMode } from '../../api/scheduleApi';

const inactive = {
  active: false,
  mode: null,
  activatedAt: null,
  supportedModes: ['IDLE', 'SOLAR_STORAGE'],
};

const renderBannerAndControl = () =>
  render(
    <ForceModeProvider>
      <ForceModeBanner />
      <ForceModeControl />
    </ForceModeProvider>,
  );

describe('ForceModeProvider', () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.useRealTimers());

  it('serves the banner and the control from one fetch', async () => {
    vi.mocked(getForceMode).mockResolvedValue(inactive);
    renderBannerAndControl();
    await screen.findByRole('button', { name: 'Standby' });
    expect(getForceMode).toHaveBeenCalledTimes(1);
  });

  it('a mode set in the control shows in the banner without a refetch', async () => {
    vi.mocked(getForceMode).mockResolvedValue(inactive);
    vi.mocked(setForceMode).mockResolvedValue({
      ...inactive,
      active: true,
      mode: 'IDLE',
      activatedAt: '2026-11-13T10:00:00+00:00',
    });
    renderBannerAndControl();

    fireEvent.click(await screen.findByRole('button', { name: 'Standby' }));
    fireEvent.click(screen.getByRole('button', { name: 'Force Standby' }));

    expect(await screen.findByText(/Force mode: Standby/)).toBeInTheDocument();
    expect(getForceMode).toHaveBeenCalledTimes(1);
  });

  it('a fetch that failed while the backend was starting is retried', async () => {
    vi.useFakeTimers();
    vi.mocked(getForceMode)
      .mockRejectedValueOnce(new Error('503 starting up'))
      .mockResolvedValue(inactive);
    vi.spyOn(console, 'error').mockImplementation(() => {});
    renderBannerAndControl();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.queryByRole('button', { name: 'Standby' })).not.toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(screen.getByRole('button', { name: 'Standby' })).toBeInTheDocument();
  });
});
