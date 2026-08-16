/**
 * Journeys Configuration Controller
 * 
 * Manages client-side staged state for Travel Journeys with Grid.js and
 * an interactive modal dialogue featuring multi-location live search autocompletion
 * (Rail Stations, Bus Stops, Home Assistant, and Custom Locations) and dynamic
 * multi-time-window scheduling.
 */

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('journeys-form');
  if (!form) return;

  const searchBaseUrl = form.getAttribute('data-search-url') || '/config/search/places';

  // Parse initial data payload
  const initialScript = document.getElementById('initial-journeys-data');
  let initialJourneysData = [];
  try {
    if (initialScript && initialScript.textContent) {
      initialJourneysData = JSON.parse(initialScript.textContent);
    }
  } catch (e) {
    console.error('Failed to parse initial journeys data:', e);
  }

  // In-memory staged state
  let stagedJourneys = JSON.parse(JSON.stringify(initialJourneysData || []));
  const initialSnapshot = JSON.stringify(stagedJourneys);

  // DOM Elements
  const hiddenInput = document.getElementById('journeys_json');
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

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function getLocationBadge(type) {
    const t = String(type || '').toLowerCase();
    if (t === 'rail') {
      return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-indigo-100 text-indigo-800 dark:bg-indigo-950/80 dark:text-indigo-300 dark:ring-1 dark:ring-indigo-500/30"><span class="material-symbols-outlined text-xs leading-none">train</span> Rail</span>`;
    } else if (t === 'bus') {
      return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-300 dark:ring-1 dark:ring-amber-500/30"><span class="material-symbols-outlined text-xs leading-none">directions_bus</span> Bus</span>`;
    } else if (t === 'tram') {
      return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-300 dark:ring-1 dark:ring-amber-500/30"><span class="material-symbols-outlined text-xs leading-none">tram</span> Tram</span>`;
    } else if (t === 'metro') {
      return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300 dark:ring-1 dark:ring-emerald-500/30"><span class="material-symbols-outlined text-xs leading-none">subway</span> Metro</span>`;
    } else if (t === 'ferry') {
      return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-cyan-100 text-cyan-800 dark:bg-cyan-950/80 dark:text-cyan-300 dark:ring-1 dark:ring-cyan-500/30"><span class="material-symbols-outlined text-xs leading-none">directions_boat</span> Ferry</span>`;
    } else if (t === 'air') {
      return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-purple-100 text-purple-800 dark:bg-purple-950/80 dark:text-purple-300 dark:ring-1 dark:ring-purple-500/30"><span class="material-symbols-outlined text-xs leading-none">flight</span> Air</span>`;
    } else if (t === 'ha') {
      return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300 dark:ring-1 dark:ring-emerald-500/30"><span class="material-symbols-outlined text-xs leading-none">home</span> Home Assistant</span>`;
    }
    return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-sky-100 text-sky-800 dark:bg-sky-950/80 dark:text-sky-300 dark:ring-1 dark:ring-sky-500/30"><span class="material-symbols-outlined text-xs leading-none">pin_drop</span> Custom</span>`;
  }

  function getLocationIcon(type) {
    const t = String(type || '').toLowerCase();
    if (t === 'rail') return 'train';
    if (t === 'bus') return 'directions_bus';
    if (t === 'tram') return 'tram';
    if (t === 'metro') return 'subway';
    if (t === 'ferry') return 'directions_boat';
    if (t === 'air') return 'flight';
    if (t === 'ha') return 'home';
    return 'pin_drop';
  }

  function formatDaysSummary(days) {
    if (!days || !days.length) return 'All days';
    const dayMap = {
      mon: 'Mon',
      tue: 'Tue',
      wed: 'Wed',
      thu: 'Thu',
      fri: 'Fri',
      sat: 'Sat',
      sun: 'Sun',
      bank_holiday: 'Bank Holiday',
    };
    const mapped = days.map(d => dayMap[d] || d);
    const hasWeekdays = ['mon', 'tue', 'wed', 'thu', 'fri'].every(d => days.includes(d));
    const isOnlyWeekdays = hasWeekdays && days.length === 5;
    const isOnlyWeekends = days.length === 2 && days.includes('sat') && days.includes('sun');

    if (isOnlyWeekdays) return 'Weekdays (Mon–Fri)';
    if (isOnlyWeekends) return 'Weekends (Sat–Sun)';
    if (days.length === 8) return 'All days & Bank Holidays';
    return mapped.join(', ');
  }

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
        gridjs.html(`
          <div class="flex items-center gap-1.5">
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
          </div>
        `),
      ];
    });
  }

  // --- Grid Instance ---
  let gridInstance = null;

  function renderGrid() {
    if (!gridWrapper) return;

    if (stagedJourneys.length === 0) {
      gridWrapper.classList.add('hidden');
      if (emptyState) emptyState.classList.remove('hidden');
    } else {
      gridWrapper.classList.remove('hidden');
      if (emptyState) emptyState.classList.add('hidden');
    }

    const gridData = formatGridData(stagedJourneys);

    if (!gridInstance) {
      gridInstance = new gridjs.Grid({
        columns: [
          { name: 'Journey', width: '26%' },
          { name: 'Start Location', width: '23%' },
          { name: 'End Location', width: '23%' },
          { name: 'Schedule', width: '20%', sort: false },
          { name: 'Actions', width: '80px', sort: false },
        ],
        data: gridData,
        search: {
          enabled: true,
          placeholder: 'Search journeys...',
        },
        sort: true,
        pagination: {
          enabled: true,
          limit: 10,
          summary: true,
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
      }).render(gridWrapper);
    } else {
      gridInstance.updateConfig({ data: gridData }).forceRender();
    }

    if (gridWrapper && gridWrapper.querySelector('.gridjs-container')) {
      if (stagedJourneys.length <= 10) {
        gridWrapper.querySelector('.gridjs-container').setAttribute('data-single-page', 'true');
      } else {
        gridWrapper.querySelector('.gridjs-container').removeAttribute('data-single-page');
      }
    }

    updateHiddenInput();
  }

  function updateHiddenInput() {
    if (hiddenInput) {
      hiddenInput.value = JSON.stringify(stagedJourneys);
    }
    // Update dirty state
    const currentSnapshot = JSON.stringify(stagedJourneys);
    const isDirty = currentSnapshot !== initialSnapshot;
    window.dispatchEvent(new CustomEvent('configDirtyStateChanged', { detail: { isDirty } }));
  }

  // --- Location Autocomplete Component ---
  function setupAutocomplete(inputEl, suggestionsEl, typeEl, idEl, nameEl, previewEl, previewIconEl, previewNameEl, previewIdEl, clearBtnEl) {
    let debounceTimer = null;

    function setSelection(item) {
      typeEl.value = item.type;
      idEl.value = item.id;
      nameEl.value = item.name;

      previewIconEl.textContent = getLocationIcon(item.type);
      previewNameEl.textContent = item.name;
      previewIdEl.textContent = item.id;

      previewEl.classList.remove('hidden');
      inputEl.parentElement.classList.add('hidden');
      suggestionsEl.classList.add('hidden');
      inputEl.value = '';
    }

    function clearSelection() {
      typeEl.value = '';
      idEl.value = '';
      nameEl.value = '';

      previewEl.classList.add('hidden');
      inputEl.parentElement.classList.remove('hidden');
      inputEl.value = '';
      inputEl.focus();
    }

    if (clearBtnEl) {
      clearBtnEl.addEventListener('click', clearSelection);
    }

    inputEl.addEventListener('input', () => {
      const q = inputEl.value.trim();
      clearTimeout(debounceTimer);

      if (!q) {
        suggestionsEl.innerHTML = '';
        suggestionsEl.classList.add('hidden');
        return;
      }

      debounceTimer = setTimeout(async () => {
        try {
          const resp = await fetch(`${searchBaseUrl}?q=${encodeURIComponent(q)}&limit=12`);
          if (!resp.ok) throw new Error('Search failed');
          const data = await resp.json();
          renderSuggestions(data.results || []);
        } catch (err) {
          console.error('Location search error:', err);
        }
      }, 200);
    });

    function renderSuggestions(items) {
      if (!items || items.length === 0) {
        suggestionsEl.innerHTML = `
          <div class="px-3.5 py-3 text-xs text-slate-500 dark:text-slate-400 text-center">
            No matching stations, bus stops, or locations found
          </div>
        `;
        suggestionsEl.classList.remove('hidden');
        return;
      }

      suggestionsEl.innerHTML = items.map((item, idx) => {
        const icon = getLocationIcon(item.type);
        const badge = getLocationBadge(item.type);

        return `
          <div 
            class="suggestion-item px-3.5 py-2.5 hover:bg-sky-50 dark:hover:bg-slate-700/60 cursor-pointer flex items-center justify-between gap-3 transition-colors"
            data-index="${idx}"
          >
            <div class="flex items-center gap-2.5 min-w-0">
              <span class="material-symbols-outlined text-slate-400 dark:text-slate-500 text-lg shrink-0">${icon}</span>
              <div class="truncate">
                <div class="text-xs font-semibold text-slate-900 dark:text-slate-100">${escapeHtml(item.name)}</div>
                <div class="text-[11px] text-slate-500 dark:text-slate-400 truncate">${escapeHtml(item.description)}</div>
              </div>
            </div>
            <div class="shrink-0">
              ${badge}
            </div>
          </div>
        `;
      }).join('');

      suggestionsEl.classList.remove('hidden');

      suggestionsEl.querySelectorAll('.suggestion-item').forEach(el => {
        el.addEventListener('click', () => {
          const idx = parseInt(el.getAttribute('data-index'), 10);
          if (items[idx]) {
            setSelection(items[idx]);
          }
        });
      });
    }

    // Close suggestions on outside click
    document.addEventListener('click', (e) => {
      if (!inputEl.contains(e.target) && !suggestionsEl.contains(e.target)) {
        suggestionsEl.classList.add('hidden');
      }
    });

    return { setSelection, clearSelection };
  }

  const fromAutocomplete = setupAutocomplete(
    fromSearchInput,
    fromSuggestions,
    fromTypeInput,
    fromIdInput,
    fromNameInput,
    fromPreview,
    fromPreviewIcon,
    fromPreviewName,
    fromPreviewId,
    clearFromBtn
  );

  const toAutocomplete = setupAutocomplete(
    toSearchInput,
    toSuggestions,
    toTypeInput,
    toIdInput,
    toNameInput,
    toPreview,
    toPreviewIcon,
    toPreviewName,
    toPreviewId,
    clearToBtn
  );

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

    if (modal && typeof modal.showModal === 'function') {
      modal.showModal();
    }
  }

  function openEditModal(index) {
    const item = stagedJourneys[index];
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

    if (modal && typeof modal.showModal === 'function') {
      modal.showModal();
    }
  }

  function closeModal() {
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
      };

      const editIndex = parseInt(editIndexInput.value, 10);
      if (editIndex >= 0 && editIndex < stagedJourneys.length) {
        stagedJourneys[editIndex] = journeyItem;
      } else {
        stagedJourneys.push(journeyItem);
      }

      renderGrid();
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
      if (!isNaN(idx) && idx >= 0 && idx < stagedJourneys.length) {
        stagedJourneys.splice(idx, 1);
        renderGrid();
      }
    }
  });

  // Initial Render
  renderGrid();
});
