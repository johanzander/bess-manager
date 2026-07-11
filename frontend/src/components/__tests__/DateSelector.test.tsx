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

describe('DateSelector resolution', () => {
  it('steps by month when resolution="month"', () => {
    const selected = new Date(2026, 5, 15); // June 15, 2026
    const onDateChange = vi.fn();

    render(
      <DateSelector
        selectedDate={selected}
        onDateChange={onDateChange}
        resolution="month"
        availableDates={null}
      />
    );

    const [prevButton] = screen.getAllByRole('button');
    fireEvent.click(prevButton);

    expect(onDateChange).toHaveBeenCalledTimes(1);
    const result = onDateChange.mock.calls[0][0] as Date;
    expect(result.getFullYear()).toBe(2026);
    expect(result.getMonth()).toBe(4); // May
  });

  it('steps by year when resolution="year"', () => {
    const selected = new Date(2026, 5, 15);
    const onDateChange = vi.fn();

    render(
      <DateSelector
        selectedDate={selected}
        onDateChange={onDateChange}
        resolution="year"
        availableDates={null}
      />
    );

    const buttons = screen.getAllByRole('button');
    const nextButton = buttons[buttons.length - 1];
    fireEvent.click(nextButton);

    expect(onDateChange).toHaveBeenCalledTimes(1);
    const result = onDateChange.mock.calls[0][0] as Date;
    expect(result.getFullYear()).toBe(2027);
  });

  it('treats a month as available if any persisted day falls inside it', () => {
    const selected = new Date(2026, 5, 15); // June 2026
    const onDateChange = vi.fn();

    render(
      <DateSelector
        selectedDate={selected}
        onDateChange={onDateChange}
        resolution="month"
        availableDates={new Set(['2026-05-20', '2026-06-01'])}
      />
    );

    const [prevButton] = screen.getAllByRole('button');
    expect(prevButton).not.toBeDisabled();
  });

  it('displays just the year when resolution="year"', () => {
    const selected = new Date(2026, 5, 15);

    render(
      <DateSelector selectedDate={selected} onDateChange={vi.fn()} resolution="year" />
    );

    expect(screen.getByText('2026')).toBeInTheDocument();
  });

  it('does not permanently disable next-year navigation after crossing the default maxDate window', () => {
    const selected = new Date(2026, 5, 15); // June 2026
    let current = selected;
    const onDateChange = vi.fn((d: Date) => {
      current = d;
    });

    const { rerender } = render(
      <DateSelector
        selectedDate={current}
        onDateChange={onDateChange}
        resolution="year"
        availableDates={null}
      />
    );

    const buttons = screen.getAllByRole('button');
    const nextButton = buttons[buttons.length - 1];
    fireEvent.click(nextButton); // -> 2027

    rerender(
      <DateSelector
        selectedDate={current}
        onDateChange={onDateChange}
        resolution="year"
        availableDates={null}
      />
    );

    const buttonsAfter = screen.getAllByRole('button');
    const nextButtonAfter = buttonsAfter[buttonsAfter.length - 1];
    expect(nextButtonAfter).not.toBeDisabled();
  });
});
