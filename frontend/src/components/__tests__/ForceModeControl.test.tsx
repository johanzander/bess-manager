import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../../api/scheduleApi', () => ({
  getForceMode: vi.fn(),
  clearForceMode: vi.fn(),
  setForceMode: vi.fn(),
}));

import ForceModeControl from '../ForceModeControl';
import { ForceModeProvider } from '../ForceModeContext';
import { getForceMode, setForceMode, clearForceMode } from '../../api/scheduleApi';

const inactive = {
  active: false,
  mode: null,
  activatedAt: null,
  supportedModes: ['GRID_CHARGING', 'IDLE', 'SOLAR_STORAGE'],
};

const renderControl = () =>
  render(
    <ForceModeProvider>
      <ForceModeControl />
    </ForceModeProvider>,
  );

describe('ForceModeControl', () => {
  beforeEach(() => vi.clearAllMocks());

  it('lists only the supported modes', async () => {
    vi.mocked(getForceMode).mockResolvedValue(inactive);
    renderControl();
    expect(await screen.findByRole('button', { name: 'Standby' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Charging from Grid' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Storing Solar' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Powering Home' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Selling to Grid' })).not.toBeInTheDocument();
  });

  it('asks for confirmation before sending the PUT', async () => {
    vi.mocked(getForceMode).mockResolvedValue(inactive);
    vi.mocked(setForceMode).mockResolvedValue({ ...inactive, active: true, mode: 'IDLE' });

    renderControl();
    fireEvent.click(await screen.findByRole('button', { name: 'Standby' }));
    expect(setForceMode).not.toHaveBeenCalled();
    expect(screen.getByText(/maximum power until cleared/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Force Standby' }));
    await waitFor(() => expect(setForceMode).toHaveBeenCalledWith('IDLE'));
  });

  it('cancel does not send anything', async () => {
    vi.mocked(getForceMode).mockResolvedValue(inactive);
    renderControl();
    fireEvent.click(await screen.findByRole('button', { name: 'Standby' }));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(setForceMode).not.toHaveBeenCalled();
    expect(screen.queryByText(/maximum power until cleared/)).not.toBeInTheDocument();
  });

  it('shows a clear button only when active', async () => {
    vi.mocked(getForceMode).mockResolvedValue(inactive);
    const { unmount } = renderControl();
    await screen.findByRole('button', { name: 'Standby' });
    expect(screen.queryByRole('button', { name: /Return to automatic/ })).not.toBeInTheDocument();
    unmount();

    vi.mocked(getForceMode).mockResolvedValue({ ...inactive, active: true, mode: 'IDLE' });
    vi.mocked(clearForceMode).mockResolvedValue(inactive);
    renderControl();
    fireEvent.click(await screen.findByRole('button', { name: /Return to automatic/ }));
    await waitFor(() => expect(clearForceMode).toHaveBeenCalled());
  });
});
