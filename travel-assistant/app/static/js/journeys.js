/**
 * Journeys Configuration Controller
 * 
 * Manages client-side staged state for Travel Journeys with Grid.js and
 * an interactive modal dialogue featuring multi-location live search autocompletion
 * (Rail Stations, Bus Stops, Home Assistant, and Custom Locations) and dynamic
 * multi-time-window scheduling.
 */

document.addEventListener('DOMContentLoaded', () => {
  const configEl =
    document.getElementById('journeys-config') ||
    document.getElementById('journeys-form');
  if (!configEl) return;

  const searchBaseUrl =
    configEl.getAttribute('data-search-url') || '/config/search/places';
  const dataUrl =
    configEl.getAttribute('data-data-url') || '/config/journeys/data';

  // Staged changeset state manager
  const changesetManager =
    window.TransitUI && window.TransitUI.createStagedChangesetManager
      ? window.TransitUI.createStagedChangesetManager('id')
      : new window.TransitUI.StagedChangesetManager('id');

  let currentPageItems = [];

  // DOM Elements
  const gridWrapper = document.getElementById('journeys-grid-wrapper');
  const emptyState = document.getElementById('journeys-grid-empty-state');

  // Modal Elements
  const modal = document.getElementById('journey-modal');
  const openAddBtn = document.getElementById('open-add-journey-modal-btn');
  const emptyAddBtn = document.getElementById('empty-add-journey-btn');
  const closeModalBtn = document.getElementById('close-journey-modal-btn');
  const cancelModalBtn = document.getElementById('cancel-journey-modal-btn');
  const confirmBtn = document.getElementById('confirm-journey-btn');
  const modalTitle = document.getElementById('journey-modal-title');
  const modalIcon = document.getElementById('journey-modal-icon');
  const editIndexInput = document.getElementById('edit-journey-index');
  const journeyNameInput = document.getElementById('journey_name');
  const modalError = document.getElementById('journey-modal-error');

  // From Location Elements
  const fromSearchInput = document.getElementById('from-journey-search');
  const fromSuggestions = document.getElementById('from-journey-suggestions');
  const fromTypeInput = document.getElementById('from_journey_type');
  const fromIdInput = document.getElementById('from_journey_id');
  const fromNameInput = document.getElementById('from_journey_name');
  const fromPreview = document.getElementById('from-selected-preview');
  const fromPreviewIcon = document.getElementById('from-preview-icon');
  const fromPreviewName = document.getElementById('from-preview-name');
  const fromPreviewId = document.getElementById('from-preview-id');
  const clearFromBtn = document.getElementById('clear-from-selection');

  // To Location Elements
  const toSearchInput = document.getElementById('to-journey-search');
  const toSuggestions = document.getElementById('to-journey-suggestions');
  const toTypeInput = document.getElementById('to_journey_type');
  const toIdInput = document.getElementById('to_journey_id');
  const toNameInput = document.getElementById('to_journey_name');
  const toPreview = document.getElementById('to-selected-preview');
  const toPreviewIcon = document.getElementById('to-preview-icon');
  const toPreviewName = document.getElementById('to-preview-name');
  const toPreviewId = document.getElementById('to-preview-id');
  const clearToBtn = document.getElementById('clear-to-selection');

  // Time Windows Elements
  const timeWindowsList = document.getElementById('time-windows-list');
  const timeWindowsEmptyNotice = document.getElementById('time-windows-empty-notice');
  const addTimeWindowBtn = document.getElementById('add-time-window-btn');

  // Modal Tabs & Calculated Routes Elements
  const tabDetails = document.getElementById('journey-tab-details');
  const tabRoutes = document.getElementById('journey-tab-routes');
  const panelDetails = document.getElementById('journey-panel-details');
  const panelRoutes = document.getElementById('journey-panel-routes');
  const dagContainer = document.getElementById('journey-routes-dag-container');
  const routesSummaryText = document.getElementById('journey-routes-summary-text');
  const routesEmptyState = document.getElementById('journey-routes-empty-state');
  const routesFitBtn = document.getElementById('journey-routes-fit-btn');

  const escapeHtml = (window.TransitUI && window.TransitUI.escapeHtml) || ((str) => (str ? String(str) : ''));
  const getLocationBadge = (window.TransitUI && window.TransitUI.getTransportBadge) || ((type) => type);
  const getLocationIcon = (window.TransitUI && window.TransitUI.getTransportIcon) || (() => 'pin_drop');
  const formatDaysSummary = (window.TransitUI && window.TransitUI.formatDaysSummary) || ((days) => (days || []).join(', '));


  function formatScheduleSummary(timeSettings) {
    if (!timeSettings || !timeSettings.length) {
      return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300">
        <span class="material-symbols-outlined text-xs leading-none text-slate-400">all_inclusive</span> Anytime (All days)
      </span>`;
    }

    const items = timeSettings.map(tw => {
      const daysText = formatDaysSummary(tw.days);
      const modeText = tw.mode === 'arrive' ? 'Arrive' : 'Depart';
      let timeText = '';
      if (tw.start_time && tw.end_time) {
        timeText = `${modeText} ${tw.start_time} – ${tw.end_time}`;
      } else if (tw.start_time) {
        timeText = `${modeText} after ${tw.start_time}`;
      } else if (tw.end_time) {
        timeText = `${modeText} before ${tw.end_time}`;
      } else {
        timeText = `${modeText} anytime`;
      }

      return `<div class="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs bg-slate-100/90 dark:bg-slate-800/80 border border-slate-200/60 dark:border-slate-700/60 text-slate-800 dark:text-slate-200">
        <span class="material-symbols-outlined text-xs text-sky-500">schedule</span>
        <span class="font-semibold">${escapeHtml(daysText)}:</span>
        <span>${escapeHtml(timeText)}</span>
      </div>`;
    });

    return `<div class="flex flex-col gap-1">${items.join('')}</div>`;
  }

  // --- Grid.js Data Formatter ---
  function formatGridData(items) {
    return items.map((item, index) => {
      const fromBadge = getLocationBadge(item.from_type);
      const toBadge = getLocationBadge(item.to_type);
      const scheduleHtml = formatScheduleSummary(item.time_settings);

      return [
        gridjs.html(`
          <div class="flex flex-col gap-0.5">
            <span class="font-bold text-slate-900 dark:text-slate-100 text-sm">${escapeHtml(item.name)}</span>
            <div class="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
              <span class="truncate max-w-[140px]">${escapeHtml(item.from_name)}</span>
              <span class="material-symbols-outlined text-xs">arrow_forward</span>
              <span class="truncate max-w-[140px]">${escapeHtml(item.to_name)}</span>
            </div>
          </div>
        `),
        gridjs.html(`
          <div class="flex flex-col gap-1">
            <div class="flex items-center gap-1.5">
              ${fromBadge}
              <span class="font-semibold text-slate-900 dark:text-slate-100">${escapeHtml(item.from_name)}</span>
            </div>
            <span class="text-xs font-mono text-slate-500 dark:text-slate-400">${escapeHtml(item.from_id)}</span>
          </div>
        `),
        gridjs.html(`
          <div class="flex flex-col gap-1">
            <div class="flex items-center gap-1.5">
              ${toBadge}
              <span class="font-semibold text-slate-900 dark:text-slate-100">${escapeHtml(item.to_name)}</span>
            </div>
            <span class="text-xs font-mono text-slate-500 dark:text-slate-400">${escapeHtml(item.to_id)}</span>
          </div>
        `),
        gridjs.html(scheduleHtml),
        gridjs.html(
          window.TransitUI && window.TransitUI.renderActionButtons
            ? window.TransitUI.renderActionButtons({
                index,
                editClass: 'edit-journey-btn',
                deleteClass: 'delete-journey-btn',
                editTitle: 'Edit journey',
                deleteTitle: 'Delete journey',
              })
            : `<div class="flex items-center gap-1.5">
                <button 
                  type="button" 
                  class="edit-journey-btn inline-flex items-center justify-center w-7 h-7 rounded-lg bg-sky-50 text-sky-600 hover:bg-sky-100 hover:text-sky-700 dark:bg-sky-950/50 dark:text-sky-400 dark:hover:bg-sky-900/60 transition-colors cursor-pointer" 
                  data-index="${index}" 
                  title="Edit journey"
                  aria-label="Edit journey"
                >
                  <span class="material-symbols-outlined text-[17px] leading-none">edit</span>
                </button>
                <button 
                  type="button" 
                  class="delete-journey-btn inline-flex items-center justify-center w-7 h-7 rounded-lg bg-rose-50 text-rose-600 hover:bg-rose-100 hover:text-rose-700 dark:bg-rose-950/50 dark:text-rose-400 dark:hover:bg-rose-900/60 transition-colors cursor-pointer" 
                  data-index="${index}" 
                  title="Delete journey"
                  aria-label="Delete journey"
                >
                  <span class="material-symbols-outlined text-[17px] leading-none">delete</span>
                </button>
              </div>`
        ),
      ];
    });
  }

  // --- Grid Instance ---
  const columnsConfig = [
    { name: 'Journey', width: '26%', sort: true },
    { name: 'Start Location', width: '23%', sort: true },
    { name: 'End Location', width: '23%', sort: true },
    { name: 'Schedule', width: '20%', sort: false },
    { name: 'Actions', width: '90px', sort: false },
  ];

  const columnSortMap = {
    0: 'name',
    1: 'from_name',
    2: 'to_name',
  };

  function syncEmptyState(total) {
    const effectiveTotal = Math.max(
      0,
      (Number(total) || 0) +
        changesetManager.added.length -
        changesetManager.deleted.size
    );
    if (effectiveTotal === 0) {
      if (emptyState) emptyState.classList.remove('hidden');
      if (gridWrapper) gridWrapper.classList.add('hidden');
    } else {
      if (emptyState) emptyState.classList.add('hidden');
      if (gridWrapper) gridWrapper.classList.remove('hidden');
    }
  }

  function updateDirtyState() {
    if (window.ConfigDirtyManager) {
      if (changesetManager.isDirty()) {
        window.ConfigDirtyManager.markDirty();
      } else {
        window.ConfigDirtyManager.clearDirty();
      }
    }
  }

  const gridInstance = new gridjs.Grid({
    columns: columnsConfig,
    server: {
      url: dataUrl,
      then: (data) => {
        const rawItems = Array.isArray(data.data) ? data.data : [];
        currentPageItems = changesetManager.applyOverlay(rawItems);
        syncEmptyState(data.total);
        return formatGridData(currentPageItems);
      },
      total: (data) => {
        const serverTotal = Number(data.total) || 0;
        return Math.max(
          0,
          serverTotal +
            changesetManager.added.length -
            changesetManager.deleted.size
        );
      },
    },
    pagination: {
      enabled: true,
      limit: 10,
      summary: true,
      server: {
        url: (prev, page, limit) => {
          const u = new URL(prev, window.location.origin);
          u.searchParams.set('limit', limit);
          u.searchParams.set('offset', page * limit);
          return u.pathname + u.search;
        },
      },
    },
    sort: {
      multiColumn: false,
      server: {
        url: (prev, columns) => {
          const u = new URL(prev, window.location.origin);
          if (!columns || !columns.length) return u.pathname + u.search;
          const col = columns[0];
          const fieldName = columnSortMap[col.index];
          if (fieldName) {
            u.searchParams.set('sort_by', fieldName);
            u.searchParams.set('order', col.direction === 1 ? 'asc' : 'desc');
          }
          return u.pathname + u.search;
        },
      },
    },
    search: {
      enabled: true,
      placeholder: 'Search journeys...',
    },
    className: {
      table: 'w-full text-left text-sm',
      th: 'py-3.5 px-4 font-semibold text-slate-700 dark:text-slate-300 bg-slate-50 dark:bg-slate-800/80 border-b border-slate-200 dark:border-slate-700',
      td: 'py-3.5 px-4 border-b border-slate-100 dark:border-slate-800/80 text-slate-600 dark:text-slate-300 align-middle',
    },
    language: {
      search: { placeholder: 'Search journeys...' },
      pagination: {
        showing: 'Showing',
        of: 'of',
        to: 'to',
        results: 'journeys',
      },
      noRecordsFound: 'No matching journeys found',
    },
  });

  if (gridWrapper) {
    gridInstance.render(gridWrapper);
  }

  function syncDirtyState() {
    if (window.ConfigDirtyManager) {
      if (changesetManager.isDirty()) {
        window.ConfigDirtyManager.markDirty();
      } else {
        window.ConfigDirtyManager.clearDirty();
      }
    }
  }

  // --- Location Autocomplete Component ---
  const fromAutocomplete = window.PlaceAutocomplete
    ? window.PlaceAutocomplete.bindSelection({
        searchInput: fromSearchInput,
        suggestionsContainer: fromSuggestions,
        typeInput: fromTypeInput,
        idInput: fromIdInput,
        nameInput: fromNameInput,
        previewContainer: fromPreview,
        previewIcon: fromPreviewIcon,
        previewName: fromPreviewName,
        previewId: fromPreviewId,
        clearBtn: clearFromBtn,
      })
    : null;

  const toAutocomplete = window.PlaceAutocomplete
    ? window.PlaceAutocomplete.bindSelection({
        searchInput: toSearchInput,
        suggestionsContainer: toSuggestions,
        typeInput: toTypeInput,
        idInput: toIdInput,
        nameInput: toNameInput,
        previewContainer: toPreview,
        previewIcon: toPreviewIcon,
        previewName: toPreviewName,
        previewId: toPreviewId,
        clearBtn: clearToBtn,
      })
    : null;


  // --- Dynamic Time Windows Builder ---
  const ALL_DAYS = [
    { key: 'mon', label: 'Mon' },
    { key: 'tue', label: 'Tue' },
    { key: 'wed', label: 'Wed' },
    { key: 'thu', label: 'Thu' },
    { key: 'fri', label: 'Fri' },
    { key: 'sat', label: 'Sat' },
    { key: 'sun', label: 'Sun' },
    { key: 'bank_holiday', label: 'Bank Hol' },
  ];

  function createTimeWindowCard(twData = {}) {
    const card = document.createElement('div');
    card.className = 'time-window-card p-4 rounded-xl border border-slate-200 dark:border-slate-700/80 bg-slate-50/50 dark:bg-slate-800/40 space-y-3 relative';

    const selectedDays = new Set(twData.days || []);
    const mode = twData.mode === 'arrive' ? 'arrive' : 'depart';
    const startTime = twData.start_time || '';
    const endTime = twData.end_time || '';

    card.innerHTML = `
      <div class="flex items-center justify-between pb-2 border-b border-slate-200/60 dark:border-slate-700/60">
        <div class="flex items-center gap-2">
          <span class="material-symbols-outlined text-sky-600 dark:text-sky-400 text-sm">schedule</span>
          <span class="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300">Time Window</span>
        </div>
        <button 
          type="button" 
          class="remove-time-window-btn text-slate-400 hover:text-rose-600 dark:hover:text-rose-400 p-1 rounded-lg transition-colors cursor-pointer"
          title="Remove time window"
        >
          <span class="material-symbols-outlined text-base">delete</span>
        </button>
      </div>

      <!-- Days of the Week Selection -->
      <div>
        <div class="flex flex-wrap items-center justify-between gap-1 mb-1.5">
          <label class="block text-[11px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-400">
            Active Days
          </label>
          <!-- Quick Preset Buttons -->
          <div class="flex items-center gap-1 text-[11px]">
            <button type="button" class="preset-btn px-1.5 py-0.5 rounded text-slate-500 hover:text-sky-600 hover:bg-sky-50 dark:hover:bg-slate-700 cursor-pointer" data-preset="weekdays">Weekdays</button>
            <span class="text-slate-300 dark:text-slate-600">|</span>
            <button type="button" class="preset-btn px-1.5 py-0.5 rounded text-slate-500 hover:text-sky-600 hover:bg-sky-50 dark:hover:bg-slate-700 cursor-pointer" data-preset="weekends">Weekends</button>
            <span class="text-slate-300 dark:text-slate-600">|</span>
            <button type="button" class="preset-btn px-1.5 py-0.5 rounded text-slate-500 hover:text-sky-600 hover:bg-sky-50 dark:hover:bg-slate-700 cursor-pointer" data-preset="all">All</button>
            <span class="text-slate-300 dark:text-slate-600">|</span>
            <button type="button" class="preset-btn px-1.5 py-0.5 rounded text-slate-500 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-slate-700 cursor-pointer" data-preset="clear">Clear</button>
          </div>
        </div>

        <div class="flex flex-wrap gap-1.5 day-buttons-container">
          ${ALL_DAYS.map(day => `
            <button 
              type="button" 
              class="day-pill-btn px-2.5 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                selectedDays.has(day.key)
                  ? 'border border-sky-500 bg-sky-50 dark:bg-sky-950/50 text-sky-700 dark:text-sky-300 font-bold'
                  : 'bg-white text-slate-500 border border-slate-200 hover:bg-slate-100 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700 dark:hover:bg-slate-700'
              }"
              data-day="${day.key}"
            >
              ${day.label}
            </button>
          `).join('')}
        </div>
      </div>

      <!-- Mode & Time Inputs Grid -->
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 items-end">
        <div>
          <label class="block text-[11px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-400 mb-1">
            Time Mode
          </label>
          <div class="inline-flex rounded-xl border border-slate-300 dark:border-slate-700 p-0.5 bg-white dark:bg-slate-800 w-full">
            <button 
              type="button" 
              class="mode-btn flex-1 py-1.5 text-xs font-semibold rounded-lg transition-colors cursor-pointer ${
                mode === 'depart'
                  ? 'bg-sky-600 text-white'
                  : 'text-slate-600 dark:text-slate-300 hover:text-slate-900'
              }"
              data-mode="depart"
            >
              Depart During
            </button>
            <button 
              type="button" 
              class="mode-btn flex-1 py-1.5 text-xs font-semibold rounded-lg transition-colors cursor-pointer ${
                mode === 'arrive'
                  ? 'bg-sky-600 text-white'
                  : 'text-slate-600 dark:text-slate-300 hover:text-slate-900'
              }"
              data-mode="arrive"
            >
              Arrive During
            </button>
          </div>
        </div>

        <div>
          <label class="block text-[11px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-400 mb-1">
            From Time
          </label>
          <input 
            type="text" 
            list="time-intervals-datalist"
            placeholder="08:00"
            class="start-time-input w-full px-3 py-1.5 rounded-xl border border-slate-300 bg-white text-xs font-mono text-slate-900 focus:border-sky-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100" 
            value="${startTime}"
          >
        </div>

        <div>
          <label class="block text-[11px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-400 mb-1">
            To Time
          </label>
          <input 
            type="text" 
            list="time-intervals-datalist"
            placeholder="09:30"
            class="end-time-input w-full px-3 py-1.5 rounded-xl border border-slate-300 bg-white text-xs font-mono text-slate-900 focus:border-sky-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100" 
            value="${endTime}"
          >
        </div>
      </div>
    `;

    // Remove Card Handler
    card.querySelector('.remove-time-window-btn').addEventListener('click', () => {
      card.remove();
      updateTimeWindowsEmptyNotice();
    });

    // Day Pill Buttons Handler
    card.querySelectorAll('.day-pill-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const dayKey = btn.getAttribute('data-day');
        if (selectedDays.has(dayKey)) {
          selectedDays.delete(dayKey);
          btn.className = 'day-pill-btn px-2.5 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer bg-white text-slate-500 border border-slate-200 hover:bg-slate-100 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700 dark:hover:bg-slate-700';
        } else {
          selectedDays.add(dayKey);
          btn.className = 'day-pill-btn px-2.5 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer border border-sky-500 bg-sky-50 dark:bg-sky-950/50 text-sky-700 dark:text-sky-300';
        }
      });
    });

    // Presets Handlers
    card.querySelectorAll('.preset-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const preset = btn.getAttribute('data-preset');
        selectedDays.clear();

        if (preset === 'weekdays') {
          ['mon', 'tue', 'wed', 'thu', 'fri'].forEach(d => selectedDays.add(d));
        } else if (preset === 'weekends') {
          ['sat', 'sun'].forEach(d => selectedDays.add(d));
        } else if (preset === 'all') {
          ALL_DAYS.forEach(d => selectedDays.add(d.key));
        }

        card.querySelectorAll('.day-pill-btn').forEach(pBtn => {
          const dKey = pBtn.getAttribute('data-day');
          if (selectedDays.has(dKey)) {
            pBtn.className = 'day-pill-btn px-2.5 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer border border-sky-500 bg-sky-50 dark:bg-sky-950/50 text-sky-700 dark:text-sky-300';
          } else {
            pBtn.className = 'day-pill-btn px-2.5 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer bg-white text-slate-500 border border-slate-200 hover:bg-slate-100 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700 dark:hover:bg-slate-700';
          }
        });
      });
    });

    // Mode Selector Handler
    let activeMode = mode;
    card.querySelectorAll('.mode-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        activeMode = btn.getAttribute('data-mode');
        card.querySelectorAll('.mode-btn').forEach(b => {
          if (b.getAttribute('data-mode') === activeMode) {
            b.className = 'mode-btn flex-1 py-1.5 text-xs font-semibold rounded-lg transition-colors cursor-pointer bg-sky-600 text-white';
          } else {
            b.className = 'mode-btn flex-1 py-1.5 text-xs font-semibold rounded-lg transition-colors cursor-pointer text-slate-600 dark:text-slate-300 hover:text-slate-900';
          }
        });
      });
    });

    // Expose data getter on element
    card.getData = () => {
      return {
        days: Array.from(selectedDays),
        mode: activeMode,
        start_time: card.querySelector('.start-time-input').value.trim(),
        end_time: card.querySelector('.end-time-input').value.trim(),
      };
    };

    return card;
  }

  function updateTimeWindowsEmptyNotice() {
    if (!timeWindowsList || !timeWindowsEmptyNotice) return;
    const count = timeWindowsList.querySelectorAll('.time-window-card').length;
    if (count === 0) {
      timeWindowsEmptyNotice.classList.remove('hidden');
    } else {
      timeWindowsEmptyNotice.classList.add('hidden');
    }
  }

  if (addTimeWindowBtn) {
    addTimeWindowBtn.addEventListener('click', () => {
      const card = createTimeWindowCard();
      timeWindowsList.appendChild(card);
      updateTimeWindowsEmptyNotice();
    });
  }

  // --- Modal Tabs & Calculated Routes Management ---
  let isRoutesTabEnabled = false;
  let currentNetwork = null;
  let activeJourneyItem = null;

  const MODE_CONFIG = {
    walk: {
      colour: '#64748b',
      label: 'Walk',
      dashes: [4, 4],
      icon: 'directions_walk',
    },
    bus: {
      colour: '#d97706',
      label: 'Bus',
      dashes: false,
      icon: 'directions_bus',
    },
    rail: {
      colour: '#4f46e5',
      label: 'Train',
      dashes: false,
      icon: 'train',
    },
    train: {
      colour: '#4f46e5',
      label: 'Train',
      dashes: false,
      icon: 'train',
    },
    metro: {
      colour: '#059669',
      label: 'Metro',
      dashes: false,
      icon: 'subway',
    },
    tram: {
      colour: '#ea580c',
      label: 'Tram',
      dashes: false,
      icon: 'tram',
    },
    ferry: {
      colour: '#0891b2',
      label: 'Ferry',
      dashes: false,
      icon: 'directions_boat',
    },
    air: {
      colour: '#9333ea',
      label: 'Flight',
      dashes: false,
      icon: 'flight',
    },
    interchange: {
      colour: '#64748b',
      label: 'Interchange',
      dashes: [2, 2],
      icon: 'swap_horiz',
    },
    platform_transfer: {
      colour: '#64748b',
      label: 'Transfer',
      dashes: [2, 2],
      icon: 'transfer_within_a_station',
    },
    custom: {
      colour: '#0284c7',
      label: 'Transit',
      dashes: false,
      icon: 'pin_drop',
    },
  };

  function getModeConfig(mode, legType) {
    const key = String(mode || legType || 'custom').toLowerCase();
    return MODE_CONFIG[key] || MODE_CONFIG.custom;
  }

  function isDarkMode() {
    return (
      document.documentElement.classList.contains('dark') ||
      (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches)
    );
  }

  function createEdgeTooltip(leg) {
    const modeCfg = getModeConfig(leg.transport_mode, leg.leg_type);
    const modeName = leg.transport_mode
      ? leg.transport_mode.charAt(0).toUpperCase() + leg.transport_mode.slice(1)
      : leg.leg_type === 'walk'
      ? 'Walking'
      : 'Transit';
    const lineHeading = leg.line_name ? `${modeName} ${leg.line_name}` : modeName;

    const parts = [];
    parts.push(
      `<div style="font-weight: 700; margin-bottom: 4px; color: ${modeCfg.colour}; font-size: 13px;">${escapeHtml(
        lineHeading
      )}</div>`
    );

    if (leg.operator_name) {
      parts.push(
        `<div style="margin-bottom: 2px;"><strong>Operator:</strong> ${escapeHtml(
          leg.operator_name
        )}</div>`
      );
    }
    if (leg.duration_minutes !== undefined && leg.duration_minutes !== null) {
      parts.push(
        `<div style="margin-bottom: 2px;"><strong>Duration:</strong> ~${leg.duration_minutes} min${
          leg.duration_minutes === 1 ? '' : 's'
        }</div>`
      );
    }
    if (leg.distance_m) {
      const distKm = (leg.distance_m / 1000).toFixed(1);
      const distStr = leg.distance_m >= 1000 ? `${distKm} km` : `${leg.distance_m} m`;
      parts.push(
        `<div style="margin-bottom: 2px;"><strong>Distance:</strong> ${distStr}</div>`
      );
    }
    if (leg.stops_count) {
      parts.push(
        `<div style="margin-bottom: 2px;"><strong>Stops:</strong> ${leg.stops_count} intermediate</div>`
      );
    }
    parts.push(
      `<div style="margin-top: 6px; padding-top: 4px; border-top: 1px dashed rgba(148, 163, 184, 0.4); font-size: 11px; opacity: 0.85;">${escapeHtml(
        leg.from_name || 'Start'
      )} &rarr; ${escapeHtml(leg.to_name || 'End')}</div>`
    );

    const tooltipEl = document.createElement('div');
    tooltipEl.innerHTML = parts.join('');
    return tooltipEl;
  }

  function renderJourneyRoutesDag(routesData, item) {
    if (currentNetwork) {
      currentNetwork.destroy();
      currentNetwork = null;
    }

    if (!dagContainer) return;

    // Parse routes
    let routes = [];
    if (typeof routesData === 'string') {
      try {
        routes = JSON.parse(routesData);
      } catch (e) {
        routes = [];
      }
    } else if (Array.isArray(routesData)) {
      routes = routesData;
    } else if (routesData && typeof routesData === 'object') {
      routes = [routesData];
    }

    if (!routes || routes.length === 0) {
      if (routesEmptyState) routesEmptyState.classList.remove('hidden');
      if (routesSummaryText) {
        routesSummaryText.textContent = 'No calculated routes available for this journey.';
      }
      return;
    }

    if (routesEmptyState) routesEmptyState.classList.add('hidden');
    if (routesSummaryText) {
      const count = routes.length;
      routesSummaryText.textContent = `${count} topological route corridor${
        count === 1 ? '' : 's'
      } discovered connecting origin to destination.`;
    }

    const dark = isDarkMode();
    const nodesMap = new Map();
    const edgesList = [];
    const edgeKeySet = new Set();

    const originName = (item && item.from_name) || 'Origin';
    const destName = (item && item.to_name) || 'Destination';
    const originId = (item && item.from_id) || '';
    const destId = (item && item.to_id) || '';

    // 1. Fixed Origin Node (Top)
    nodesMap.set('NODE_ORIGIN', {
      id: 'NODE_ORIGIN',
      label: `🚩 ${originName}\n(Start)`,
      title: `Origin: ${originName}${originId ? ` (${originId})` : ''}`,
      shape: 'box',
      margin: { top: 10, bottom: 10, left: 14, right: 14 },
      shapeProperties: { borderRadius: 10 },
      color: {
        background: dark ? '#064e3b' : '#ecfdf5',
        border: dark ? '#34d399' : '#10b981',
        highlight: {
          background: dark ? '#065f46' : '#d1fae5',
          border: '#10b981',
        },
        hover: {
          background: dark ? '#065f46' : '#d1fae5',
          border: '#10b981',
        },
      },
      font: {
        color: dark ? '#ecfdf5' : '#065f46',
        bold: { color: dark ? '#ffffff' : '#064e3b' },
        size: 13,
        face: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      },
      borderWidth: 2,
      shadow: {
        enabled: true,
        color: dark ? 'rgba(0,0,0,0.5)' : 'rgba(16,185,129,0.15)',
        size: 6,
        x: 0,
        y: 2,
      },
    });

    // 2. Fixed Destination Node (Bottom)
    nodesMap.set('NODE_DESTINATION', {
      id: 'NODE_DESTINATION',
      label: `🏁 ${destName}\n(End)`,
      title: `Destination: ${destName}${destId ? ` (${destId})` : ''}`,
      shape: 'box',
      margin: { top: 10, bottom: 10, left: 14, right: 14 },
      shapeProperties: { borderRadius: 10 },
      color: {
        background: dark ? '#4c0519' : '#fff1f2',
        border: dark ? '#fb7185' : '#f43f5e',
        highlight: {
          background: dark ? '#881337' : '#ffe4e6',
          border: '#f43f5e',
        },
        hover: {
          background: dark ? '#881337' : '#ffe4e6',
          border: '#f43f5e',
        },
      },
      font: {
        color: dark ? '#ffe4e6' : '#881337',
        bold: { color: dark ? '#ffffff' : '#4c0519' },
        size: 13,
        face: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      },
      borderWidth: 2,
      shadow: {
        enabled: true,
        color: dark ? 'rgba(0,0,0,0.5)' : 'rgba(244,63,94,0.15)',
        size: 6,
        x: 0,
        y: 2,
      },
    });

    function getStopNodeId(id, name, type) {
      if (!id && !name) return 'stop_unknown';
      return `stop_${type || 'loc'}_${id || name}`;
    }

    function addStopNode(nodeId, name, type) {
      if (nodesMap.has(nodeId)) return;
      nodesMap.set(nodeId, {
        id: nodeId,
        label: `🚏 ${name || 'Stop'}`,
        title: `Stop: ${name || 'Stop'}${type ? ` (${type})` : ''}`,
        shape: 'box',
        margin: { top: 8, bottom: 8, left: 12, right: 12 },
        shapeProperties: { borderRadius: 8 },
        color: {
          background: dark ? '#1e293b' : '#f8fafc',
          border: dark ? '#475569' : '#cbd5e1',
          highlight: {
            background: dark ? '#334155' : '#e2e8f0',
            border: dark ? '#94a3b8' : '#64748b',
          },
          hover: {
            background: dark ? '#334155' : '#e2e8f0',
            border: dark ? '#94a3b8' : '#64748b',
          },
        },
        font: {
          color: dark ? '#f1f5f9' : '#1e293b',
          size: 12,
          face: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        },
        borderWidth: 1.5,
        shadow: {
          enabled: true,
          color: dark ? 'rgba(0,0,0,0.4)' : 'rgba(0,0,0,0.06)',
          size: 4,
          x: 0,
          y: 1,
        },
      });
    }

    // 3. Process each route corridor and its legs
    routes.forEach(route => {
      if (!route || !Array.isArray(route.legs) || route.legs.length === 0) return;

      const legs = route.legs;
      legs.forEach((leg, index) => {
        let fromNodeId;
        if (
          index === 0 ||
          leg.from_id === originId ||
          leg.from_name === originName
        ) {
          fromNodeId = 'NODE_ORIGIN';
        } else {
          fromNodeId = getStopNodeId(leg.from_id, leg.from_name, leg.from_type);
          addStopNode(fromNodeId, leg.from_name, leg.from_type);
        }

        let toNodeId;
        if (
          index === legs.length - 1 ||
          leg.to_id === destId ||
          leg.to_name === destName
        ) {
          toNodeId = 'NODE_DESTINATION';
        } else {
          toNodeId = getStopNodeId(leg.to_id, leg.to_name, leg.to_type);
          addStopNode(toNodeId, leg.to_name, leg.to_type);
        }

        const modeCfg = getModeConfig(leg.transport_mode, leg.leg_type);
        const edgeKey = `${fromNodeId}->${toNodeId}:${leg.transport_mode || leg.leg_type}:${leg.line_name || ''}:${leg.operator_name || ''}`;

        if (!edgeKeySet.has(edgeKey)) {
          edgeKeySet.add(edgeKey);
          edgesList.push({
            id: `edge_${edgeKeySet.size}`,
            from: fromNodeId,
            to: toNodeId,
            arrows: {
              to: {
                enabled: true,
                scaleFactor: 0.85,
              },
            },
            width: 2.5,
            color: {
              color: modeCfg.colour,
              highlight: modeCfg.colour,
              hover: modeCfg.colour,
              opacity: 0.9,
            },
            dashes: modeCfg.dashes,
            title: createEdgeTooltip(leg),
            smooth: {
              type: 'cubicBezier',
              forceDirection: 'vertical',
              roundness: 0.35,
            },
          });
        }
      });
    });

    if (typeof vis === 'undefined' || !vis.Network) {
      console.warn('vis-network library not loaded.');
      return;
    }

    const networkData = {
      nodes: new vis.DataSet(Array.from(nodesMap.values())),
      edges: new vis.DataSet(edgesList),
    };

    const networkOptions = {
      layout: {
        hierarchical: {
          enabled: true,
          direction: 'UD', // Vertical DAG layout (top to bottom)
          sortMethod: 'directed',
          levelSeparation: 90,
          nodeSpacing: 180,
          shakeTowards: 'leaves',
        },
      },
      physics: {
        enabled: false,
      },
      interaction: {
        hover: true,
        hoverConnectedEdges: true,
        selectConnectedEdges: true,
        tooltipDelay: 80,
        zoomView: true,
        dragView: true,
        dragNodes: true,
      },
    };

    currentNetwork = new vis.Network(dagContainer, networkData, networkOptions);
    currentNetwork.once('afterDrawing', () => {
      if (currentNetwork) currentNetwork.fit();
    });
  }

  function setRoutesTabState(enabled, content = null, item = null) {
    isRoutesTabEnabled = Boolean(enabled);
    activeJourneyItem = item;

    if (tabRoutes) {
      tabRoutes.disabled = !isRoutesTabEnabled;
      if (isRoutesTabEnabled) {
        tabRoutes.className =
          'journey-modal-tab px-3.5 py-1.5 rounded-xl text-xs font-semibold border transition-all cursor-pointer bg-white text-slate-500 border-slate-200 hover:bg-slate-100 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700 dark:hover:bg-slate-700';
      } else {
        tabRoutes.className =
          'journey-modal-tab px-3.5 py-1.5 rounded-xl text-xs font-semibold border transition-all cursor-not-allowed bg-slate-100 text-slate-400 border-slate-200 dark:bg-slate-800/60 dark:text-slate-500 dark:border-slate-700 opacity-60';
      }
    }

    if (isRoutesTabEnabled && content) {
      renderJourneyRoutesDag(content, item);
    } else {
      if (currentNetwork) {
        currentNetwork.destroy();
        currentNetwork = null;
      }
    }
  }

  function switchTab(targetTab) {
    if (targetTab === 'routes' && !isRoutesTabEnabled) return;

    if (targetTab === 'routes') {
      if (panelDetails) panelDetails.classList.add('hidden');
      if (panelRoutes) panelRoutes.classList.remove('hidden');

      if (tabRoutes) {
        tabRoutes.className =
          'journey-modal-tab px-3.5 py-1.5 rounded-xl text-xs font-semibold border transition-all cursor-pointer border-sky-500 bg-sky-50 dark:bg-sky-950/50 text-sky-700 dark:text-sky-300 font-bold';
      }
      if (tabDetails) {
        tabDetails.className =
          'journey-modal-tab px-3.5 py-1.5 rounded-xl text-xs font-semibold border transition-all cursor-pointer bg-white text-slate-500 border-slate-200 hover:bg-slate-100 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700 dark:hover:bg-slate-700';
      }

      // Re-fit diagram when tab becomes visible
      if (currentNetwork) {
        requestAnimationFrame(() => {
          if (currentNetwork) currentNetwork.fit();
        });
      }
    } else {
      if (panelRoutes) panelRoutes.classList.add('hidden');
      if (panelDetails) panelDetails.classList.remove('hidden');

      if (tabDetails) {
        tabDetails.className =
          'journey-modal-tab px-3.5 py-1.5 rounded-xl text-xs font-semibold border transition-all cursor-pointer border-sky-500 bg-sky-50 dark:bg-sky-950/50 text-sky-700 dark:text-sky-300 font-bold';
      }
      if (tabRoutes) {
        if (isRoutesTabEnabled) {
          tabRoutes.className =
            'journey-modal-tab px-3.5 py-1.5 rounded-xl text-xs font-semibold border transition-all cursor-pointer bg-white text-slate-500 border-slate-200 hover:bg-slate-100 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700 dark:hover:bg-slate-700';
        } else {
          tabRoutes.className =
            'journey-modal-tab px-3.5 py-1.5 rounded-xl text-xs font-semibold border transition-all cursor-not-allowed bg-slate-100 text-slate-400 border-slate-200 dark:bg-slate-800/60 dark:text-slate-500 dark:border-slate-700 opacity-60';
        }
      }
    }
  }

  if (tabDetails) tabDetails.addEventListener('click', () => switchTab('details'));
  if (tabRoutes) tabRoutes.addEventListener('click', () => switchTab('routes'));

  if (routesFitBtn) {
    routesFitBtn.addEventListener('click', () => {
      if (currentNetwork) {
        currentNetwork.fit({
          animation: {
            duration: 350,
            easingFunction: 'easeInOutQuad',
          },
        });
      }
    });
  }

  // Observe theme changes to adapt DAG colours dynamically
  const themeObserver = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      if (
        mutation.attributeName === 'class' &&
        isRoutesTabEnabled &&
        activeJourneyItem &&
        activeJourneyItem.calculated_routes
      ) {
        renderJourneyRoutesDag(activeJourneyItem.calculated_routes, activeJourneyItem);
      }
    });
  });
  themeObserver.observe(document.documentElement, { attributes: true });

  // --- Modal Open / Close Handlers ---
  function openAddModal() {
    editIndexInput.value = '-1';
    modalTitle.textContent = 'Add New Journey';
    modalIcon.textContent = 'route';
    journeyNameInput.value = '';
    fromAutocomplete.clearSelection();
    toAutocomplete.clearSelection();
    timeWindowsList.innerHTML = '';
    updateTimeWindowsEmptyNotice();
    modalError.classList.add('hidden');
    switchTab('details');
    setRoutesTabState(false);

    if (modal && typeof modal.showModal === 'function') {
      modal.showModal();
    }
  }

  function openEditModal(index) {
    const item = currentPageItems[index];
    if (!item) return;

    editIndexInput.value = String(index);
    modalTitle.textContent = 'Edit Journey';
    modalIcon.textContent = 'edit';
    journeyNameInput.value = item.name || '';

    fromAutocomplete.setSelection({
      type: item.from_type,
      id: item.from_id,
      name: item.from_name,
    });

    toAutocomplete.setSelection({
      type: item.to_type,
      id: item.to_id,
      name: item.to_name,
    });

    timeWindowsList.innerHTML = '';
    if (item.time_settings && Array.isArray(item.time_settings)) {
      item.time_settings.forEach(tw => {
        const card = createTimeWindowCard(tw);
        timeWindowsList.appendChild(card);
      });
    }
    updateTimeWindowsEmptyNotice();
    modalError.classList.add('hidden');

    switchTab('details');
    const hasRoutesContent =
      item.calculated_routes !== null &&
      item.calculated_routes !== undefined &&
      item.calculated_routes !== '' &&
      !(Array.isArray(item.calculated_routes) && item.calculated_routes.length === 0) &&
      !(typeof item.calculated_routes === 'object' && Object.keys(item.calculated_routes).length === 0);

    setRoutesTabState(hasRoutesContent, hasRoutesContent ? item.calculated_routes : null, item);

    if (modal && typeof modal.showModal === 'function') {
      modal.showModal();
    }
  }

  function closeModal() {
    if (currentNetwork) {
      currentNetwork.destroy();
      currentNetwork = null;
    }
    activeJourneyItem = null;
    if (modal && typeof modal.close === 'function') {
      modal.close();
    }
  }

  if (openAddBtn) openAddBtn.addEventListener('click', openAddModal);
  if (emptyAddBtn) emptyAddBtn.addEventListener('click', openAddModal);
  if (closeModalBtn) closeModalBtn.addEventListener('click', closeModal);
  if (cancelModalBtn) cancelModalBtn.addEventListener('click', closeModal);

  // --- Confirm Save Modal Handler ---
  if (confirmBtn) {
    confirmBtn.addEventListener('click', () => {
      const name = journeyNameInput.value.trim();
      const fromType = fromTypeInput.value.trim();
      const fromId = fromIdInput.value.trim();
      const fromName = fromNameInput.value.trim();
      const toType = toTypeInput.value.trim();
      const toId = toIdInput.value.trim();
      const toName = toNameInput.value.trim();

      if (!name || !fromId || !fromName || !toId || !toName) {
        modalError.textContent = 'Please enter a journey name and select valid start and end locations.';
        modalError.classList.remove('hidden');
        return;
      }

      // Collect time windows
      const cards = timeWindowsList.querySelectorAll('.time-window-card');
      const timeSettings = [];
      cards.forEach(card => {
        if (typeof card.getData === 'function') {
          timeSettings.push(card.getData());
        }
      });

      const journeyItem = {
        name,
        from_type: fromType,
        from_id: fromId,
        from_name: fromName,
        to_type: toType,
        to_id: toId,
        to_name: toName,
        time_settings: timeSettings,
        calculated_routes: null,
      };

      const editIndex = parseInt(editIndexInput.value, 10);
      if (editIndex >= 0 && editIndex < currentPageItems.length) {
        const existing = currentPageItems[editIndex];
        if (existing && existing.id !== undefined) {
          journeyItem.id = existing.id;
        }
        changesetManager.update(journeyItem.id, journeyItem);
      } else {
        journeyItem.id = -1 * (changesetManager.added.length + 1);
        changesetManager.add(journeyItem);
      }

      syncDirtyState();
      syncEmptyState(1);
      gridInstance.forceRender();
      closeModal();
    });
  }

  // --- Grid Button Actions (Edit / Delete) ---
  document.addEventListener('click', (e) => {
    const editBtn = e.target.closest('.edit-journey-btn');
    if (editBtn) {
      const idx = parseInt(editBtn.getAttribute('data-index'), 10);
      if (!isNaN(idx)) openEditModal(idx);
      return;
    }

    const delBtn = e.target.closest('.delete-journey-btn');
    if (delBtn) {
      const idx = parseInt(delBtn.getAttribute('data-index'), 10);
      if (!isNaN(idx) && idx >= 0 && idx < currentPageItems.length) {
        const item = currentPageItems[idx];
        if (item && item.id !== undefined) {
          changesetManager.delete(item.id);
          syncDirtyState();
          gridInstance.forceRender();
        }
      }
    }
  });

  // Register discard handler
  if (window.ConfigDirtyManager) {
    window.ConfigDirtyManager.registerDiscardHandler(() => {
      changesetManager.reset();
      syncDirtyState();
      gridInstance.forceRender();
    });
  }

  if (window.ConfigSave) {
    window.ConfigSave.register({
      endpoint: dataUrl,
      getChangeset: () => {
        return changesetManager.getChangeset();
      },
      onSaveSuccess: () => {
        changesetManager.reset();
        syncDirtyState();
        gridInstance.forceRender();
      },
    });
  }
});
