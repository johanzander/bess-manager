import { useState } from 'react';
import { Calendar, ChevronLeft, ChevronRight } from 'lucide-react';
import DatePicker from 'react-datepicker';
import 'react-datepicker/dist/react-datepicker.css';
import { toISODate } from '../utils/timeUtils';

const DateSelector = ({
  selectedDate,
  onDateChange,
  maxDate = new Date(new Date().setDate(new Date().getDate() + 1)), // Allow selecting up to tomorrow
  minDate = new Date(new Date().setMonth(new Date().getMonth() - 2)), // Set min date to today minus 2 months
  isLoading = false,
  availableDates = null, // Restrict selection to these ISO dates; null = no restriction (e.g. still loading)
}: {
  selectedDate: Date;
  onDateChange: (date: Date) => void;
  maxDate?: Date;
  minDate?: Date;
  isLoading?: boolean;
  availableDates?: Set<string> | null;
}) => {
  const [isOpen, setIsOpen] = useState(false);

  // Format date for display
  const formatDisplayDate = (date: Date): string => {
    return date.toLocaleDateString('sv-SE', {
      weekday: 'short',
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    });
  };

  const isAvailable = (date: Date): boolean =>
    !availableDates || availableDates.has(toISODate(date));

  // Walk day-by-day toward `direction` until an available date is found
  // (skipping gaps in the persisted history) or the min/max bound is hit.
  const findNextAvailable = (from: Date, direction: number): Date | null => {
    const candidate = new Date(from);
    while (true) {
      candidate.setDate(candidate.getDate() + direction);
      if (candidate < minDate || candidate > maxDate) return null;
      if (isAvailable(candidate)) return candidate;
    }
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
            />
          </div>
        </div>
      )}
    </div>
  );
};

export default DateSelector;