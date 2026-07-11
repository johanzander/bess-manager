import { useState } from 'react';
import { Calendar, ChevronLeft, ChevronRight } from 'lucide-react';
import DatePicker from 'react-datepicker';
import 'react-datepicker/dist/react-datepicker.css';
import { toISODate } from '../utils/timeUtils';

type DateResolution = 'day' | 'month' | 'year';

const DateSelector = ({
  selectedDate,
  onDateChange,
  maxDate = new Date(new Date().setDate(new Date().getDate() + 1)), // Allow selecting up to tomorrow
  minDate = new Date(new Date().setMonth(new Date().getMonth() - 2)), // Set min date to today minus 2 months
  isLoading = false,
  availableDates = null, // Restrict selection to these ISO dates; null = no restriction (e.g. still loading)
  resolution = 'day',
}: {
  selectedDate: Date;
  onDateChange: (date: Date) => void;
  maxDate?: Date;
  minDate?: Date;
  isLoading?: boolean;
  availableDates?: Set<string> | null;
  resolution?: DateResolution;
}) => {
  const [isOpen, setIsOpen] = useState(false);

  // Format date for display, matching the selected resolution's granularity.
  const formatDisplayDate = (date: Date): string => {
    if (resolution === 'month') {
      return date.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
    }
    if (resolution === 'year') {
      return String(date.getFullYear());
    }
    return date.toLocaleDateString('sv-SE', {
      weekday: 'short',
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    });
  };

  // availableDates holds day-level ISO strings even at month/year
  // resolution — a month/year counts as available if any persisted day
  // falls inside it.
  const isAvailable = (date: Date): boolean => {
    if (!availableDates) return true;
    if (resolution === 'day') return availableDates.has(toISODate(date));
    const prefix =
      resolution === 'month'
        ? `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
        : `${date.getFullYear()}-`;
    for (const d of availableDates) {
      if (d.startsWith(prefix)) return true;
    }
    return false;
  };

  const stepDate = (from: Date, direction: number): Date => {
    const next = new Date(from);
    if (resolution === 'month') {
      next.setMonth(next.getMonth() + direction, 1);
    } else if (resolution === 'year') {
      next.setFullYear(next.getFullYear() + direction, 0, 1);
    } else {
      next.setDate(next.getDate() + direction);
    }
    return next;
  };

  // Walk day/month/year-by-step toward `direction` until an available
  // period is found (skipping gaps in the persisted history) or a bound
  // is hit. The day-level minDate/maxDate props only constrain day
  // resolution (they default to a narrow "last 2 months / tomorrow"
  // window); at month/year resolution, availability is governed solely
  // by availableDates, with an iteration cap as a safety net.
  const findNextAvailable = (from: Date, direction: number): Date | null => {
    let candidate = stepDate(from, direction);
    if (resolution === 'day') {
      while (candidate >= minDate && candidate <= maxDate) {
        if (isAvailable(candidate)) return candidate;
        candidate = stepDate(candidate, direction);
      }
      return null;
    }
    const maxSteps = 1000;
    for (let i = 0; i < maxSteps; i++) {
      if (isAvailable(candidate)) return candidate;
      candidate = stepDate(candidate, direction);
    }
    return null;
  };

  const navigateDay = (direction: number) => {
    const newDate = findNextAvailable(selectedDate, direction);
    if (newDate) {
      onDateChange(newDate);
    }
  };

  const canNavigate = (direction: number): boolean =>
    findNextAvailable(selectedDate, direction) !== null;

  return (
    <div className="relative">
      <div className="bg-white p-4 rounded-lg shadow flex items-center justify-between" style={{ height: '75px', width: '300px' }}>
        <button
          onClick={() => navigateDay(-1)}
          className="p-1 hover:bg-gray-100 rounded-full disabled:opacity-30 disabled:cursor-not-allowed"
          disabled={selectedDate <= minDate || !canNavigate(-1)}
        >
          <ChevronLeft className="w-5 h-5 text-gray-600" />
        </button>
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="flex items-center space-x-2 px-3 py-2 border border-gray-300 rounded-md hover:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
          disabled={isLoading}
        >
          <Calendar className="w-5 h-5 text-gray-600" />
          <span className="text-gray-700">{formatDisplayDate(selectedDate)}</span>
        </button>
        <button
          onClick={() => navigateDay(1)}
          className="p-1 hover:bg-gray-100 rounded-full disabled:opacity-30 disabled:cursor-not-allowed"
          disabled={selectedDate >= maxDate || !canNavigate(1)}
        >
          <ChevronRight className="w-5 h-5 text-gray-600" />
        </button>
      </div>

      {isLoading && (
        <div className="absolute top-full left-0 right-0 pt-2">
          <div className="flex items-center justify-center space-x-2 text-gray-600">
            <div className="animate-spin h-5 w-5 border-2 border-blue-500 rounded-full border-t-transparent"></div>
            <span className="text-sm">Loading...</span>
          </div>
        </div>
      )}

      {isOpen && (
        <div className="absolute top-20 left-0 z-10 w-64 bg-white rounded-lg shadow-lg border border-gray-200">
          <div className="p-2">
            <DatePicker
              selected={selectedDate}
              onChange={(date: Date | null) => {
                if (date) {
                  onDateChange(date);
                  setIsOpen(false);
                }
              }}
              inline
              minDate={minDate}
              maxDate={maxDate}
              filterDate={isAvailable}
              showMonthYearPicker={resolution === 'month'}
              showYearPicker={resolution === 'year'}
            />
          </div>
        </div>
      )}
    </div>
  );
};

export default DateSelector;
