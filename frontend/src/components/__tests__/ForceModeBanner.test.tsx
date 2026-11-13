import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../../api/scheduleApi', () => ({
  getForceMode: vi.fn(),
  clearForceMode: vi.fn(),
  setForceMode: vi.fn(),
}));

import ForceModeBanner from '../ForceModeBanner';
import { ForceModeProvider } from '../ForceModeContext';
import { getForceMode, clearForceMode } from '../../api/scheduleApi';

const inactive = { active: false, mode: null, activatedAt: null, supportedModes: ['IDLE'] };
const active = {
  active: true,
  mode: 'BATTERY_EXPORT',
  activatedAt: '2026-11-09T14:30:00+00:00',
  supportedModes: ['IDLE', 'BATTERY_EXPORT'],
};

const renderBanner = () =>
  render(
    <ForceModeProvider>
      <ForceModeBanner />
    </ForceModeProvider>,
  );

describe('ForceModeBanner', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders nothing when force mode is inactive', async () => {
    vi.mocked(getForceMode).mockResolvedValue(inactive);
    const { container } = renderBanner();
    await waitFor(() => expect(getForceMode).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the forced mode when active', async () => {
    vi.mocked(getForceMode).mockResolvedValue(active);
    renderBanner();
    expect(await screen.findByText(/Force mode: Selling to Grid/)).toBeInTheDocument();
    expect(screen.getByText(/optimizer plan overridden since/)).toBeInTheDocument();
  });

  it('Return to automatic clears force mode and hides the banner', async () => {
    vi.mocked(getForceMode).mockResolvedValue(active);
    vi.mocked(clearForceMode).mockImplementation(async () => {
      vi.mocked(getForceMode).mockResolvedValue(inactive);
      return inactive;
    });
    const { container } = renderBanner();
    fireEvent.click(await screen.findByRole('button', { name: /Return to automatic/ }));
    await waitFor(() => expect(clearForceMode).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
