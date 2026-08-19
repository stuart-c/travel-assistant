/**
 * Transfers Configuration Controller
 * 
 * Manages client-side staged state for Platform & Stand Transfers
 * using Grid.js and modal dialogues with live search autocomplete.
 */

document.addEventListener('DOMContentLoaded', () => {
  const configEl =
    document.getElementById('transfers-config') ||
    document.getElementById('transfers-form');
  if (!configEl) return;

  const searchBaseUrl =
    configEl.getAttribute('data-search-url') || '/config/search/places';
  const dataUrl =
    configEl.getAttribute('data-data-url') || '/config/transfers/data';

  // In-memory staged state (seeded after remote fetch)
  let stagedPlatformTransfers = [];
  let initialPlatformSnapshot = '[]';

  // Containers
  const platGridWrapper = document.getElementById(
    'platform-transfers-grid-wrapper'
  );
  const platEmptyState = document.getElementById('platform-grid-empty-state');

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
  const platStationType = document.getElementById('plat_station_type');
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

  const escapeHtml = (window.TransitUI && window.TransitUI.escapeHtml) || function (str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  };

  const getLocationBadge = function (type) {
    if (window.TransitUI && window.TransitUI.getTransportBadge) {
      return window.TransitUI.getTransportBadge(type, null, true);
    }
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
  };

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
        gridjs.html(
          window.TransitUI && window.TransitUI.renderActionButtons
            ? window.TransitUI.renderActionButtons({
                index,
                editClass: 'edit-plat-row-btn',
                deleteClass: 'remove-plat-row-btn',
                editTitle: 'Edit platform transfer',
                deleteTitle: 'Delete platform transfer',
              })
            : `<div class="flex items-center gap-1.5">
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
              </div>`
        )
      ];
    });
  }

  const platColumnsConfig = [
    { name: 'Station / Interchange', width: '200px', sort: true },
    { name: 'From Platform', width: '130px', sort: true },
    { name: 'To Platform', width: '130px', sort: true },
    { name: 'Duration', width: '110px', sort: true },
    { name: 'Direction', width: '130px', sort: true },
    { name: 'Step-Free', width: '100px', sort: true },
    { name: 'Notes', width: 'auto', sort: true },
    { name: 'Actions', width: '90px', sort: false }
  ];

  // --- Initialise Platform Grid.js ---
  const platformGrid = new gridjs.Grid({
    columns: platColumnsConfig,
    data: formatPlatformGridData(stagedPlatformTransfers),
    search: { placeholder: 'Search platform transfers...' },
    pagination: { limit: 10, summary: true },
    sort: true,
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
  });

  let gridRendered = false;

  // Fetch remote data then render — loading/error UI managed by GridLoader
  function loadTransfers() {
    GridLoader.load(dataUrl, platGridWrapper, {
      label: 'transfers',
      emptyState: platEmptyState,
      onSuccess(json) {
        stagedPlatformTransfers = Array.isArray(json.data) ? json.data : [];
        initialPlatformSnapshot = JSON.stringify(stagedPlatformTransfers);
        if (!gridRendered) {
          platformGrid.render(platGridWrapper);
          gridRendered = true;
        }
        syncState();
      },
    });
  }

  // --- Sync State with Dirty Manager ---
  function syncState() {
    const currentPlatJson = JSON.stringify(stagedPlatformTransfers);

    // Toggle Empty State vs Grid
    if (stagedPlatformTransfers.length === 0) {
      platGridWrapper.classList.add('hidden');
      platEmptyState.classList.remove('hidden');
    } else {
      platGridWrapper.classList.remove('hidden');
      platEmptyState.classList.add('hidden');
    }

    // Force Re-render Grid & check pagination display
    if (platGridWrapper.querySelector('.gridjs-container')) {
      if (stagedPlatformTransfers.length <= 10) {
        platGridWrapper
          .querySelector('.gridjs-container')
          .setAttribute('data-single-page', 'true');
      } else {
        platGridWrapper
          .querySelector('.gridjs-container')
          .removeAttribute('data-single-page');
      }
    }

    platformGrid
      .updateConfig({
        columns: platColumnsConfig,
        data: formatPlatformGridData(stagedPlatformTransfers),
      })
      .forceRender();

    // Check Dirty Status
    if (window.ConfigDirtyManager) {
      const isDirty = currentPlatJson !== initialPlatformSnapshot;
      if (isDirty) {
        window.ConfigDirtyManager.markDirty();
      } else {
        window.ConfigDirtyManager.clearDirty();
      }
    }
  }

  // Initial Sync
  syncState();

  // Register Discard Handler with ConfigDirtyManager
  if (window.ConfigDirtyManager) {
    window.ConfigDirtyManager.registerDiscardHandler(() => {
      stagedPlatformTransfers = JSON.parse(initialPlatformSnapshot);
      syncState();
    });
  }

  // --- Platform Autocomplete Setup ---
  const platAutocomplete = window.PlaceAutocomplete
    ? window.PlaceAutocomplete.create({
        inputEl: platStationSearch,
        suggestionsEl: platStationSuggestions,
        defaultFilter: 'rail',
        searchBaseUrl,
        emptyText: 'No matching locations found. Enter details manually below.',
        onSelect: (item) => {
          if (platStationName) platStationName.value = item.name;
          if (platStationId) platStationId.value = item.id;
          if (platStationType && item.type) {
            platStationType.value = item.type;
          }
          if (platAutocomplete) platAutocomplete.hide();
        },
      })
    : null;

  // --- Platform Modal Handlers ---
  function showPlatformModal(editIndex = -1) {
    if (platError) platError.classList.add('hidden');
    if (editPlatIndexInput) editPlatIndexInput.value = editIndex;
    if (platStationSuggestions) platStationSuggestions.classList.add('hidden');

    if (editIndex >= 0 && editIndex < stagedPlatformTransfers.length) {
      const item = stagedPlatformTransfers[editIndex];
      if (platModalTitle) platModalTitle.textContent = 'Edit Platform Transfer';
      if (platModalIcon) platModalIcon.textContent = 'edit';
      if (platStationType) platStationType.value = item.location_type || 'rail';
      if (platStationSearch) platStationSearch.value = item.location_name || '';
      if (platStationName) platStationName.value = item.location_name || '';
      if (platStationId) platStationId.value = item.location_id || '';
      if (platFromPlatform) platFromPlatform.value = item.from_platform || '';
      if (platToPlatform) platToPlatform.value = item.to_platform || '';
      if (platTransferTime) platTransferTime.value = item.transfer_time_minutes || 2;
      if (platBidirectional) platBidirectional.checked = Boolean(item.bidirectional);
      if (platStepFree) platStepFree.checked = Boolean(item.step_free);
      if (platNotes) platNotes.value = item.notes || '';
    } else {
      if (platModalTitle) platModalTitle.textContent = 'Add Platform Transfer';
      if (platModalIcon) platModalIcon.textContent = 'transfer_within_a_station';
      if (platStationType) platStationType.value = 'rail';
      if (platStationSearch) platStationSearch.value = '';
      if (platStationName) platStationName.value = '';
      if (platStationId) platStationId.value = '';
      if (platFromPlatform) platFromPlatform.value = '';
      if (platToPlatform) platToPlatform.value = '';
      if (platTransferTime) platTransferTime.value = '2';
      if (platBidirectional) platBidirectional.checked = true;
      if (platStepFree) platStepFree.checked = false;
      if (platNotes) platNotes.value = '';

      if (platAutocomplete) {
        platAutocomplete.resetFilter('rail');
      }
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
      const location_type = platStationType ? platStationType.value : 'rail';
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

  // Register discard handler
  if (window.ConfigDirtyManager) {
    window.ConfigDirtyManager.registerDiscardHandler(() => {
      stagedPlatformTransfers = JSON.parse(initialPlatformSnapshot);
      syncState();
    });
  }

  // Register with ConfigSave
  if (window.ConfigSave) {
    window.ConfigSave.register({
      endpoint: dataUrl,
      getChangeset: () => {
        const initialList = JSON.parse(initialPlatformSnapshot || '[]');
        return window.TransitUI.computeChangeset(
          initialList,
          stagedPlatformTransfers,
          'id'
        );
      },
      onSaveSuccess: () => {
        loadTransfers();
      },
    });
  }

  loadTransfers();
});

