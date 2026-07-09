import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { SavingsHistorySection } from '../SavingsHistorySection';
import * as scheduleApi from '../../../api/scheduleApi';

describe('SavingsHistorySection', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(scheduleApi, 'fetchSavingsHistoryDiskUsage').mockResolvedValue({
      dayCount: 12,
      totalBytes: 45000,
    });
  });

  it('shows the recorded day count and requires a second click to clear', async () => {
    const clearSpy = vi.spyOn(scheduleApi, 'clearSavingsHistory').mockResolvedValue({
      dayCount: 0,
      totalBytes: 0,
    });

    render(<SavingsHistorySection />);

    await waitFor(() => {
      expect(screen.getByText(/12 days recorded/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /clear history/i }));
    expect(clearSpy).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /confirm clear/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /confirm clear/i }));

    await waitFor(() => expect(clearSpy).toHaveBeenCalled());
    await waitFor(() => {
      expect(screen.getByText(/0 days recorded/i)).toBeInTheDocument();
    });
  });
});
