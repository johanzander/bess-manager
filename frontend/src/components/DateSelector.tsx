import { useState } from 'react';
import { Calendar, ChevronLeft, ChevronRight } from 'lucide-react';
import DatePicker from 'react-datepicker';
import 'react-datepicker/dist/react-datepicker.css';

const DateSelector = ({ 
  selectedDate,
  onDateChange,
  maxDate = new Date(new Date().setDate(new Date().getDate() + 1)), // Allow selecting up to tomorrow
  minDate = new Date(new Date().setMonth(new Date().getMonth() - 2)), // Set min date to today minus 2 months
  isLoading = false
}: {
  selectedDate: Date;
  onDateChange: (date: Date) => void;
  maxDate?: Date;
  minDate?: Date;
  isLoading?: boolean;
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

  const navigateDay = (direction: number) => {
    const newDate = new Date(selectedDate);
    newDate.setDate(newDate.getDate() + direction);
    if (newDate >= minDate && newDate <= maxDate) {
      onDateChange(newDate);
    }
  };

  return (
    <div className="relative">
      <div className="bg-white p-4 rounded-lg shadow flex items-center justify-between" style={{ height: '75px', width: '300px' }}>
        <button
          onClick={() => navigateDay(-1)}
          className="p-1 hover:bg-gray-100 rounded-full"
          disabled={selectedDate <= minDate}
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
          className="p-1 hover:bg-gray-100 rounded-full"
          disabled={selectedDate >= maxDate}
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
              onChange={(date) => {
                if (date) {
                  onDateChange(date);
                  setIsOpen(false);
                }
              }}
              inline
              minDate={minDate}
              maxDate={maxDate}
            />
          </div>
        </div>
      )}
    </div>
  );
};

export default DateSelector;