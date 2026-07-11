import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import DateSelector from '../DateSelector';
import { toISODate as iso } from '../../utils/timeUtils';

describe('DateSelector availableDates', () => {
  it('disables the prev-day chevron when the previous day has no data', () => {
    const today = new Date();
    const onDateChange = vi.fn();

    render(
      <DateSelector
        selectedDate={today}
        onDateChange={onDateChange}
        availableDates={new Set([iso(today)])}
      />
    );

    const [prevButton] = screen.getAllByRole('button');
    expect(prevButton).toBeDisabled();

    fireEvent.click(prevButton);
    expect(onDateChange).not.toHaveBeenCalled();
  });

  it('skips over a gap in available dates when navigating', () => {
    const today = new Date();
    const twoDaysAgo = new Date(today);
    twoDaysAgo.setDate(today.getDate() - 2);
    const onDateChange = vi.fn();

    render(
      <DateSelector
        selectedDate={today}
        onDateChange={onDateChange}
        availableDates={new Set([iso(today), iso(twoDaysAgo)])}
      />
    );

    const [prevButton] = screen.getAllByRole('button');
    expect(prevButton).not.toBeDisabled();

    fireEvent.click(prevButton);
    expect(onDateChange).toHaveBeenCalledTimes(1);
    expect(iso(onDateChange.mock.calls[0][0])).toBe(iso(twoDaysAgo));
  });

  it('does not restrict navigation when availableDates is null (still loading)', () => {
    const today = new Date();
    const onDateChange = vi.fn();

    render(
      <DateSelector selectedDate={today} onDateChange={onDateChange} availableDates={null} />
    );

    const [prevButton] = screen.getAllByRole('button');
    expect(prevButton).not.toBeDisabled();
  });
});
