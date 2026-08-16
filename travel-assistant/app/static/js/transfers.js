/**
 * Transfers Configuration Controller
 * 
 * Manages client-side staged state for both Inter-Location Transfers and
 * Platform/Stand Transfers using Grid.js and modal dialogs with live search autocomplete.
 */

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('transfers-form');
  if (!form) return;

  const searchBaseUrl = form.getAttribute('data-search-url') || '/config/search/places';

  // Parse initial data payloads
  const locScript = document.getElementById('initial-location-transfers-data');
  const platScript = document.getElementById('initial-platform-transfers-data');

  let initialLocationData = [];
  let initialPlatformData = [];

  try {
    if (locScript && locScript.textContent) {
      initialLocationData = JSON.parse(locScript.textContent);
    }
  } catch (e) {
    console.error('Failed to parse initial location transfers data:', e);
  }

  try {
    if (platScript && platScript.textContent) {
      initialPlatformData = JSON.parse(platScript.textContent);
    }
  } catch (e) {
    console.error('Failed to parse initial platform transfers data:', e);
  }

  // In-memory staged state
  let stagedLocationTransfers = JSON.parse(JSON.stringify(initialLocationData || []));
  let stagedPlatformTransfers = JSON.parse(JSON.stringify(initialPlatformData || []));

  const initialLocationSnapshot = JSON.stringify(stagedLocationTransfers);
  const initialPlatformSnapshot = JSON.stringify(stagedPlatformTransfers);

  // Hidden form inputs
  const locHiddenInput = document.getElementById('location_transfers_json');
  const platHiddenInput = document.getElementById('platform_transfers_json');

  // Containers
  const locGridWrapper = document.getElementById('location-transfers-grid-wrapper');
  const locEmptyState = document.getElementById('location-grid-empty-state');
  const platGridWrapper = document.getElementById('platform-transfers-grid-wrapper');
  const platEmptyState = document.getElementById('platform-grid-empty-state');

  // Location Modal Elements
  const locModal = document.getElementById('location-transfer-modal');
  const openAddLocBtn = document.getElementById('open-add-location-modal-btn');
  const emptyAddLocBtn = document.getElementById('empty-add-location-btn');
  const closeLocModalBtn = document.getElementById('close-location-modal-btn');
  const cancelLocModalBtn = document.getElementById('cancel-location-modal-btn');
  const confirmLocBtn = document.getElementById('confirm-location-transfer-btn');
  const locModalTitle = document.getElementById('location-modal-title');
  const locModalIcon = document.getElementById('location-modal-icon');
  const editLocIndexInput = document.getElementById('edit-location-index');
  const fromLocSearch = document.getElementById('from-loc-search');
  const fromLocSuggestions = document.getElementById('from-loc-suggestions');
  const fromLocName = document.getElementById('from_loc_name');
  const fromLocId = document.getElementById('from_loc_id');
  const toLocSearch = document.getElementById('to-loc-search');
  const toLocSuggestions = document.getElementById('to-loc-suggestions');
  const toLocName = document.getElementById('to_loc_name');
  const toLocId = document.getElementById('to_loc_id');
  const locTransferTime = document.getElementById('location_transfer_time');
  const locBidirectional = document.getElementById('location_bidirectional');
  const locStepFree = document.getElementById('location_step_free');
  const locNotes = document.getElementById('location_notes');
  const locError = document.getElementById('location-modal-error');

  // Platform Modal Elements
  const platModal = document.getElementById('platform-transfer-modal');
  const openAddPlatBtn = document.getElementById('open-add-platform-modal-btn');
  const emptyAddPlatBtn = document.getElementById('empty-add-platform-btn');
  const closePlatModalBtn = document.getElementById('close-platform-modal-btn');
  const cancelPlatModalBtn = document.getElementById('cancel-platform-modal-btn');
  const confirmPlatBtn = document.getElementById('confirm-platform-transfer-btn');
  const platModalTitle = document.getElementById('platform-modal-title');
  const platModalIcon = document.getElementById('platform-modal-icon');
  const editPlatIndexInput = document.getElementById('edit-platform-index');
  const platStationSearch = document.getElementById('plat-station-search');
  const platStationSuggestions = document.getElementById('plat-station-suggestions');
  const platStationName = document.getElementById('plat_station_name');
  const platStationId = document.getElementById('plat_station_id');
  const platFromPlatform = document.getElementById('plat_from_platform');
  const platToPlatform = document.getElementById('plat_to_platform');
  const platTransferTime = document.getElementById('platform_transfer_time');
  const platBidirectional = document.getElementById('platform_bidirectional');
  const platStepFree = document.getElementById('platform_step_free');
  const platNotes = document.getElementById('platform_notes');
  const platError = document.getElementById('platform-modal-error');

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
      return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300 dark:ring-1 dark:ring-emerald-500/30"><span class="material-symbols-outlined text-xs leading-none">home</span> HA</span>`;
    }
    return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-sky-100 text-sky-800 dark:bg-sky-950/80 dark:text-sky-300 dark:ring-1 dark:ring-sky-500/30"><span class="material-symbols-outlined text-xs leading-none">pin_drop</span> Custom</span>`;
  }

  // --- Location Transfers Grid Data Formatter ---
  function formatLocationGridData(items) {
    return items.map((item, index) => {
      const fromBadge = getLocationBadge(item.from_type);
      const toBadge = getLocationBadge(item.to_type);

      const dirHtml = item.bidirectional
        ? `<span class="inline-flex items-center gap-1 text-xs font-medium text-slate-700 dark:text-slate-300" title="Transfer valid in both directions"><span class="material-symbols-outlined text-sm leading-none text-sky-500">sync_alt</span> ⇄ Both ways</span>`
        : `<span class="inline-flex items-center gap-1 text-xs font-medium text-slate-500 dark:text-slate-400" title="One-way transfer"><span class="material-symbols-outlined text-sm leading-none">arrow_forward</span> → One way</span>`;

      const stepFreeHtml = item.step_free
        ? `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300"><span class="material-symbols-outlined text-xs leading-none">accessible</span> Yes</span>`
        : `<span class="text-xs text-slate-400 dark:text-slate-500">No</span>`;

      return [
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
        gridjs.html(`
          <span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-sky-50 text-sky-700 dark:bg-sky-950/60 dark:text-sky-300 font-bold text-xs">
            <span class="material-symbols-outlined text-sm leading-none">timer</span>
            ${escapeHtml(item.transfer_time_minutes)} min${item.transfer_time_minutes > 1 ? 's' : ''}
          </span>
        `),
        gridjs.html(dirHtml),
        gridjs.html(stepFreeHtml),
        gridjs.html(`<span class="text-xs text-slate-600 dark:text-slate-300 truncate max-w-xs block" title="${escapeHtml(item.notes || '')}">${escapeHtml(item.notes || '—')}</span>`),
        gridjs.html(`
          <div class="flex items-center gap-1.5">
            <button 
              type="button" 
              class="edit-loc-row-btn inline-flex items-center justify-center w-7 h-7 rounded-lg bg-sky-50 text-sky-600 hover:bg-sky-100 hover:text-sky-700 dark:bg-sky-950/50 dark:text-sky-400 dark:hover:bg-sky-900/60 transition-colors cursor-pointer"
              data-index="${index}"
              title="Edit transfer"
              aria-label="Edit transfer"
            >
              <span class="material-symbols-outlined text-[17px] leading-none">edit</span>
            </button>
            <button 
              type="button" 
              class="remove-loc-row-btn inline-flex items-center justify-center w-7 h-7 rounded-lg bg-rose-50 text-rose-600 hover:bg-rose-100 hover:text-rose-700 dark:bg-rose-950/50 dark:text-rose-400 dark:hover:bg-rose-900/60 transition-colors cursor-pointer"
              data-index="${index}"
              title="Delete transfer"
              aria-label="Delete transfer"
            >
              <span class="material-symbols-outlined text-[17px] leading-none">delete</span>
            </button>
          </div>
        `)
      ];
    });
  }

  // --- Platform Transfers Grid Data Formatter ---
  function formatPlatformGridData(items) {
    return items.map((item, index) => {
      const locBadge = getLocationBadge(item.location_type);

      const dirHtml = item.bidirectional
        ? `<span class="inline-flex items-center gap-1 text-xs font-medium text-slate-700 dark:text-slate-300" title="Transfer valid in both directions"><span class="material-symbols-outlined text-sm leading-none text-indigo-500">sync_alt</span> ⇄ Both ways</span>`
        : `<span class="inline-flex items-center gap-1 text-xs font-medium text-slate-500 dark:text-slate-400" title="One-way transfer"><span class="material-symbols-outlined text-sm leading-none">arrow_forward</span> → One way</span>`;

      const stepFreeHtml = item.step_free
        ? `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300"><span class="material-symbols-outlined text-xs leading-none">accessible</span> Yes</span>`
        : `<span class="text-xs text-slate-400 dark:text-slate-500">No</span>`;

      return [
        gridjs.html(`
          <div class="flex flex-col gap-1">
            <div class="flex items-center gap-1.5">
              ${locBadge}
              <span class="font-semibold text-slate-900 dark:text-slate-100">${escapeHtml(item.location_name)}</span>
            </div>
            <span class="text-xs font-mono text-slate-500 dark:text-slate-400">${escapeHtml(item.location_id)}</span>
          </div>
        `),
        gridjs.html(`
          <span class="inline-flex items-center px-2 py-0.5 rounded-md font-mono text-xs font-semibold bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300">
            ${escapeHtml(item.from_platform || 'Any')}
          </span>
        `),
        gridjs.html(`
          <span class="inline-flex items-center px-2 py-0.5 rounded-md font-mono text-xs font-semibold bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300">
            ${escapeHtml(item.to_platform || 'Any')}
          </span>
        `),
        gridjs.html(`
          <span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-indigo-50 text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300 font-bold text-xs">
            <span class="material-symbols-outlined text-sm leading-none">timer</span>
            ${escapeHtml(item.transfer_time_minutes)} min${item.transfer_time_minutes > 1 ? 's' : ''}
          </span>
        `),
        gridjs.html(dirHtml),
        gridjs.html(stepFreeHtml),
        gridjs.html(`<span class="text-xs text-slate-600 dark:text-slate-300 truncate max-w-xs block" title="${escapeHtml(item.notes || '')}">${escapeHtml(item.notes || '—')}</span>`),
        gridjs.html(`
          <div class="flex items-center gap-1.5">
            <button 
              type="button" 
              class="edit-plat-row-btn inline-flex items-center justify-center w-7 h-7 rounded-lg bg-indigo-50 text-indigo-600 hover:bg-indigo-100 hover:text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-400 dark:hover:bg-indigo-900/60 transition-colors cursor-pointer"
              data-index="${index}"
              title="Edit platform transfer"
              aria-label="Edit platform transfer"
            >
              <span class="material-symbols-outlined text-[17px] leading-none">edit</span>
            </button>
            <button 
              type="button" 
              class="remove-plat-row-btn inline-flex items-center justify-center w-7 h-7 rounded-lg bg-rose-50 text-rose-600 hover:bg-rose-100 hover:text-rose-700 dark:bg-rose-950/50 dark:text-rose-400 dark:hover:bg-rose-900/60 transition-colors cursor-pointer"
              data-index="${index}"
              title="Delete platform transfer"
              aria-label="Delete platform transfer"
            >
              <span class="material-symbols-outlined text-[17px] leading-none">delete</span>
            </button>
          </div>
        `)
      ];
    });
  }

  // --- Initialise Location Grid.js ---
  const locationGrid = new gridjs.Grid({
    columns: [
      { name: 'Origin (From)', width: '220px' },
      { name: 'Destination (To)', width: '220px' },
      { name: 'Duration', width: '110px' },
      { name: 'Direction', width: '130px' },
      { name: 'Step-Free', width: '100px' },
      { name: 'Notes', width: 'auto' },
      { name: 'Actions', width: '80px', sort: false }
    ],
    data: formatLocationGridData(stagedLocationTransfers),
    search: { placeholder: 'Search inter-location transfers...' },
    sort: true,
    pagination: { limit: 10, summary: true },
    language: {
      search: { placeholder: 'Search inter-location transfers...' },
      pagination: {
        previous: 'Previous',
        next: 'Next',
        showing: 'Showing',
        of: 'of',
        to: 'to',
        results: 'transfers'
      },
      noRecordsFound: 'No matching transfers found'
    }
  }).render(locGridWrapper);

  // --- Initialise Platform Grid.js ---
  const platformGrid = new gridjs.Grid({
    columns: [
      { name: 'Station / Interchange', width: '200px' },
      { name: 'From Platform', width: '130px' },
      { name: 'To Platform', width: '130px' },
      { name: 'Duration', width: '110px' },
      { name: 'Direction', width: '130px' },
      { name: 'Step-Free', width: '100px' },
      { name: 'Notes', width: 'auto' },
      { name: 'Actions', width: '80px', sort: false }
    ],
    data: formatPlatformGridData(stagedPlatformTransfers),
    search: { placeholder: 'Search platform transfers...' },
    sort: true,
    pagination: { limit: 10, summary: true },
    language: {
      search: { placeholder: 'Search platform transfers...' },
      pagination: {
        previous: 'Previous',
        next: 'Next',
        showing: 'Showing',
        results: () => 'transfers'
      },
      noRecordsFound: 'No matching platform transfers found'
    }
  }).render(platGridWrapper);

  // --- Sync State with Dirty Manager & Hidden Inputs ---
  function syncState() {
    const currentLocJson = JSON.stringify(stagedLocationTransfers);
    const currentPlatJson = JSON.stringify(stagedPlatformTransfers);

    if (locHiddenInput) locHiddenInput.value = currentLocJson;
    if (platHiddenInput) platHiddenInput.value = currentPlatJson;

    // Toggle Empty States vs Grids
    if (stagedLocationTransfers.length === 0) {
      locGridWrapper.classList.add('hidden');
      locEmptyState.classList.remove('hidden');
    } else {
      locGridWrapper.classList.remove('hidden');
      locEmptyState.classList.add('hidden');
    }

    if (stagedPlatformTransfers.length === 0) {
      platGridWrapper.classList.add('hidden');
      platEmptyState.classList.remove('hidden');
    } else {
      platGridWrapper.classList.remove('hidden');
      platEmptyState.classList.add('hidden');
    }

    // Force Re-render Grids & check pagination display
    if (locGridWrapper.querySelector('.gridjs-container')) {
      if (stagedLocationTransfers.length <= 10) {
        locGridWrapper.querySelector('.gridjs-container').setAttribute('data-single-page', 'true');
      } else {
        locGridWrapper.querySelector('.gridjs-container').removeAttribute('data-single-page');
      }
    }

    if (platGridWrapper.querySelector('.gridjs-container')) {
      if (stagedPlatformTransfers.length <= 10) {
        platGridWrapper.querySelector('.gridjs-container').setAttribute('data-single-page', 'true');
      } else {
        platGridWrapper.querySelector('.gridjs-container').removeAttribute('data-single-page');
      }
    }

    locationGrid.updateConfig({
      data: formatLocationGridData(stagedLocationTransfers)
    }).forceRender();

    platformGrid.updateConfig({
      data: formatPlatformGridData(stagedPlatformTransfers)
    }).forceRender();

    // Check Dirty Status
    if (window.ConfigDirtyManager) {
      const isDirty = (currentLocJson !== initialLocationSnapshot) || (currentPlatJson !== initialPlatformSnapshot);
      if (isDirty) {
        window.ConfigDirtyManager.markDirty();
      } else {
        window.ConfigDirtyManager.clearDirty();
      }
    }
  }

  // Initial Sync
  syncState();

  // Collapsible section toggles
  document.querySelectorAll('.section-toggle').forEach(header => {
    header.addEventListener('click', (e) => {
      // Don't toggle if clicking an interactive input/button inside
      if (e.target.closest('button, input, select, a')) return;
      const targetId = header.getAttribute('data-target');
      const section = targetId ? document.getElementById(targetId) : header.closest('.collapsible-section');
      if (section) {
        section.classList.toggle('collapsed');
      }
    });
  });

  // Register Discard Handler with ConfigDirtyManager
  if (window.ConfigDirtyManager) {
    window.ConfigDirtyManager.registerDiscardHandler(() => {
      stagedLocationTransfers = JSON.parse(initialLocationSnapshot);
      stagedPlatformTransfers = JSON.parse(initialPlatformSnapshot);
      syncState();
    });
  }

  // --- Location Autocomplete Helpers ---
  function setupAutocomplete(searchInput, suggestionsContainer, typeRadioName, nameInput, idInput) {
    let debounceTimer = null;

    async function triggerLookup(query) {
      const checkedRadio = document.querySelector(`input[name="${typeRadioName}"]:checked`);
      const mode = checkedRadio ? checkedRadio.value : '';

      try {
        const res = await fetch(`${searchBaseUrl}?type=${encodeURIComponent(mode)}&q=${encodeURIComponent(query)}`);
        const data = await res.json();
        renderSuggestions(data.results || []);
      } catch (err) {
        console.error('Location search lookup failed:', err);
      }
    }

    function renderSuggestions(results) {
      if (!results || results.length === 0) {
        suggestionsContainer.innerHTML = '<div class="p-2.5 text-xs text-slate-500 dark:text-slate-400 text-center">No locations found. Enter details manually below.</div>';
        suggestionsContainer.classList.remove('hidden');
        return;
      }

      suggestionsContainer.innerHTML = '';
      results.forEach(item => {
        const div = document.createElement('div');
        div.className = 'p-2.5 hover:bg-sky-50 dark:hover:bg-slate-700/60 cursor-pointer rounded-lg transition-colors flex items-center justify-between gap-3';
        const itemIcon = item.icon || 'place';
        div.innerHTML = `
          <div class="flex items-center gap-2.5 min-w-0">
            <span class="material-symbols-outlined text-base text-slate-400 shrink-0">${escapeHtml(itemIcon)}</span>
            <div class="min-w-0">
              <div class="text-xs font-semibold text-slate-900 dark:text-slate-100 truncate">${escapeHtml(item.name)}</div>
              <div class="text-xs text-slate-500 dark:text-slate-400 truncate">${escapeHtml(item.description || item.id)}</div>
            </div>
          </div>
          <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 shrink-0">${escapeHtml(item.id)}</span>
        `;
        div.addEventListener('click', () => {
          nameInput.value = item.name;
          idInput.value = item.id;
          if (typeRadioName && item.type) {
            const matchingRadio = document.querySelector(`input[name="${typeRadioName}"][value="${item.type}"]`);
            if (matchingRadio) matchingRadio.checked = true;
          }
          suggestionsContainer.classList.add('hidden');
        });
        suggestionsContainer.appendChild(div);
      });
      suggestionsContainer.classList.remove('hidden');
    }

    if (searchInput) {
      searchInput.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
          triggerLookup(searchInput.value.trim());
        }, 200);
      });

      searchInput.addEventListener('focus', () => {
        if (suggestionsContainer && suggestionsContainer.children.length > 0) {
          suggestionsContainer.classList.remove('hidden');
        } else {
          triggerLookup(searchInput.value.trim());
        }
      });
    }

    document.querySelectorAll(`input[name="${typeRadioName}"]`).forEach(radio => {
      radio.addEventListener('change', () => {
        if (searchInput) triggerLookup(searchInput.value.trim());
      });
    });
  }

  // Setup Autocompletes
  setupAutocomplete(fromLocSearch, fromLocSuggestions, 'from_loc_type', fromLocName, fromLocId);
  setupAutocomplete(toLocSearch, toLocSuggestions, 'to_loc_type', toLocName, toLocId);
  setupAutocomplete(platStationSearch, platStationSuggestions, 'plat_station_type', platStationName, platStationId);

  // Close suggestions when clicking outside
  document.addEventListener('click', (e) => {
    if (fromLocSearch && !e.target.closest('#from-loc-search') && !e.target.closest('#from-loc-suggestions')) {
      if (fromLocSuggestions) fromLocSuggestions.classList.add('hidden');
    }
    if (toLocSearch && !e.target.closest('#to-loc-search') && !e.target.closest('#to-loc-suggestions')) {
      if (toLocSuggestions) toLocSuggestions.classList.add('hidden');
    }
    if (platStationSearch && !e.target.closest('#plat-station-search') && !e.target.closest('#plat-station-suggestions')) {
      if (platStationSuggestions) platStationSuggestions.classList.add('hidden');
    }
  });

  // --- Location Modal Handlers ---
  function showLocationModal(editIndex = -1) {
    if (locError) locError.classList.add('hidden');
    if (editLocIndexInput) editLocIndexInput.value = editIndex;
    if (fromLocSuggestions) fromLocSuggestions.classList.add('hidden');
    if (toLocSuggestions) toLocSuggestions.classList.add('hidden');

    if (editIndex >= 0 && editIndex < stagedLocationTransfers.length) {
      const item = stagedLocationTransfers[editIndex];
      if (locModalTitle) locModalTitle.textContent = 'Edit Inter-Location Transfer';
      if (locModalIcon) locModalIcon.textContent = 'edit';
      if (fromLocSearch) fromLocSearch.value = item.from_name || '';
      if (fromLocName) fromLocName.value = item.from_name || '';
      if (fromLocId) fromLocId.value = item.from_id || '';
      if (toLocSearch) toLocSearch.value = item.to_name || '';
      if (toLocName) toLocName.value = item.to_name || '';
      if (toLocId) toLocId.value = item.to_id || '';
      if (locTransferTime) locTransferTime.value = item.transfer_time_minutes || 5;
      if (locBidirectional) locBidirectional.checked = Boolean(item.bidirectional);
      if (locStepFree) locStepFree.checked = Boolean(item.step_free);
      if (locNotes) locNotes.value = item.notes || '';

      const fromRadio = document.querySelector(`input[name="from_loc_type"][value="${item.from_type || ''}"]`);
      if (fromRadio) fromRadio.checked = true;
      const toRadio = document.querySelector(`input[name="to_loc_type"][value="${item.to_type || ''}"]`);
      if (toRadio) toRadio.checked = true;
    } else {
      if (locModalTitle) locModalTitle.textContent = 'Add Inter-Location Transfer';
      if (locModalIcon) locModalIcon.textContent = 'directions_walk';
      if (fromLocSearch) fromLocSearch.value = '';
      if (fromLocName) fromLocName.value = '';
      if (fromLocId) fromLocId.value = '';
      if (toLocSearch) toLocSearch.value = '';
      if (toLocName) toLocName.value = '';
      if (toLocId) toLocId.value = '';
      if (locTransferTime) locTransferTime.value = '5';
      if (locBidirectional) locBidirectional.checked = true;
      if (locStepFree) locStepFree.checked = false;
      if (locNotes) locNotes.value = '';

      const defaultFromRadio = document.querySelector('input[name="from_loc_type"][value=""]');
      if (defaultFromRadio) defaultFromRadio.checked = true;
      const defaultToRadio = document.querySelector('input[name="to_loc_type"][value=""]');
      if (defaultToRadio) defaultToRadio.checked = true;
    }

    if (locModal && typeof locModal.showModal === 'function') {
      locModal.showModal();
    }
  }

  function closeLocationModal() {
    if (locModal && typeof locModal.close === 'function') {
      locModal.close();
    }
  }

  if (openAddLocBtn) openAddLocBtn.addEventListener('click', () => showLocationModal(-1));
  if (emptyAddLocBtn) emptyAddLocBtn.addEventListener('click', () => showLocationModal(-1));
  if (closeLocModalBtn) closeLocModalBtn.addEventListener('click', closeLocationModal);
  if (cancelLocModalBtn) cancelLocModalBtn.addEventListener('click', closeLocationModal);

  if (confirmLocBtn) {
    confirmLocBtn.addEventListener('click', () => {
      const fromTypeRadio = document.querySelector('input[name="from_loc_type"]:checked');
      const toTypeRadio = document.querySelector('input[name="to_loc_type"]:checked');

      const from_type = fromTypeRadio ? fromTypeRadio.value : '';
      const from_name = fromLocName.value.trim();
      const from_id = fromLocId.value.trim();
      const to_type = toTypeRadio ? toTypeRadio.value : '';
      const to_name = toLocName.value.trim();
      const to_id = toLocId.value.trim();
      const transfer_time_minutes = parseInt(locTransferTime.value, 10) || 5;
      const bidirectional = locBidirectional.checked;
      const step_free = locStepFree.checked;
      const notes = locNotes.value.trim();

      if (!from_name || !from_id || !to_name || !to_id) {
        if (locError) locError.classList.remove('hidden');
        return;
      }

      const itemPayload = {
        from_type,
        from_name,
        from_id,
        to_type,
        to_name,
        to_id,
        transfer_time_minutes: Math.max(1, transfer_time_minutes),
        bidirectional,
        step_free,
        notes
      };

      const editIdx = parseInt(editLocIndexInput.value, 10);
      if (editIdx >= 0 && editIdx < stagedLocationTransfers.length) {
        stagedLocationTransfers[editIdx] = itemPayload;
      } else {
        stagedLocationTransfers.push(itemPayload);
      }

      syncState();
      closeLocationModal();
    });
  }

  // --- Platform Modal Handlers ---
  function showPlatformModal(editIndex = -1) {
    if (platError) platError.classList.add('hidden');
    if (editPlatIndexInput) editPlatIndexInput.value = editIndex;
    if (platStationSuggestions) platStationSuggestions.classList.add('hidden');

    if (editIndex >= 0 && editIndex < stagedPlatformTransfers.length) {
      const item = stagedPlatformTransfers[editIndex];
      if (platModalTitle) platModalTitle.textContent = 'Edit Platform Transfer';
      if (platModalIcon) platModalIcon.textContent = 'edit';
      if (platStationSearch) platStationSearch.value = item.location_name || '';
      if (platStationName) platStationName.value = item.location_name || '';
      if (platStationId) platStationId.value = item.location_id || '';
      if (platFromPlatform) platFromPlatform.value = item.from_platform || '';
      if (platToPlatform) platToPlatform.value = item.to_platform || '';
      if (platTransferTime) platTransferTime.value = item.transfer_time_minutes || 2;
      if (platBidirectional) platBidirectional.checked = Boolean(item.bidirectional);
      if (platStepFree) platStepFree.checked = Boolean(item.step_free);
      if (platNotes) platNotes.value = item.notes || '';

      const stationRadio = document.querySelector(`input[name="plat_station_type"][value="${item.location_type || 'station'}"]`);
      if (stationRadio) stationRadio.checked = true;
    } else {
      if (platModalTitle) platModalTitle.textContent = 'Add Platform Transfer';
      if (platModalIcon) platModalIcon.textContent = 'transfer_within_a_station';
      if (platStationSearch) platStationSearch.value = '';
      if (platStationName) platStationName.value = '';
      if (platStationId) platStationId.value = '';
      if (platFromPlatform) platFromPlatform.value = '';
      if (platToPlatform) platToPlatform.value = '';
      if (platTransferTime) platTransferTime.value = '2';
      if (platBidirectional) platBidirectional.checked = true;
      if (platStepFree) platStepFree.checked = false;
      if (platNotes) platNotes.value = '';

      const defaultStationRadio = document.querySelector('input[name="plat_station_type"][value="station"]');
      if (defaultStationRadio) defaultStationRadio.checked = true;
    }

    if (platModal && typeof platModal.showModal === 'function') {
      platModal.showModal();
    }
  }

  function closePlatformModal() {
    if (platModal && typeof platModal.close === 'function') {
      platModal.close();
    }
  }

  if (openAddPlatBtn) openAddPlatBtn.addEventListener('click', () => showPlatformModal(-1));
  if (emptyAddPlatBtn) emptyAddPlatBtn.addEventListener('click', () => showPlatformModal(-1));
  if (closePlatModalBtn) closePlatModalBtn.addEventListener('click', closePlatformModal);
  if (cancelPlatModalBtn) cancelPlatModalBtn.addEventListener('click', closePlatformModal);

  if (confirmPlatBtn) {
    confirmPlatBtn.addEventListener('click', () => {
      const locTypeRadio = document.querySelector('input[name="plat_station_type"]:checked');
      const location_type = locTypeRadio ? locTypeRadio.value : 'station';
      const location_name = platStationName.value.trim();
      const location_id = platStationId.value.trim();
      const from_platform = platFromPlatform.value.trim();
      const to_platform = platToPlatform.value.trim();
      const transfer_time_minutes = parseInt(platTransferTime.value, 10) || 2;
      const bidirectional = platBidirectional.checked;
      const step_free = platStepFree.checked;
      const notes = platNotes.value.trim();

      if (!location_name || !location_id || !from_platform || !to_platform) {
        if (platError) platError.classList.remove('hidden');
        return;
      }

      const itemPayload = {
        location_type,
        location_name,
        location_id,
        from_platform,
        to_platform,
        transfer_time_minutes: Math.max(1, transfer_time_minutes),
        bidirectional,
        step_free,
        notes
      };

      const editIdx = parseInt(editPlatIndexInput.value, 10);
      if (editIdx >= 0 && editIdx < stagedPlatformTransfers.length) {
        stagedPlatformTransfers[editIdx] = itemPayload;
      } else {
        stagedPlatformTransfers.push(itemPayload);
      }

      syncState();
      closePlatformModal();
    });
  }

  // --- Row Action Delegations ---
  document.addEventListener('click', (e) => {
    // Location Grid Actions
    const editLocBtn = e.target.closest('.edit-loc-row-btn');
    if (editLocBtn) {
      const idx = parseInt(editLocBtn.getAttribute('data-index'), 10);
      if (!isNaN(idx)) showLocationModal(idx);
      return;
    }

    const removeLocBtn = e.target.closest('.remove-loc-row-btn');
    if (removeLocBtn) {
      const idx = parseInt(removeLocBtn.getAttribute('data-index'), 10);
      if (!isNaN(idx) && idx >= 0 && idx < stagedLocationTransfers.length) {
        stagedLocationTransfers.splice(idx, 1);
        syncState();
      }
      return;
    }

    // Platform Grid Actions
    const editPlatBtn = e.target.closest('.edit-plat-row-btn');
    if (editPlatBtn) {
      const idx = parseInt(editPlatBtn.getAttribute('data-index'), 10);
      if (!isNaN(idx)) showPlatformModal(idx);
      return;
    }

    const removePlatBtn = e.target.closest('.remove-plat-row-btn');
    if (removePlatBtn) {
      const idx = parseInt(removePlatBtn.getAttribute('data-index'), 10);
      if (!isNaN(idx) && idx >= 0 && idx < stagedPlatformTransfers.length) {
        stagedPlatformTransfers.splice(idx, 1);
        syncState();
      }
      return;
    }
  });
});
