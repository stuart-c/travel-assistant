/**
 * DaySelector - Reusable Day Pill Toggle & Presets Component for Travel Assistant.
 * Manages 8-day selection matrices (Mon–Sun + Bank Holiday) and quick preset buttons
 * (All, Weekdays, Weekends, Clear) across Timetables and Journeys.
 */
window.DaySelector = (function () {
  'use strict';

  const ALL_DAYS = [
    'monday',
    'tuesday',
    'wednesday',
    'thursday',
    'friday',
    'saturday',
    'sunday',
    'bank_holiday',
  ];

  const SHORT_MAP = {
    mon: 'monday',
    tue: 'tuesday',
    wed: 'wednesday',
    thu: 'thursday',
    fri: 'friday',
    sat: 'saturday',
    sun: 'sunday',
    bank_holiday: 'bank_holiday',
  };

  const REV_SHORT_MAP = {
    monday: 'mon',
    tuesday: 'tue',
    wednesday: 'wed',
    thursday: 'thu',
    friday: 'fri',
    saturday: 'sat',
    sunday: 'sun',
    bank_holiday: 'bank_holiday',
  };

  const ACTIVE_CLASSES = [
    'border-sky-500',
    'bg-sky-50',
    'dark:bg-sky-950/50',
    'text-sky-700',
    'dark:text-sky-300',
  ];

  const INACTIVE_CLASSES = [
    'border-slate-200',
    'dark:border-slate-700',
    'bg-white',
    'dark:bg-slate-800',
    'text-slate-500',
    'dark:text-slate-400',
  ];

  /**
   * Binds a DaySelector to a DOM container.
   *
   * @param {Object} options
   * @param {HTMLElement|string} options.container - Container holding the day pills.
   * @param {HTMLElement|string} [options.selectAllBtn] - "All" preset button.
   * @param {HTMLElement|string} [options.selectWeekdaysBtn] - "Weekdays" preset button.
   * @param {HTMLElement|string} [options.selectWeekendsBtn] - "Weekends" preset button.
   * @param {HTMLElement|string} [options.clearAllBtn] - "Clear" preset button.
   * @param {Function} [options.onChange] - Callback invoked when day selection changes: `(daysObj, daysArr) => {}`.
   */
  function bind(options) {
    const {
      container,
      selectAllBtn,
      selectWeekdaysBtn,
      selectWeekendsBtn,
      clearAllBtn,
      onChange,
    } = options || {};

    const containerEl =
      typeof container === 'string'
        ? document.querySelector(container)
        : container;

    if (!containerEl) return null;

    const selectAllEl =
      typeof selectAllBtn === 'string'
        ? document.querySelector(selectAllBtn)
        : selectAllBtn;
    const selectWeekdaysEl =
      typeof selectWeekdaysBtn === 'string'
        ? document.querySelector(selectWeekdaysBtn)
        : selectWeekdaysBtn;
    const selectWeekendsEl =
      typeof selectWeekendsBtn === 'string'
        ? document.querySelector(selectWeekendsBtn)
        : selectWeekendsBtn;
    const clearAllEl =
      typeof clearAllBtn === 'string'
        ? document.querySelector(clearAllBtn)
        : clearAllBtn;

    function getCheckboxes() {
      return Array.from(
        containerEl.querySelectorAll('input[type="checkbox"].day-checkbox')
      );
    }

    function getDayKey(checkbox) {
      const dayData = checkbox.getAttribute('data-day');
      if (dayData) return dayData.toLowerCase();
      const name = checkbox.name || checkbox.id || '';
      const parts = name.split('_');
      const key = parts[parts.length - 1].toLowerCase();
      if (name.includes('bank_holiday') || key === 'holiday') return 'bank_holiday';
      return SHORT_MAP[key] || key;
    }

    function updatePillStyles(checkbox) {
      const label = checkbox.closest('label');
      if (!label) return;

      if (checkbox.checked) {
        label.classList.add(...ACTIVE_CLASSES);
        label.classList.remove(...INACTIVE_CLASSES);
      } else {
        label.classList.remove(...ACTIVE_CLASSES);
        label.classList.add(...INACTIVE_CLASSES);
      }
    }

    function syncAllPills() {
      getCheckboxes().forEach(updatePillStyles);
      if (typeof onChange === 'function') {
        onChange(getDays(), getDaysArray());
      }
    }

    function getDays() {
      const result = {};
      ALL_DAYS.forEach((d) => {
        result[d] = false;
      });
      getCheckboxes().forEach((cb) => {
        const key = getDayKey(cb);
        if (key) {
          result[key] = cb.checked;
        }
      });
      return result;
    }

    function getDaysArray(useShort = true) {
      const result = [];
      getCheckboxes().forEach((cb) => {
        if (cb.checked) {
          const key = getDayKey(cb);
          if (key) {
            result.push(useShort ? REV_SHORT_MAP[key] || key : key);
          }
        }
      });
      return result;
    }

    function setDays(days) {
      const checkboxes = getCheckboxes();
      if (Array.isArray(days)) {
        const norm = days.map((d) => {
          const s = String(d).toLowerCase();
          return SHORT_MAP[s] || s;
        });
        checkboxes.forEach((cb) => {
          const key = getDayKey(cb);
          cb.checked = norm.includes(key);
        });
      } else if (typeof days === 'object' && days !== null) {
        checkboxes.forEach((cb) => {
          const key = getDayKey(cb);
          const val = days[key] !== undefined ? days[key] : (days[REV_SHORT_MAP[key]] !== undefined ? days[REV_SHORT_MAP[key]] : false);
          cb.checked = Boolean(val);
        });
      }
      syncAllPills();
    }

    function selectAll() {
      getCheckboxes().forEach((cb) => {
        cb.checked = true;
      });
      syncAllPills();
    }

    function selectWeekdays() {
      getCheckboxes().forEach((cb) => {
        const key = getDayKey(cb);
        cb.checked = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'].includes(key);
      });
      syncAllPills();
    }

    function selectWeekends() {
      getCheckboxes().forEach((cb) => {
        const key = getDayKey(cb);
        cb.checked = ['saturday', 'sunday'].includes(key);
      });
      syncAllPills();
    }

    function clearAll() {
      getCheckboxes().forEach((cb) => {
        cb.checked = false;
      });
      syncAllPills();
    }

    // Attach checkbox event listeners
    getCheckboxes().forEach((cb) => {
      cb.addEventListener('change', () => {
        updatePillStyles(cb);
        if (typeof onChange === 'function') {
          onChange(getDays(), getDaysArray());
        }
      });
    });

    // Attach preset button event listeners
    if (selectAllEl) {
      selectAllEl.addEventListener('click', (e) => {
        e.preventDefault();
        selectAll();
      });
    }
    if (selectWeekdaysEl) {
      selectWeekdaysEl.addEventListener('click', (e) => {
        e.preventDefault();
        selectWeekdays();
      });
    }
    if (selectWeekendsEl) {
      selectWeekendsEl.addEventListener('click', (e) => {
        e.preventDefault();
        selectWeekends();
      });
    }
    if (clearAllEl) {
      clearAllEl.addEventListener('click', (e) => {
        e.preventDefault();
        clearAll();
      });
    }

    // Initialise styling
    syncAllPills();

    return {
      getDays,
      getDaysArray,
      setDays,
      selectAll,
      selectWeekdays,
      selectWeekends,
      clearAll,
      sync: syncAllPills,
    };
  }

  return {
    bind,
    ALL_DAYS,
    SHORT_MAP,
    REV_SHORT_MAP,
  };
})();
