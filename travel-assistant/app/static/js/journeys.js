/**
 * Journeys Configuration Controller
 * 
 * Manages client-side staged state for Travel Journeys with Grid.js and
 * an interactive modal dialogue featuring multi-location live search autocompletion
 * (Rail Stations, Bus Stops, Home Assistant, and Custom Locations), dynamic
 * multi-time-window scheduling, and delegates DAG route visualization to JourneyDagViewer.
 */

document.addEventListener('DOMContentLoaded', () => {
  const configEl =
    document.getElementById('journeys-config') ||
    document.getElementById('journeys-form');
  if (!configEl) return;

  const dataUrl =
    configEl.getAttribute('data-data-url') || '/config/journeys/data';

  const changesetManager =
    window.TransitUI && window.TransitUI.createStagedChangesetManager
      ? window.TransitUI.createStagedChangesetManager('id')
      : new window.TransitUI.StagedChangesetManager('id');

  let currentPageItems = [];

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
  const journeyDiscoverBtn = document.getElementById('journey-discover-btn');
  const routeCardsContainer = document.getElementById('journey-routes-cards-container');
  const queriesDetails = document.getElementById('journey-queries-details');
  const queriesCount = document.getElementById('journey-queries-count');
  const queriesList = document.getElementById('journey-queries-list');

  const escapeHtml = (window.TransitUI && window.TransitUI.escapeHtml) || ((str) => (str ? String(str) : ''));
  const getLocationBadge = (window.TransitUI && window.TransitUI.getTransportBadge) || ((type) => type);
  const formatDaysSummary = (window.TransitUI && window.TransitUI.formatDaysSummary) || ((days) => (days || []).join(', '));

  function formatScheduleSummary(timeSettings) {
    if (!timeSettings || !timeSettings.length) {
      return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300">
        <span class="material-symbols-outlined text-xs leading-none text-slate-400">all_inclusive</span> Anytime (All days)
      </span>`;
    }

    const items = timeSettings.map((tw) => {
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
            <button type="button" class="discover-journey-btn w-7 h-7 rounded-lg bg-emerald-50 text-emerald-600 hover:bg-emerald-100 cursor-pointer" data-index="${index}" title="Discover corridors via Google"><span class="material-symbols-outlined text-[17px]">auto_awesome</span></button>
            <button type="button" class="edit-journey-btn w-7 h-7 rounded-lg bg-sky-50 text-sky-600 hover:bg-sky-100 cursor-pointer" data-index="${index}" title="Edit journey"><span class="material-symbols-outlined text-[17px]">edit</span></button>
            <button type="button" class="delete-journey-btn w-7 h-7 rounded-lg bg-rose-50 text-rose-600 hover:bg-rose-100 cursor-pointer" data-index="${index}" title="Delete journey"><span class="material-symbols-outlined text-[17px]">delete</span></button>
          </div>
        `),
      ];
    });
  }

  const columnsConfig = [
    { name: 'Journey', width: '25%', sort: true },
    { name: 'Start Location', width: '22%', sort: true },
    { name: 'End Location', width: '22%', sort: true },
    { name: 'Schedule', width: '19%', sort: false },
    { name: 'Actions', width: '120px', sort: false },
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
    if (emptyState) emptyState.classList.toggle('hidden', effectiveTotal > 0);
    if (gridWrapper) gridWrapper.classList.toggle('hidden', effectiveTotal === 0);
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
      total: (data) =>
        Math.max(
          0,
          (Number(data.total) || 0) +
            changesetManager.added.length -
            changesetManager.deleted.size
        ),
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
    search: { enabled: true, placeholder: 'Search journeys...' },
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

  if (gridWrapper) gridInstance.render(gridWrapper);

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
    card.className =
      'time-window-card p-4 rounded-xl border border-slate-200 dark:border-slate-700/80 bg-slate-50/50 dark:bg-slate-800/40 space-y-3 relative';

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
        <button type="button" class="remove-time-window-btn text-slate-400 hover:text-rose-600 dark:hover:text-rose-400 p-1 rounded-lg transition-colors cursor-pointer" title="Remove time window">
          <span class="material-symbols-outlined text-base">delete</span>
        </button>
      </div>
      <div>
        <div class="flex flex-wrap items-center justify-between gap-1 mb-1.5">
          <label class="block text-[11px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-400">Active Days</label>
          <div class="flex items-center gap-1 text-[11px]">
            <button type="button" class="preset-btn px-1.5 py-0.5 rounded text-slate-500 hover:text-sky-600 cursor-pointer" data-preset="weekdays">Weekdays</button>
            <span class="text-slate-300 dark:text-slate-600">|</span>
            <button type="button" class="preset-btn px-1.5 py-0.5 rounded text-slate-500 hover:text-sky-600 cursor-pointer" data-preset="weekends">Weekends</button>
            <span class="text-slate-300 dark:text-slate-600">|</span>
            <button type="button" class="preset-btn px-1.5 py-0.5 rounded text-slate-500 hover:text-sky-600 cursor-pointer" data-preset="all">All</button>
            <span class="text-slate-300 dark:text-slate-600">|</span>
            <button type="button" class="preset-btn px-1.5 py-0.5 rounded text-slate-500 hover:text-rose-600 cursor-pointer" data-preset="clear">Clear</button>
          </div>
        </div>
        <div class="flex flex-wrap gap-1.5 day-buttons-container">
          ${ALL_DAYS.map(
            (day) => `
            <button type="button" class="day-pill-btn px-2.5 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
              selectedDays.has(day.key)
                ? 'border border-sky-500 bg-sky-50 dark:bg-sky-950/50 text-sky-700 dark:text-sky-300 font-bold'
                : 'bg-white text-slate-500 border border-slate-200 hover:bg-slate-100 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700 dark:hover:bg-slate-700'
            }" data-day="${day.key}">
              ${day.label}
            </button>`
          ).join('')}
        </div>
      </div>
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 items-end">
        <div>
          <label class="block text-[11px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-400 mb-1">Time Mode</label>
          <div class="inline-flex rounded-xl border border-slate-300 dark:border-slate-700 p-0.5 bg-white dark:bg-slate-800 w-full">
            <button type="button" class="mode-btn flex-1 py-1.5 text-xs font-semibold rounded-lg transition-colors cursor-pointer ${
              mode === 'depart' ? 'bg-sky-600 text-white' : 'text-slate-600 dark:text-slate-300 hover:text-slate-900'
            }" data-mode="depart">Depart During</button>
            <button type="button" class="mode-btn flex-1 py-1.5 text-xs font-semibold rounded-lg transition-colors cursor-pointer ${
              mode === 'arrive' ? 'bg-sky-600 text-white' : 'text-slate-600 dark:text-slate-300 hover:text-slate-900'
            }" data-mode="arrive">Arrive During</button>
          </div>
        </div>
        <div>
          <label class="block text-[11px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-400 mb-1">From Time</label>
          <input type="text" list="time-intervals-datalist" placeholder="08:00" class="start-time-input w-full px-3 py-1.5 rounded-xl border border-slate-300 bg-white text-xs font-mono text-slate-900 focus:border-sky-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100" value="${startTime}">
        </div>
        <div>
          <label class="block text-[11px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-400 mb-1">To Time</label>
          <input type="text" list="time-intervals-datalist" placeholder="09:30" class="end-time-input w-full px-3 py-1.5 rounded-xl border border-slate-300 bg-white text-xs font-mono text-slate-900 focus:border-sky-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100" value="${endTime}">
        </div>
      </div>
    `;

    card.querySelector('.remove-time-window-btn').addEventListener('click', () => {
      card.remove();
      updateTimeWindowsEmptyNotice();
    });

    card.querySelectorAll('.day-pill-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const dayKey = btn.getAttribute('data-day');
        if (selectedDays.has(dayKey)) {
          selectedDays.delete(dayKey);
          btn.className =
            'day-pill-btn px-2.5 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer bg-white text-slate-500 border border-slate-200 hover:bg-slate-100 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700 dark:hover:bg-slate-700';
        } else {
          selectedDays.add(dayKey);
          btn.className =
            'day-pill-btn px-2.5 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer border border-sky-500 bg-sky-50 dark:bg-sky-950/50 text-sky-700 dark:text-sky-300';
        }
      });
    });

    card.querySelectorAll('.preset-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const preset = btn.getAttribute('data-preset');
        selectedDays.clear();
        if (preset === 'weekdays') {
          ['mon', 'tue', 'wed', 'thu', 'fri'].forEach((d) => selectedDays.add(d));
        } else if (preset === 'weekends') {
          ['sat', 'sun'].forEach((d) => selectedDays.add(d));
        } else if (preset === 'all') {
          ALL_DAYS.forEach((d) => selectedDays.add(d.key));
        }

        card.querySelectorAll('.day-pill-btn').forEach((pBtn) => {
          const dKey = pBtn.getAttribute('data-day');
          pBtn.className = selectedDays.has(dKey)
            ? 'day-pill-btn px-2.5 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer border border-sky-500 bg-sky-50 dark:bg-sky-950/50 text-sky-700 dark:text-sky-300'
            : 'day-pill-btn px-2.5 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer bg-white text-slate-500 border border-slate-200 hover:bg-slate-100 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700 dark:hover:bg-slate-700';
        });
      });
    });

    let activeMode = mode;
    card.querySelectorAll('.mode-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        activeMode = btn.getAttribute('data-mode');
        card.querySelectorAll('.mode-btn').forEach((b) => {
          b.className = b.getAttribute('data-mode') === activeMode
            ? 'mode-btn flex-1 py-1.5 text-xs font-semibold rounded-lg transition-colors cursor-pointer bg-sky-600 text-white'
            : 'mode-btn flex-1 py-1.5 text-xs font-semibold rounded-lg transition-colors cursor-pointer text-slate-600 dark:text-slate-300 hover:text-slate-900';
        });
      });
    });

    card.getData = () => ({
      days: Array.from(selectedDays),
      mode: activeMode,
      start_time: card.querySelector('.start-time-input').value.trim(),
      end_time: card.querySelector('.end-time-input').value.trim(),
    });

    return card;
  }

  function updateTimeWindowsEmptyNotice() {
    if (!timeWindowsList || !timeWindowsEmptyNotice) return;
    const count = timeWindowsList.querySelectorAll('.time-window-card').length;
    timeWindowsEmptyNotice.classList.toggle('hidden', count > 0);
  }

  if (addTimeWindowBtn) {
    addTimeWindowBtn.addEventListener('click', () => {
      const card = createTimeWindowCard();
      timeWindowsList.appendChild(card);
      updateTimeWindowsEmptyNotice();
    });
  }

  let isRoutesTabEnabled = false;

  if (window.JourneyDagViewer) {
    window.JourneyDagViewer.init({
      container: dagContainer,
      summaryText: routesSummaryText,
      emptyState: routesEmptyState,
      fitBtn: routesFitBtn,
    });
  }

  function setRoutesTabState(enabled, content = null, item = null) {
    isRoutesTabEnabled = Boolean(enabled);
    if (tabRoutes) {
      tabRoutes.disabled = !isRoutesTabEnabled;
      tabRoutes.className = isRoutesTabEnabled
        ? 'journey-modal-tab px-3.5 py-1.5 rounded-xl text-xs font-semibold border transition-all cursor-pointer bg-white text-slate-500 border-slate-200 hover:bg-slate-100 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700 dark:hover:bg-slate-700'
        : 'journey-modal-tab px-3.5 py-1.5 rounded-xl text-xs font-semibold border transition-all cursor-not-allowed bg-slate-100 text-slate-400 border-slate-200 dark:bg-slate-800/60 dark:text-slate-500 dark:border-slate-700 opacity-60';
    }

    if (isRoutesTabEnabled && content && window.JourneyDagViewer) {
      window.JourneyDagViewer.render(content, item);
    } else if (window.JourneyDagViewer) {
      window.JourneyDagViewer.destroy();
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

      if (window.JourneyDagViewer) {
        requestAnimationFrame(() => {
          window.JourneyDagViewer.fit();
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
        tabRoutes.className = isRoutesTabEnabled
          ? 'journey-modal-tab px-3.5 py-1.5 rounded-xl text-xs font-semibold border transition-all cursor-pointer bg-white text-slate-500 border-slate-200 hover:bg-slate-100 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700 dark:hover:bg-slate-700'
          : 'journey-modal-tab px-3.5 py-1.5 rounded-xl text-xs font-semibold border transition-all cursor-not-allowed bg-slate-100 text-slate-400 border-slate-200 dark:bg-slate-800/60 dark:text-slate-500 dark:border-slate-700 opacity-60';
      }
    }
  }

  function renderJourneyRouteCards(routes) {
    if (!routeCardsContainer) return;
    if (!routes || !routes.length) {
      routeCardsContainer.innerHTML = '';
      return;
    }

    routeCardsContainer.innerHTML = routes
      .map((r, idx) => {
        const preferredBadge = r.is_preferred
          ? `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-800 dark:bg-amber-900/60 dark:text-amber-200">
               <span class="material-symbols-outlined text-xs">star</span> Primary Route
             </span>`
          : `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400">
               Alternative ${idx}
             </span>`;

        const modeIcon =
          r.primary_mode === 'train' || r.primary_mode === 'rail'
            ? 'train'
            : r.primary_mode === 'bus'
            ? 'directions_bus'
            : 'alt_route';

        const legsHtml = Array.isArray(r.legs)
          ? r.legs
              .map((l) => {
                const legMode = escapeHtml(l.mode || 'transit');
                const lineName = l.line
                  ? `<span class="font-bold ml-1">${escapeHtml(l.line)}</span>`
                  : '';
                return `<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 text-[11px] text-slate-700 dark:text-slate-300">
                  ${legMode}${lineName}
                </span>`;
              })
              .join('<span class="text-slate-400 text-xs">→</span>')
          : '';

        return `
          <div class="p-3 rounded-xl border border-slate-200 dark:border-slate-700/80 bg-white dark:bg-slate-900/70 shadow-xs flex flex-col gap-2">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <span class="material-symbols-outlined text-slate-500 text-base">${modeIcon}</span>
                <span class="font-semibold text-xs text-slate-800 dark:text-slate-200">${escapeHtml(r.name || 'Route Option')}</span>
                ${preferredBadge}
              </div>
              <div class="text-xs text-slate-500 dark:text-slate-400 font-mono">
                ~${r.total_duration_est_minutes || 0} mins · ${r.transfer_count || 0} transfers
              </div>
            </div>
            ${legsHtml ? `<div class="flex flex-wrap items-center gap-1.5 pt-1 border-t border-slate-100 dark:border-slate-800">${legsHtml}</div>` : ''}
            ${r.summary_text ? `<p class="text-[11px] text-slate-500 dark:text-slate-400">${escapeHtml(r.summary_text)}</p>` : ''}
          </div>
        `;
      })
      .join('');
  }

  function renderQueryAuditHistory(queries) {
    if (queriesCount) {
      queriesCount.textContent = String(queries ? queries.length : 0);
    }
    if (!queriesList) return;

    if (!queries || !queries.length) {
      queriesList.innerHTML =
        '<p class="text-xs text-slate-400 dark:text-slate-500 py-1">No routing API queries recorded for this journey yet.</p>';
      return;
    }

    queriesList.innerHTML = queries
      .map((q) => {
        const typeBadge =
          q.query_type === 'live_disruption_reroute'
            ? '<span class="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300">Live Reroute</span>'
            : q.query_type === 'manual_refresh'
            ? '<span class="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300">Manual Refresh</span>'
            : '<span class="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">Initial Discovery</span>';

        const dateStr = q.created_at
          ? new Date(q.created_at).toLocaleString('en-GB')
          : 'Unknown date';
        const parsedCount = Array.isArray(q.parsed_summary)
          ? q.parsed_summary.length
          : 0;

        return `
          <div class="p-2.5 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 text-xs">
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-1.5">
                ${typeBadge}
                <span class="text-slate-500 dark:text-slate-400 font-mono text-[11px]">${escapeHtml(dateStr)}</span>
              </div>
              <span class="text-slate-500 dark:text-slate-400 text-[11px]">${parsedCount} route option(s) discovered</span>
            </div>
            ${q.trigger_reason ? `<div class="mt-1 text-[11px] text-slate-600 dark:text-slate-300">Reason: ${escapeHtml(q.trigger_reason)}</div>` : ''}
          </div>
        `;
      })
      .join('');
  }

  async function loadJourneyRouteCardsAndQueries(journeyId) {
    if (!journeyId || journeyId <= 0) {
      if (routeCardsContainer) routeCardsContainer.innerHTML = '';
      if (queriesCount) queriesCount.textContent = '0';
      if (queriesList) {
        queriesList.innerHTML =
          '<p class="text-xs text-slate-400 dark:text-slate-500 py-1">Save this journey to view routes and query history.</p>';
      }
      return;
    }

    try {
      const [routesRes, queriesRes] = await Promise.all([
        fetch(`/config/journeys/${journeyId}/routes`),
        fetch(`/config/journeys/${journeyId}/queries`),
      ]);

      if (routesRes.ok) {
        const routesData = await routesRes.json();
        renderJourneyRouteCards(routesData.routes || []);
      }
      if (queriesRes.ok) {
        const queriesData = await queriesRes.json();
        renderQueryAuditHistory(queriesData.queries || []);
      }
    } catch (err) {
      console.error('Error fetching journey routes and audit logs:', err);
    }
  }

  if (journeyDiscoverBtn) {
    journeyDiscoverBtn.addEventListener('click', async () => {
      const editIndex = parseInt(editIndexInput.value, 10);
      let journeyId = null;
      let journeyItem = null;
      if (editIndex >= 0 && editIndex < currentPageItems.length) {
        journeyItem = currentPageItems[editIndex];
        journeyId = journeyItem?.id;
      }

      if (!journeyId || journeyId <= 0) {
        alert('Please save the journey first before discovering corridors.');
        return;
      }

      const origHtml = journeyDiscoverBtn.innerHTML;
      journeyDiscoverBtn.disabled = true;
      journeyDiscoverBtn.innerHTML = `
        <span class="material-symbols-outlined text-sm animate-spin">refresh</span>
        <span>Discovering...</span>
      `;

      try {
        const res = await fetch(`/config/journeys/${journeyId}/discover`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.error || 'Failed to discover routes');
        }

        const data = await res.json();
        if (journeyItem) {
          journeyItem.calculated_routes = data.routes || [];
        }

        setRoutesTabState(true, data.routes || [], journeyItem);
        await loadJourneyRouteCardsAndQueries(journeyId);
        gridInstance.forceRender();
      } catch (err) {
        console.error('Error discovering journey corridors:', err);
        alert('Corridor discovery failed: ' + (err.message || 'Unknown error'));
      } finally {
        journeyDiscoverBtn.disabled = false;
        journeyDiscoverBtn.innerHTML = origHtml;
      }
    });
  }

  if (tabDetails) tabDetails.addEventListener('click', () => switchTab('details'));
  if (tabRoutes) tabRoutes.addEventListener('click', () => switchTab('routes'));

  function openAddModal() {
    editIndexInput.value = '-1';
    modalTitle.textContent = 'Add New Journey';
    modalIcon.textContent = 'route';
    journeyNameInput.value = '';
    if (fromAutocomplete) fromAutocomplete.clearSelection();
    if (toAutocomplete) toAutocomplete.clearSelection();
    timeWindowsList.innerHTML = '';
    updateTimeWindowsEmptyNotice();
    modalError.classList.add('hidden');
    switchTab('details');
    setRoutesTabState(false);
    loadJourneyRouteCardsAndQueries(null);

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

    if (fromAutocomplete) {
      fromAutocomplete.setSelection({
        type: item.from_type,
        id: item.from_id,
        name: item.from_name,
      });
    }

    if (toAutocomplete) {
      toAutocomplete.setSelection({
        type: item.to_type,
        id: item.to_id,
        name: item.to_name,
      });
    }

    timeWindowsList.innerHTML = '';
    if (item.time_settings && Array.isArray(item.time_settings)) {
      item.time_settings.forEach((tw) => {
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
      !(
        Array.isArray(item.calculated_routes) &&
        item.calculated_routes.length === 0
      ) &&
      !(
        typeof item.calculated_routes === 'object' &&
        Object.keys(item.calculated_routes).length === 0
      );

    setRoutesTabState(
      hasRoutesContent,
      hasRoutesContent ? item.calculated_routes : null,
      item
    );
    loadJourneyRouteCardsAndQueries(item.id);

    if (modal && typeof modal.showModal === 'function') {
      modal.showModal();
    }
  }

  function closeModal() {
    if (window.JourneyDagViewer) {
      window.JourneyDagViewer.destroy();
    }
    if (modal && typeof modal.close === 'function') {
      modal.close();
    }
  }

  if (openAddBtn) openAddBtn.addEventListener('click', openAddModal);
  if (emptyAddBtn) emptyAddBtn.addEventListener('click', openAddModal);
  if (closeModalBtn) closeModalBtn.addEventListener('click', closeModal);
  if (cancelModalBtn) cancelModalBtn.addEventListener('click', closeModal);

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
        modalError.textContent =
          'Please enter a journey name and select valid start and end locations.';
        modalError.classList.remove('hidden');
        return;
      }

      const cards = timeWindowsList.querySelectorAll('.time-window-card');
      const timeSettings = [];
      cards.forEach((card) => {
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

  document.addEventListener('click', (e) => {
    const discBtn = e.target.closest('.discover-journey-btn');
    if (discBtn) {
      const idx = parseInt(discBtn.getAttribute('data-index'), 10);
      if (!isNaN(idx) && idx >= 0 && idx < currentPageItems.length) {
        const item = currentPageItems[idx];
        if (!item || !item.id || item.id <= 0) {
          alert('Please save changes first before discovering corridors.');
          return;
        }

        const origHtml = discBtn.innerHTML;
        discBtn.disabled = true;
        discBtn.innerHTML =
          '<span class="material-symbols-outlined text-[17px] animate-spin">refresh</span>';

        fetch(`/config/journeys/${item.id}/discover`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        })
          .then((res) => {
            if (!res.ok) throw new Error('Corridor discovery failed');
            return res.json();
          })
          .then((data) => {
            item.calculated_routes = data.routes || [];
            gridInstance.forceRender();
          })
          .catch((err) => {
            console.error('Error during corridor discovery:', err);
            alert('Failed to discover corridors: ' + err.message);
          })
          .finally(() => {
            discBtn.disabled = false;
            discBtn.innerHTML = origHtml;
          });
      }
      return;
    }

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
      getChangeset: () => changesetManager.getChangeset(),
      onSaveSuccess: () => {
        changesetManager.reset();
        syncDirtyState();
        gridInstance.forceRender();
      },
    });
  }
});
