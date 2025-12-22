/**
 * Time utilities for handling hourly and quarterly resolution data
 */

import { DataResolution } from '../hooks/useUserPreferences';

/**
 * Convert period index to time string
 * @param periodIndex - Period index (0-23 for hourly, 0-95 for quarterly)
 * @param resolution - Data resolution ('hourly' or 'quarter-hourly')
 * @returns Time string in HH:MM format
 */
export const periodToTimeString = (
  periodIndex: number,
  resolution: DataResolution
): string => {
  if (resolution === 'quarter-hourly') {
    const hour = Math.floor(periodIndex / 4);
    const minute = (periodIndex % 4) * 15;
    return `${hour.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}`;
  } else {
    return `${periodIndex.toString().padStart(2, '0')}:00`;
  }
};

/**
 * Get time range string for a period
 * @param periodIndex - Period index
 * @param resolution - Data resolution ('hourly' or 'quarter-hourly')
 * @returns Time range string like "14:30 - 14:45"
 */
export const periodToTimeRange = (
  periodIndex: number,
  resolution: DataResolution
): string => {
  if (resolution === 'quarter-hourly') {
    const startHour = Math.floor(periodIndex / 4);
    const startMinute = (periodIndex % 4) * 15;
    const endPeriod = periodIndex + 1;
    const endHour = Math.floor(endPeriod / 4);
    const endMinute = (endPeriod % 4) * 15;
    return `${startHour.toString().padStart(2, '0')}:${startMinute.toString().padStart(2, '0')} - ${endHour.toString().padStart(2, '0')}:${endMinute.toString().padStart(2, '0')}`;
  } else {
    const endHour = (periodIndex + 1) % 24;
    return `${periodIndex.toString().padStart(2, '0')}:00 - ${endHour.toString().padStart(2, '0')}:00`;
  }
};

/**
 * Get end time string for a period (for two-line display)
 * @param periodIndex - Period index
 * @param resolution - Data resolution ('hourly' or 'quarter-hourly')
 * @returns End time string with dash prefix like "-14:14"
 */
export const periodToEndTime = (
  periodIndex: number,
  resolution: DataResolution
): string => {
  if (resolution === 'quarter-hourly') {
    // End time is the last minute of the 15-minute period
    // E.g., period 57 (14:15-14:30) ends at 14:29
    const startHour = Math.floor(periodIndex / 4);
    const startMinute = (periodIndex % 4) * 15;
    const endMinute = startMinute + 14; // 15-minute period ends 14 minutes after start

    // Handle minute overflow (e.g., 14:45 + 14 = 14:59, not 15:59)
    if (endMinute >= 60) {
      const endHour = startHour + 1;
      const adjustedEndMinute = endMinute - 60;
      return `-${endHour.toString().padStart(2, '0')}:${adjustedEndMinute.toString().padStart(2, '0')}`;
    }

    return `-${startHour.toString().padStart(2, '0')}:${endMinute.toString().padStart(2, '0')}`;
  } else {
    return `-${periodIndex.toString().padStart(2, '0')}:59`;
  }
};
