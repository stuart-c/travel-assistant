/**
 * Timetable Time Utilities.
 * Pure helper functions for parsing, formatting, shifting, sorting, and validating transit timetable times.
 */
(function () {
  'use strict';

  // Parse HH:MM into minutes from midnight
  function timeToMinutes(timeStr) {
    if (!timeStr || typeof timeStr !== 'string') return null;
    const parts = timeStr.trim().split(':');
    if (parts.length < 2) return null;
    const h = parseInt(parts[0], 10);
    const m = parseInt(parts[1], 10);
    if (isNaN(h) || isNaN(m)) return null;
    return h * 60 + m;
  }

  // Format minutes from midnight into HH:MM
  function minutesToTime(totalMinutes) {
    let normalised = totalMinutes % (24 * 60);
    if (normalised < 0) normalised += 24 * 60;
    const h = Math.floor(normalised / 60);
    const m = normalised % 60;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  }

  // Add minutes to HH:MM string
  function shiftTime(timeStr, deltaMinutes) {
    const mins = timeToMinutes(timeStr);
    if (mins === null) return '';
    return minutesToTime(mins + deltaMinutes);
  }

  // Check if a time entry is a dual arrival/departure object
  function isDualTiming(timeEntry) {
    return (
      typeof timeEntry === 'object' &&
      timeEntry !== null &&
      ('arr' in timeEntry || 'dep' in timeEntry)
    );
  }

  // Get arrival time in minutes from a time entry (single string or dual object)
  function getTimeArrivalMinutes(timeEntry) {
    if (!timeEntry) return null;
    if (isDualTiming(timeEntry)) {
      if (timeEntry.arr) return timeToMinutes(timeEntry.arr);
      if (timeEntry.dep) return timeToMinutes(timeEntry.dep);
      return null;
    }
    return timeToMinutes(timeEntry);
  }

  // Get departure time in minutes from a time entry (single string or dual object)
  function getTimeDepartureMinutes(timeEntry) {
    if (!timeEntry) return null;
    if (isDualTiming(timeEntry)) {
      if (timeEntry.dep) return timeToMinutes(timeEntry.dep);
      if (timeEntry.arr) return timeToMinutes(timeEntry.arr);
      return null;
    }
    return timeToMinutes(timeEntry);
  }

  // Shift single or dual time entry by deltaMinutes
  function shiftTimeEntry(timeEntry, deltaMinutes) {
    if (!timeEntry) return '';
    if (isDualTiming(timeEntry)) {
      const arr = timeEntry.arr ? shiftTime(timeEntry.arr, deltaMinutes) : '';
      const dep = timeEntry.dep ? shiftTime(timeEntry.dep, deltaMinutes) : '';
      return { arr, dep };
    }
    return shiftTime(timeEntry, deltaMinutes);
  }

  // Get initial departure time in minutes for a trip column
  function getTripFirstDepartureMinutes(trip) {
    if (!trip || !Array.isArray(trip.times)) return null;
    for (let i = 0; i < trip.times.length; i++) {
      const mins = getTimeDepartureMinutes(trip.times[i]);
      if (mins !== null) return mins;
    }
    return null;
  }

  // Sort trips chronologically
  function sortTripsChronologically(trips) {
    return [...trips].sort((a, b) => {
      const aMin = getTripFirstDepartureMinutes(a);
      const bMin = getTripFirstDepartureMinutes(b);
      if (aMin === null && bMin === null) return 0;
      if (aMin === null) return 1;
      if (bMin === null) return -1;
      return aMin - bMin;
    });
  }

  // Validate timing sequences down a trip column
  function validateTripColumn(trip, stopsCount) {
    const times = trip?.times || [];
    const errors = new Set();
    let prevDepMinutes = null;

    for (let sIdx = 0; sIdx < stopsCount; sIdx++) {
      const entry = times[sIdx];
      if (!entry) continue;

      if (isDualTiming(entry)) {
        const arrM = entry.arr ? timeToMinutes(entry.arr) : null;
        const depM = entry.dep ? timeToMinutes(entry.dep) : null;

        if ((entry.arr && arrM === null) || (entry.dep && depM === null)) {
          errors.add(sIdx);
          continue;
        }

        if (arrM !== null && depM !== null && depM < arrM) {
          errors.add(sIdx);
        }

        const stopArrivalM = arrM !== null ? arrM : depM;
        if (
          prevDepMinutes !== null &&
          stopArrivalM !== null &&
          stopArrivalM < prevDepMinutes
        ) {
          errors.add(sIdx);
        }

        if (depM !== null) {
          prevDepMinutes = depM;
        } else if (arrM !== null) {
          prevDepMinutes = arrM;
        }
      } else {
        const currentMinutes = timeToMinutes(entry);
        if (currentMinutes === null) {
          errors.add(sIdx);
          continue;
        }

        if (prevDepMinutes !== null && currentMinutes < prevDepMinutes) {
          errors.add(sIdx);
        }

        prevDepMinutes = currentMinutes;
      }
    }

    return errors;
  }

  window.TimetableTimeUtils = {
    timeToMinutes,
    minutesToTime,
    shiftTime,
    isDualTiming,
    getTimeArrivalMinutes,
    getTimeDepartureMinutes,
    shiftTimeEntry,
    getTripFirstDepartureMinutes,
    sortTripsChronologically,
    validateTripColumn,
  };
})();
