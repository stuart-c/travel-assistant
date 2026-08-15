/**
 * Timetables View Controller.
 * Manages Grid.js data table rendering, in-memory staged mutations,
 * transit dataset caching checks, autocomplete pickers for train journeys
 * and bus stop-route pairs, and modal interactions.
 */
document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('timetables-form');
  if (!form) return;

  const dataEl = document.getElementById('initial-timetables-data');
  let initialRaw = [];
  try {
    initialRaw = dataEl ? JSON.parse(dataEl.textContent || '[]') : [];
  } catch (e) {
    console.error('Failed to parse initial timetables data:', e);
  }

  // In-memory staged state
  let stagedTimetables = JSON.parse(JSON.stringify(initialRaw || []));
  const initialSnapshot = JSON.stringify(stagedTimetables);

  const searchUrl =
    form.dataset.searchUrl ||
    window.location.pathname.replace(/\/$/, '') + '/search';

  const hiddenInput = document.getElementById('timetables_json');
  const emptyState = document.getElementById('grid-empty-state');
  const gridContainer = document.getElementById('timetables-grid-wrapper');

  // Modal elements
  const addModal = document.getElementById('add-timetable-modal');
  const openAddBtn = document.getElementById('open-add-modal-btn');
  const emptyAddBtn = document.getElementById('empty-add-btn');
  const closeAddBtn = document.getElementById('close-add-modal-btn');
  const cancelAddBtn = document.getElementById('cancel-add-modal-btn');
  const confirmAddBtn = document.getElementById('confirm-add-timetable-btn');

  // Containers
  const trainContainer = document.getElementById('train-selection-container');
  const busContainer = document.getElementById('bus-selection-container');
  const cacheWarning = document.getElementById('cache-warning-banner');
  const cacheWarningTitle = document.getElementById('cache-warning-title');
  const cacheWarningMsg = document.getElementById('cache-warning-message');

  // Train picker elements
  const station1Input = document.getElementById('station1-search-input');
  const station1Spinner = document.getElementById('station1-spinner');
  const station1Chip = document.getElementById('station1-selected-chip');
  const station1ChipName = document.getElementById('station1-chip-name');
  const station1ChipCrs = document.getElementById('station1-chip-crs');
  const clearStation1Btn = document.getElementById('clear-station1-btn');
  const station1Suggestions = document.getElementById('station1-suggestions');

  const station2Input = document.getElementById('station2-search-input');
  const station2Spinner = document.getElementById('station2-spinner');
  const station2Chip = document.getElementById('station2-selected-chip');
  const station2ChipName = document.getElementById('station2-chip-name');
  const station2ChipCrs = document.getElementById('station2-chip-crs');
  const clearStation2Btn = document.getElementById('clear-station2-btn');
  const station2Suggestions = document.getElementById('station2-suggestions');

  // Bus picker elements
  const busStopInput = document.getElementById('bus-stop-search-input');
  const busStopSpinner = document.getElementById('bus-stop-spinner');
  const busStopChip = document.getElementById('bus-stop-selected-chip');
  const busStopChipName = document.getElementById('bus-stop-chip-name');
  const busStopChipAtco = document.getElementById('bus-stop-chip-atco');
  const clearBusStopBtn = document.getElementById('clear-bus-stop-btn');
  const busStopSuggestions = document.getElementById('bus-stop-suggestions');

  const busRouteInput = document.getElementById('bus-route-search-input');
  const busRouteSpinner = document.getElementById('bus-route-spinner');
  const busRouteChip = document.getElementById('bus-route-selected-chip');
  const busRouteChipName = document.getElementById('bus-route-chip-name');
  const busRouteChipNumber = document.getElementById('bus-route-chip-number');
  const clearBusRouteBtn = document.getElementById('clear-bus-route-btn');
  const busRouteSuggestions = document.getElementById('bus-route-suggestions');

  // Summary & status fields
  const modalNameInput = document.getElementById('modal_name');
  const modalIdInput = document.getElementById('modal_identifier');
  const modalStatusSelect = document.getElementById('modal_status');
  const modalError = document.getElementById('modal-validation-error');

  // Selection state
  let selectedStation1 = null;
  let selectedStation2 = null;
  let selectedBusStop = null;
  let selectedBusRoute = null;

  function getSelectedTransportType() {
    const checked = document.querySelector(
      'input[name="modal_transport_type"]:checked'
    );
    return checked ? checked.value : 'bus';
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // Format data rows for Grid.js
  function formatGridData(items) {
    return items.map((item, index) => {
      const typeIcon =
        item.transport_type === 'train' ? 'train' : 'directions_bus';
      const typeBadgeColor =
        item.transport_type === 'train'
          ? 'bg-indigo-100 text-indigo-800 dark:bg-indigo-950/80 dark:text-indigo-300 dark:ring-1 dark:ring-indigo-500/30'
          : 'bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-300 dark:ring-1 dark:ring-amber-500/30';
      const typeLabel = item.transport_type === 'train' ? 'Train' : 'Bus';

      const statusBadgeColor =
        item.status === 'active'
          ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300'
          : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400';
      const statusLabel = item.status === 'active' ? 'Active' : 'Inactive';

      return [
        gridjs.html(`
          <span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold ${typeBadgeColor}">
            <span class="material-symbols-outlined text-xs leading-none">${typeIcon}</span>
            ${typeLabel}
          </span>
        `),
        gridjs.html(
          `<span class="font-medium text-slate-900 dark:text-slate-100">${escapeHtml(
            item.name
          )}</span>`
        ),
        gridjs.html(
          `<code class="px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 text-xs font-mono">${escapeHtml(
            item.identifier
          )}</code>`
        ),
        gridjs.html(
          `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${statusBadgeColor}">${statusLabel}</span>`
        ),
        gridjs.html(`
          <button 
            type="button" 
            class="remove-row-btn inline-flex items-center gap-1 px-2.5 py-1 text-xs font-semibold rounded-lg text-rose-600 hover:text-white hover:bg-rose-600 dark:text-rose-400 dark:hover:bg-rose-700/80 transition-colors cursor-pointer"
            data-index="${index}"
            title="Remove from list"
          >
            <span class="material-symbols-outlined text-xs leading-none">delete</span>
            Remove
          </button>
        `),
      ];
    });
  }

  // Initialise Grid.js instance
  const grid = new gridjs.Grid({
    columns: [
      { name: 'Type', width: '110px' },
      { name: 'Name', width: 'auto' },
      { name: 'Identifier / Feed', width: '200px' },
      { name: 'Status', width: '110px' },
      { name: 'Actions', width: '110px', sort: false },
    ],
    data: formatGridData(stagedTimetables),
    search: {
      placeholder: 'Search timetables...',
    },
    sort: true,
    pagination: {
      limit: 8,
      summary: true,
    },
    language: {
      search: {
        placeholder: 'Search timetables...',
      },
      pagination: {
        previous: 'Previous',
        next: 'Next',
        showing: 'Showing',
        results: () => 'timetables',
      },
    },
  }).render(gridContainer);

  // Sync in-memory changes with hidden form input and dirty manager
  function syncState() {
    const currentJson = JSON.stringify(stagedTimetables);
    if (hiddenInput) {
      hiddenInput.value = currentJson;
    }

    if (stagedTimetables.length === 0) {
      gridContainer.classList.add('hidden');
      emptyState.classList.remove('hidden');
    } else {
      gridContainer.classList.remove('hidden');
      emptyState.classList.add('hidden');
    }

    grid
      .updateConfig({
        data: formatGridData(stagedTimetables),
      })
      .forceRender();

    if (window.ConfigDirtyManager) {
      if (currentJson !== initialSnapshot) {
        window.ConfigDirtyManager.markDirty();
      } else {
        window.ConfigDirtyManager.clearDirty();
      }
    }
  }

  syncState();

  if (window.ConfigDirtyManager) {
    window.ConfigDirtyManager.registerDiscardHandler(() => {
      stagedTimetables = JSON.parse(initialSnapshot);
      syncState();
    });
  }

  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.remove-row-btn');
    if (btn) {
      const idx = parseInt(btn.getAttribute('data-index'), 10);
      if (!isNaN(idx) && idx >= 0 && idx < stagedTimetables.length) {
        stagedTimetables.splice(idx, 1);
        syncState();
      }
    }
  });

  // Check dataset caching availability and update UI mode
  async function updateModalMode() {
    const type = getSelectedTransportType();
    if (modalError) modalError.classList.add('hidden');

    if (type === 'train') {
      if (busContainer) busContainer.classList.add('hidden');
      if (trainContainer) trainContainer.classList.remove('hidden');

      try {
        const sep = searchUrl.includes('?') ? '&' : '?';
        const res = await fetch(`${searchUrl}${sep}type=station&q=&limit=1`);
        const data = await res.json();

        if (data && data.is_cached === false) {
          if (cacheWarning) {
            cacheWarningTitle.textContent = 'Rail Stations Not Cached';
            cacheWarningMsg.textContent =
              'The rail stations dataset has not been cached yet. You must synchronise stations in Database settings before configuring train journeys.';
            cacheWarning.classList.remove('hidden');
          }
          if (station1Input) station1Input.disabled = true;
          if (station2Input) station2Input.disabled = true;
        } else {
          if (cacheWarning) cacheWarning.classList.add('hidden');
          if (station1Input) station1Input.disabled = false;
          if (station2Input) station2Input.disabled = false;
        }
      } catch (err) {
        console.error('Failed to check train stations cache:', err);
      }
    } else {
      if (trainContainer) trainContainer.classList.add('hidden');
      if (busContainer) busContainer.classList.remove('hidden');

      try {
        const sep = searchUrl.includes('?') ? '&' : '?';
        const res = await fetch(`${searchUrl}${sep}type=bus_stop&q=&limit=1`);
        const data = await res.json();

        if (data && data.is_cached === false) {
          if (cacheWarning) {
            cacheWarningTitle.textContent = 'Bus Datasets Not Cached';
            cacheWarningMsg.textContent =
              'Bus stops and routes have not been cached yet. You must synchronise bus datasets in Database settings before configuring bus timetables.';
            cacheWarning.classList.remove('hidden');
          }
          if (busStopInput) busStopInput.disabled = true;
          if (busRouteInput) busRouteInput.disabled = true;
        } else {
          if (cacheWarning) cacheWarning.classList.add('hidden');
          if (busStopInput) busStopInput.disabled = false;
          if (busRouteInput) busRouteInput.disabled = false;
        }
      } catch (err) {
        console.error('Failed to check bus cache status:', err);
      }
    }
  }

  // Update auto-generated Display Name & Identifier
  function updateGeneratedFields() {
    const type = getSelectedTransportType();
    if (type === 'train') {
      if (selectedStation1 && selectedStation2) {
        const name = `${selectedStation1.name} ↔ ${selectedStation2.name}`;
        const identifier = `${selectedStation1.crs_code} ↔ ${selectedStation2.crs_code}`;
        if (modalNameInput) modalNameInput.value = name;
        if (modalIdInput) modalIdInput.value = identifier;
      }
    } else {
      if (selectedBusStop && selectedBusRoute) {
        const routeNum = selectedBusRoute.route_number || 'Bus';
        const stopName = selectedBusStop.name || 'Stop';
        const stopAtco = selectedBusStop.atco_code || '';
        const name = `Route ${routeNum} at ${stopName}`;
        const identifier = `${routeNum}@${stopAtco}`;
        if (modalNameInput) modalNameInput.value = name;
        if (modalIdInput) modalIdInput.value = identifier;
      } else if (selectedBusStop) {
        const stopName = selectedBusStop.name || 'Stop';
        const stopAtco = selectedBusStop.atco_code || '';
        if (modalNameInput && !modalNameInput.value) {
          modalNameInput.value = `Bus at ${stopName}`;
        }
        if (modalIdInput && !modalIdInput.value) {
          modalIdInput.value = `@${stopAtco}`;
        }
      }
    }
  }

  // Autocomplete Setup Helper
  function setupAutocomplete({
    inputEl,
    spinnerEl,
    suggestionsEl,
    getType,
    renderItem,
    onSelect,
  }) {
    if (!inputEl || !suggestionsEl) return;

    let debounceTimer = null;

    async function triggerLookup(q) {
      const type = typeof getType === 'function' ? getType() : getType;
      if (spinnerEl) spinnerEl.classList.remove('hidden');

      try {
        const sep = searchUrl.includes('?') ? '&' : '?';
        const res = await fetch(
          `${searchUrl}${sep}type=${encodeURIComponent(
            type
          )}&q=${encodeURIComponent(q)}&limit=20`
        );
        const data = await res.json();
        renderResults(data.results || []);
      } catch (err) {
        console.error(`Lookup failed for ${type}:`, err);
      } finally {
        if (spinnerEl) spinnerEl.classList.add('hidden');
      }
    }

    function renderResults(results) {
      if (!results || results.length === 0) {
        suggestionsEl.innerHTML =
          '<div class="p-3 text-xs text-slate-500 dark:text-slate-400 text-center">No matching records found in cache.</div>';
        suggestionsEl.classList.remove('hidden');
        return;
      }

      suggestionsEl.innerHTML = '';
      results.forEach((item) => {
        const div = document.createElement('div');
        div.className =
          'p-2.5 hover:bg-sky-50 dark:hover:bg-slate-700/60 cursor-pointer rounded-lg transition-colors flex items-center justify-between gap-3';
        div.innerHTML = renderItem(item);
        div.addEventListener('click', () => {
          onSelect(item);
          suggestionsEl.classList.add('hidden');
          inputEl.value = '';
        });
        suggestionsEl.appendChild(div);
      });
      suggestionsEl.classList.remove('hidden');
    }

    inputEl.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        triggerLookup(inputEl.value.trim());
      }, 250);
    });

    inputEl.addEventListener('focus', () => {
      if (suggestionsEl.children.length > 0) {
        suggestionsEl.classList.remove('hidden');
      } else {
        triggerLookup(inputEl.value.trim());
      }
    });
  }

  // Setup Train Station 1 Autocomplete
  setupAutocomplete({
    inputEl: station1Input,
    spinnerEl: station1Spinner,
    suggestionsEl: station1Suggestions,
    getType: () => 'station',
    renderItem: (item) => `
      <div class="min-w-0">
        <div class="text-xs font-semibold text-slate-900 dark:text-slate-100 truncate">${escapeHtml(
          item.name
        )}</div>
        <div class="text-xs text-slate-500 dark:text-slate-400 truncate">${escapeHtml(
          item.operator || 'National Rail'
        )}</div>
      </div>
      <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-sky-100 dark:bg-sky-900 text-sky-800 dark:text-sky-200 shrink-0">${escapeHtml(
        item.crs_code
      )}</span>
    `,
    onSelect: (item) => {
      selectedStation1 = item;
      if (station1Chip && station1ChipName && station1ChipCrs) {
        station1ChipName.textContent = item.name;
        station1ChipCrs.textContent = item.crs_code;
        station1Chip.classList.remove('hidden');
      }
      updateGeneratedFields();
      if (station2Input && !selectedStation2) {
        station2Input.focus();
      }
    },
  });

  if (clearStation1Btn) {
    clearStation1Btn.addEventListener('click', () => {
      selectedStation1 = null;
      if (station1Chip) station1Chip.classList.add('hidden');
      if (station1Input) {
        station1Input.value = '';
        station1Input.focus();
      }
      updateGeneratedFields();
    });
  }

  // Setup Train Station 2 Autocomplete
  setupAutocomplete({
    inputEl: station2Input,
    spinnerEl: station2Spinner,
    suggestionsEl: station2Suggestions,
    getType: () => 'station',
    renderItem: (item) => `
      <div class="min-w-0">
        <div class="text-xs font-semibold text-slate-900 dark:text-slate-100 truncate">${escapeHtml(
          item.name
        )}</div>
        <div class="text-xs text-slate-500 dark:text-slate-400 truncate">${escapeHtml(
          item.operator || 'National Rail'
        )}</div>
      </div>
      <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-sky-100 dark:bg-sky-900 text-sky-800 dark:text-sky-200 shrink-0">${escapeHtml(
        item.crs_code
      )}</span>
    `,
    onSelect: (item) => {
      selectedStation2 = item;
      if (station2Chip && station2ChipName && station2ChipCrs) {
        station2ChipName.textContent = item.name;
        station2ChipCrs.textContent = item.crs_code;
        station2Chip.classList.remove('hidden');
      }
      updateGeneratedFields();
    },
  });

  if (clearStation2Btn) {
    clearStation2Btn.addEventListener('click', () => {
      selectedStation2 = null;
      if (station2Chip) station2Chip.classList.add('hidden');
      if (station2Input) {
        station2Input.value = '';
        station2Input.focus();
      }
      updateGeneratedFields();
    });
  }

  // Setup Bus Stop Autocomplete
  setupAutocomplete({
    inputEl: busStopInput,
    spinnerEl: busStopSpinner,
    suggestionsEl: busStopSuggestions,
    getType: () => 'bus_stop',
    renderItem: (item) => {
      const localityPart = [item.indicator, item.locality]
        .filter(Boolean)
        .join(' • ');
      return `
        <div class="min-w-0">
          <div class="text-xs font-semibold text-slate-900 dark:text-slate-100 truncate">${escapeHtml(
            item.name
          )}</div>
          <div class="text-xs text-slate-500 dark:text-slate-400 truncate">${escapeHtml(
            localityPart || item.atco_code
          )}</div>
        </div>
        <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-amber-100 dark:bg-amber-900 text-amber-800 dark:text-amber-200 shrink-0">${escapeHtml(
          item.atco_code
        )}</span>
      `;
    },
    onSelect: (item) => {
      selectedBusStop = item;
      if (busStopChip && busStopChipName && busStopChipAtco) {
        busStopChipName.textContent = item.name;
        busStopChipAtco.textContent = item.atco_code;
        busStopChip.classList.remove('hidden');
      }
      updateGeneratedFields();
      if (busRouteInput && !selectedBusRoute) {
        busRouteInput.focus();
      }
    },
  });

  if (clearBusStopBtn) {
    clearBusStopBtn.addEventListener('click', () => {
      selectedBusStop = null;
      if (busStopChip) busStopChip.classList.add('hidden');
      if (busStopInput) {
        busStopInput.value = '';
        busStopInput.focus();
      }
      updateGeneratedFields();
    });
  }

  // Setup Bus Route Autocomplete
  setupAutocomplete({
    inputEl: busRouteInput,
    spinnerEl: busRouteSpinner,
    suggestionsEl: busRouteSuggestions,
    getType: () => 'bus_route',
    renderItem: (item) => {
      const desc =
        item.destination && item.origin
          ? `${item.origin} → ${item.destination}`
          : item.description || item.operator_name || 'Bus Service';
      return `
        <div class="min-w-0">
          <div class="text-xs font-semibold text-slate-900 dark:text-slate-100 truncate">Route ${escapeHtml(
            item.route_number
          )}</div>
          <div class="text-xs text-slate-500 dark:text-slate-400 truncate">${escapeHtml(
            desc
          )}</div>
        </div>
        <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-amber-100 dark:bg-amber-900 text-amber-800 dark:text-amber-200 shrink-0">${escapeHtml(
          item.operator_code || item.route_number
        )}</span>
      `;
    },
    onSelect: (item) => {
      selectedBusRoute = item;
      if (busRouteChip && busRouteChipName && busRouteChipNumber) {
        const desc =
          item.destination || item.operator_name || `Route ${item.route_number}`;
        busRouteChipName.textContent = `Route ${item.route_number} (${desc})`;
        busRouteChipNumber.textContent = item.route_number;
        busRouteChip.classList.remove('hidden');
      }
      updateGeneratedFields();
    },
  });

  if (clearBusRouteBtn) {
    clearBusRouteBtn.addEventListener('click', () => {
      selectedBusRoute = null;
      if (busRouteChip) busRouteChip.classList.add('hidden');
      if (busRouteInput) {
        busRouteInput.value = '';
        busRouteInput.focus();
      }
      updateGeneratedFields();
    });
  }

  // Global click to close open suggestion popovers
  document.addEventListener('click', (e) => {
    const allSuggestions = [
      station1Suggestions,
      station2Suggestions,
      busStopSuggestions,
      busRouteSuggestions,
    ];
    allSuggestions.forEach((sugg) => {
      if (sugg && !sugg.contains(e.target) && !e.target.closest('input')) {
        sugg.classList.add('hidden');
      }
    });
  });

  // Open Add Modal
  function showAddModal() {
    if (modalError) modalError.classList.add('hidden');
    selectedStation1 = null;
    selectedStation2 = null;
    selectedBusStop = null;
    selectedBusRoute = null;

    if (station1Chip) station1Chip.classList.add('hidden');
    if (station2Chip) station2Chip.classList.add('hidden');
    if (busStopChip) busStopChip.classList.add('hidden');
    if (busRouteChip) busRouteChip.classList.add('hidden');

    if (station1Input) station1Input.value = '';
    if (station2Input) station2Input.value = '';
    if (busStopInput) busStopInput.value = '';
    if (busRouteInput) busRouteInput.value = '';

    if (modalNameInput) modalNameInput.value = '';
    if (modalIdInput) modalIdInput.value = '';
    if (modalStatusSelect) modalStatusSelect.value = 'active';

    [
      station1Suggestions,
      station2Suggestions,
      busStopSuggestions,
      busRouteSuggestions,
    ].forEach((sugg) => {
      if (sugg) {
        sugg.innerHTML = '';
        sugg.classList.add('hidden');
      }
    });

    updateModalMode();

    if (addModal && typeof addModal.showModal === 'function') {
      addModal.showModal();
    }
  }

  if (openAddBtn) openAddBtn.addEventListener('click', showAddModal);
  if (emptyAddBtn) emptyAddBtn.addEventListener('click', showAddModal);

  function closeAddModal() {
    if (addModal && typeof addModal.close === 'function') {
      addModal.close();
    }
  }

  if (closeAddBtn) closeAddBtn.addEventListener('click', closeAddModal);
  if (cancelAddBtn) cancelAddBtn.addEventListener('click', closeAddModal);

  // Update styling when transport type radio changes
  document
    .querySelectorAll('input[name="modal_transport_type"]')
    .forEach((radio) => {
      radio.addEventListener('change', () => {
        document.querySelectorAll('.transport-type-label').forEach((lbl) => {
          lbl.classList.remove(
            'border-sky-500',
            'bg-sky-50/50',
            'dark:bg-sky-950/40'
          );
          lbl.classList.add('border-slate-200', 'dark:border-slate-800');
        });
        const activeLabel = radio.closest('.transport-type-label');
        if (activeLabel) {
          activeLabel.classList.remove(
            'border-slate-200',
            'dark:border-slate-800'
          );
          activeLabel.classList.add(
            'border-sky-500',
            'bg-sky-50/50',
            'dark:bg-sky-950/40'
          );
        }
        updateModalMode();
      });
    });

  // Confirm adding new timetable to staged list
  if (confirmAddBtn) {
    confirmAddBtn.addEventListener('click', () => {
      const name = modalNameInput ? modalNameInput.value.trim() : '';
      const identifier = modalIdInput ? modalIdInput.value.trim() : '';
      const transport_type = getSelectedTransportType();
      const status = modalStatusSelect ? modalStatusSelect.value : 'active';

      if (!name || !identifier) {
        if (modalError) modalError.classList.remove('hidden');
        return;
      }

      stagedTimetables.push({
        transport_type,
        name,
        identifier,
        status,
      });

      syncState();
      closeAddModal();
    });
  }
});
