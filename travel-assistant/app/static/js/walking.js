/**
 * Walking Configuration Controller
 * 
 * Manages client-side staged state for configured walking routes with Grid.js and
 * an interactive modal dialogue featuring multi-place live search autocompletion
 * (Rail Stations, Bus Stops, Home Assistant Zones, and Custom Locations),
 * walking duration in minutes, and bidirectionality support.
 */

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('walking-form');
  if (!form) return;

  const searchBaseUrl = form.getAttribute('data-search-url') || '/config/search/places';

  // Parse initial data payload
  const initialScript = document.getElementById('initial-walking-data');
  let initialWalkingData = [];
  try {
    if (initialScript && initialScript.textContent) {
      initialWalkingData = JSON.parse(initialScript.textContent);
    }
  } catch (e) {
    console.error('Failed to parse initial walking data:', e);
  }

  // In-memory staged state
  let stagedWalking = JSON.parse(JSON.stringify(initialWalkingData || []));
  const initialSnapshot = JSON.stringify(stagedWalking);

  // DOM Elements
  const hiddenInput = document.getElementById('walking_json');
  const gridWrapper = document.getElementById('walking-grid-wrapper');
  const emptyState = document.getElementById('walking-grid-empty-state');

  // Modal Elements
  const modal = document.getElementById('walking-modal');
  const openAddBtn = document.getElementById('open-add-walking-modal-btn');
  const emptyAddBtn = document.getElementById('empty-add-walking-btn');
  const closeModalBtn = document.getElementById('close-walking-modal-btn');
  const cancelModalBtn = document.getElementById('cancel-walking-modal-btn');
  const confirmBtn = document.getElementById('confirm-walking-btn');
  const modalTitle = document.getElementById('walking-modal-title');
  const modalIcon = document.getElementById('walking-modal-icon');
  const editIndexInput = document.getElementById('edit-walking-index');
  const modalError = document.getElementById('walking-modal-error');
  const timeNeededInput = document.getElementById('walking_time_needed');
  const bidirectionalInput = document.getElementById('walking_bidirectional');

  // Start Location Elements
  const startSearchInput = document.getElementById('start-walking-search');
  const startSuggestions = document.getElementById('start-walking-suggestions');
  const startTypeInput = document.getElementById('start_walking_type');
  const startIdInput = document.getElementById('start_walking_id');
  const startNameInput = document.getElementById('start_walking_name');
  const startPreview = document.getElementById('start-selected-preview');
  const startPreviewIcon = document.getElementById('start-preview-icon');
  const startPreviewName = document.getElementById('start-preview-name');
  const startPreviewId = document.getElementById('start-preview-id');
  const clearStartBtn = document.getElementById('clear-start-selection');

  // Finish Location Elements
  const finishSearchInput = document.getElementById('finish-walking-search');
  const finishSuggestions = document.getElementById('finish-walking-suggestions');
  const finishTypeInput = document.getElementById('finish_walking_type');
  const finishIdInput = document.getElementById('finish_walking_id');
  const finishNameInput = document.getElementById('finish_walking_name');
  const finishPreview = document.getElementById('finish-selected-preview');
  const finishPreviewIcon = document.getElementById('finish-preview-icon');
  const finishPreviewName = document.getElementById('finish-preview-name');
  const finishPreviewId = document.getElementById('finish-preview-id');
  const clearFinishBtn = document.getElementById('clear-finish-selection');

  const escapeHtml = (window.TransitUI && window.TransitUI.escapeHtml) || function (str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  };

  const getLocationBadge = (window.TransitUI && window.TransitUI.getTransportBadge) || function (type) {
    const t = String(type || '').toLowerCase();
    if (t === 'rail') {
      return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-indigo-100 text-indigo-800 dark:bg-indigo-950/80 dark:text-indigo-300 dark:ring-1 dark:ring-indigo-500/30"><span class="material-symbols-outlined text-xs leading-none">train</span> Rail</span>`;
    } else if (t === 'bus') {
      return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-300 dark:ring-1 dark:ring-amber-500/30"><span class="material-symbols-outlined text-xs leading-none">directions_bus</span> Bus</span>`;
    } else if (t === 'tram') {
      return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-purple-100 text-purple-800 dark:bg-purple-950/80 dark:text-purple-300 dark:ring-1 dark:ring-purple-500/30"><span class="material-symbols-outlined text-xs leading-none">tram</span> Tram</span>`;
    } else if (t === 'metro') {
      return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300 dark:ring-1 dark:ring-emerald-500/30"><span class="material-symbols-outlined text-xs leading-none">subway</span> Metro</span>`;
    } else if (t === 'ferry') {
      return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-cyan-100 text-cyan-800 dark:bg-cyan-950/80 dark:text-cyan-300 dark:ring-1 dark:ring-cyan-500/30"><span class="material-symbols-outlined text-xs leading-none">directions_boat</span> Ferry</span>`;
    } else if (t === 'air') {
      return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-sky-100 text-sky-800 dark:bg-sky-950/80 dark:text-sky-300 dark:ring-1 dark:ring-sky-500/30"><span class="material-symbols-outlined text-xs leading-none">flight</span> Air</span>`;
    } else if (t === 'ha') {
      return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 dark:bg-rose-950/80 dark:text-rose-300 dark:ring-1 dark:ring-rose-500/30"><span class="material-symbols-outlined text-xs leading-none">home</span> HA Zone</span>`;
    }
    return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-300"><span class="material-symbols-outlined text-xs leading-none">pin_drop</span> Custom</span>`;
  };

  const getLocationIcon = (window.TransitUI && window.TransitUI.getTransportIcon) || function (type) {
    const t = String(type || '').toLowerCase();
    if (t === 'rail') return 'train';
    if (t === 'bus') return 'directions_bus';
    if (t === 'tram') return 'tram';
    if (t === 'metro') return 'subway';
    if (t === 'ferry') return 'directions_boat';
    if (t === 'air') return 'flight';
    if (t === 'ha') return 'home';
    return 'pin_drop';
  };

  // Setup PlaceAutocomplete instances
  let startAutocomplete = null;
  let finishAutocomplete = null;

  if (window.PlaceAutocomplete && startSearchInput && startSuggestions) {
    startAutocomplete = window.PlaceAutocomplete.create({
      inputEl: startSearchInput,
      suggestionsEl: startSuggestions,
      searchBaseUrl: searchBaseUrl,
      onSelect: (item) => {
        setStartSelection(item.type, item.id, item.name);
        startAutocomplete.hide();
      },
    });
  }

  if (window.PlaceAutocomplete && finishSearchInput && finishSuggestions) {
    finishAutocomplete = window.PlaceAutocomplete.create({
      inputEl: finishSearchInput,
      suggestionsEl: finishSuggestions,
      searchBaseUrl: searchBaseUrl,
      onSelect: (item) => {
        setFinishSelection(item.type, item.id, item.name);
        finishAutocomplete.hide();
      },
    });
  }

  function setStartSelection(type, id, name) {
    startTypeInput.value = type || 'custom';
    startIdInput.value = id || '';
    startNameInput.value = name || '';

    if (id && name) {
      startPreviewIcon.textContent = getLocationIcon(type);
      startPreviewName.textContent = name;
      startPreviewId.textContent = id;
      startPreview.classList.remove('hidden');
      startSearchInput.value = '';
      startSearchInput.classList.add('hidden');
    } else {
      clearStartSelection();
    }
  }

  function clearStartSelection() {
    startTypeInput.value = '';
    startIdInput.value = '';
    startNameInput.value = '';
    startPreview.classList.add('hidden');
    startSearchInput.classList.remove('hidden');
    startSearchInput.value = '';
    if (startAutocomplete) startAutocomplete.clear();
  }

  function setFinishSelection(type, id, name) {
    finishTypeInput.value = type || 'custom';
    finishIdInput.value = id || '';
    finishNameInput.value = name || '';

    if (id && name) {
      finishPreviewIcon.textContent = getLocationIcon(type);
      finishPreviewName.textContent = name;
      finishPreviewId.textContent = id;
      finishPreview.classList.remove('hidden');
      finishSearchInput.value = '';
      finishSearchInput.classList.add('hidden');
    } else {
      clearFinishSelection();
    }
  }

  function clearFinishSelection() {
    finishTypeInput.value = '';
    finishIdInput.value = '';
    finishNameInput.value = '';
    finishPreview.classList.add('hidden');
    finishSearchInput.classList.remove('hidden');
    finishSearchInput.value = '';
    if (finishAutocomplete) finishAutocomplete.clear();
  }

  if (clearStartBtn) clearStartBtn.addEventListener('click', clearStartSelection);
  if (clearFinishBtn) clearFinishBtn.addEventListener('click', clearFinishSelection);

  // Format data rows for Grid.js
  function formatGridData(items) {
    return items.map((item, index) => {
      const startBadge = getLocationBadge(item.start_type);
      const finishBadge = getLocationBadge(item.finish_type);

      const startHtml = `
        <div class="space-y-1">
          <div class="flex items-center gap-1.5 font-semibold text-slate-900 dark:text-slate-100">
            <span class="material-symbols-outlined text-slate-400 dark:text-slate-500 text-sm">${escapeHtml(getLocationIcon(item.start_type))}</span>
            <span>${escapeHtml(item.start_name)}</span>
          </div>
          <div class="flex items-center gap-1.5">
            ${startBadge}
            <span class="text-[11px] font-mono text-slate-400 dark:text-slate-500">${escapeHtml(item.start_id)}</span>
          </div>
        </div>
      `;

      const finishHtml = `
        <div class="space-y-1">
          <div class="flex items-center gap-1.5 font-semibold text-slate-900 dark:text-slate-100">
            <span class="material-symbols-outlined text-slate-400 dark:text-slate-500 text-sm">${escapeHtml(getLocationIcon(item.finish_type))}</span>
            <span>${escapeHtml(item.finish_name)}</span>
          </div>
          <div class="flex items-center gap-1.5">
            ${finishBadge}
            <span class="text-[11px] font-mono text-slate-400 dark:text-slate-500">${escapeHtml(item.finish_id)}</span>
          </div>
        </div>
      `;

      const isBidi = item.bidirectional !== false;
      const directionHtml = isBidi
        ? `<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300 border border-emerald-200/80 dark:border-emerald-800/60" title="Walking duration applies in both directions"><span class="material-symbols-outlined text-sm">sync_alt</span> Two-way</span>`
        : `<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400" title="Walking duration applies only from start to finish"><span class="material-symbols-outlined text-sm">arrow_forward</span> One-way</span>`;

      const durationHtml = `
        <span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-xl text-xs font-bold font-mono bg-sky-50 text-sky-700 dark:bg-sky-950/60 dark:text-sky-300 border border-sky-200/80 dark:border-sky-800/60">
          <span class="material-symbols-outlined text-sm">schedule</span>
          ${escapeHtml(item.time_needed_minutes || 5)} min${item.time_needed_minutes === 1 ? '' : 's'}
        </span>
      `;

      const actionButtons = window.TransitUI && window.TransitUI.renderActionButtons
        ? window.TransitUI.renderActionButtons({
            index,
            isReadOnly: false,
            editClass: 'edit-walking-btn',
            deleteClass: 'delete-walking-btn',
            editTitle: 'Edit walking route',
            deleteTitle: 'Delete walking route',
          })
        : `<div class="flex items-center gap-1.5">
             <button 
               type="button" 
               class="edit-walking-btn inline-flex items-center justify-center w-7 h-7 rounded-lg bg-sky-50 text-sky-600 hover:bg-sky-100 hover:text-sky-700 dark:bg-sky-950/50 dark:text-sky-400 dark:hover:bg-sky-900/60 transition-colors cursor-pointer"
               data-index="${index}"
               title="Edit walking route"
               aria-label="Edit walking route"
             >
               <span class="material-symbols-outlined text-[17px] leading-none">edit</span>
             </button>
             <button 
               type="button" 
               class="delete-walking-btn inline-flex items-center justify-center w-7 h-7 rounded-lg bg-rose-50 text-rose-600 hover:bg-rose-100 hover:text-rose-700 dark:bg-rose-950/50 dark:text-rose-400 dark:hover:bg-rose-900/60 transition-colors cursor-pointer"
               data-index="${index}"
               title="Delete walking route"
               aria-label="Delete walking route"
             >
               <span class="material-symbols-outlined text-[17px] leading-none">delete</span>
             </button>
           </div>`;

      return [
        gridjs.html(startHtml),
        gridjs.html(finishHtml),
        gridjs.html(durationHtml),
        gridjs.html(directionHtml),
        gridjs.html(actionButtons),
      ];
    });
  }

  const columnsConfig = [
    { name: 'Start Location', width: 'auto', sort: true },
    { name: 'Finish Location', width: 'auto', sort: true },
    { name: 'Time Needed', width: '150px', sort: true },
    { name: 'Direction', width: '140px', sort: false },
    { name: 'Actions', width: '100px', sort: false },
  ];

  // Initialise Grid.js instance
  const grid = new gridjs.Grid({
    columns: columnsConfig,
    data: formatGridData(stagedWalking),
    sort: true,
    search: {
      enabled: true,
      placeholder: 'Search walking routes...',
    },
    pagination: {
      enabled: true,
      limit: 10,
      summary: true,
    },
    className: {
      table: 'w-full text-left border-collapse text-sm',
      thead: 'bg-slate-50 dark:bg-slate-800/80 text-slate-700 dark:text-slate-300 uppercase text-xs tracking-wider border-b border-slate-200 dark:border-slate-800 font-semibold',
      tbody: 'divide-y divide-slate-100 dark:divide-slate-800 text-slate-700 dark:text-slate-300',
      search: 'w-full sm:w-72 mb-4',
    },
    language: {
      search: {
        placeholder: 'Search walking routes...',
      },
      pagination: {
        previous: 'Previous',
        next: 'Next',
        showing: 'Showing',
        of: 'of',
        to: 'to',
        results: 'routes',
      },
      noRecordsFound: 'No matching walking routes found',
    },
  });

  if (gridWrapper) {
    grid.render(gridWrapper);
  }

  function syncState() {
    if (hiddenInput) {
      hiddenInput.value = JSON.stringify(stagedWalking);
    }

    if (stagedWalking.length === 0) {
      if (emptyState) emptyState.classList.remove('hidden');
      if (gridWrapper) gridWrapper.classList.add('hidden');
    } else {
      if (emptyState) emptyState.classList.add('hidden');
      if (gridWrapper) gridWrapper.classList.remove('hidden');
    }

    if (gridWrapper && gridWrapper.querySelector('.gridjs-container')) {
      if (stagedWalking.length <= 10) {
        gridWrapper.querySelector('.gridjs-container').setAttribute('data-single-page', 'true');
      } else {
        gridWrapper.querySelector('.gridjs-container').removeAttribute('data-single-page');
      }
    }

    grid.updateConfig({
      columns: columnsConfig,
      data: formatGridData(stagedWalking),
    }).forceRender();

    // Trigger DirtyManager check
    if (window.ConfigDirtyManager) {
      const currentJson = JSON.stringify(stagedWalking);
      if (currentJson !== initialSnapshot) {
        window.ConfigDirtyManager.markDirty();
      } else {
        window.ConfigDirtyManager.clearDirty();
      }
    }
  }

  // Initial sync
  syncState();

  // Register discard handler
  if (window.ConfigDirtyManager) {
    window.ConfigDirtyManager.registerDiscardHandler(() => {
      stagedWalking = JSON.parse(initialSnapshot);
      syncState();
    });
  }

  // Open modal helper
  function openModal(mode = 'add', index = -1) {
    if (modalError) modalError.classList.add('hidden');
    editIndexInput.value = index;

    if (mode === 'edit' && index >= 0 && index < stagedWalking.length) {
      const item = stagedWalking[index];
      modalTitle.textContent = 'Edit Walking Route';
      modalIcon.textContent = 'edit';

      setStartSelection(item.start_type, item.start_id, item.start_name);
      setFinishSelection(item.finish_type, item.finish_id, item.finish_name);
      timeNeededInput.value = item.time_needed_minutes || 5;
      bidirectionalInput.checked = item.bidirectional !== false;
    } else {
      modalTitle.textContent = 'Add New Walking Route';
      modalIcon.textContent = 'directions_walk';

      clearStartSelection();
      clearFinishSelection();
      timeNeededInput.value = '5';
      bidirectionalInput.checked = true;
    }

    if (modal && typeof modal.showModal === 'function') {
      modal.showModal();
    }
  }

  function closeModal() {
    if (modal && typeof modal.close === 'function') {
      modal.close();
    }
  }

  if (openAddBtn) openAddBtn.addEventListener('click', () => openModal('add'));
  if (emptyAddBtn) emptyAddBtn.addEventListener('click', () => openModal('add'));
  if (closeModalBtn) closeModalBtn.addEventListener('click', closeModal);
  if (cancelModalBtn) cancelModalBtn.addEventListener('click', closeModal);

  // Save walking route from modal
  if (confirmBtn) {
    confirmBtn.addEventListener('click', () => {
      const startId = startIdInput.value.trim();
      const startName = startNameInput.value.trim();
      const startType = startTypeInput.value.trim() || 'custom';

      const finishId = finishIdInput.value.trim();
      const finishName = finishNameInput.value.trim();
      const finishType = finishTypeInput.value.trim() || 'custom';

      const timeVal = parseInt(timeNeededInput.value, 10);
      const isBidi = bidirectionalInput.checked;

      if (!startId || !startName || !finishId || !finishName || isNaN(timeVal) || timeVal < 1) {
        if (modalError) modalError.classList.remove('hidden');
        return;
      }

      const idx = parseInt(editIndexInput.value, 10);
      const existingId =
        !isNaN(idx) && idx >= 0 && idx < stagedWalking.length
          ? stagedWalking[idx].id
          : undefined;

      const entry = {
        ...(existingId !== undefined ? { id: existingId } : {}),
        start_type: startType,
        start_id: startId,
        start_name: startName,
        finish_type: finishType,
        finish_id: finishId,
        finish_name: finishName,
        time_needed_minutes: timeVal,
        bidirectional: isBidi,
      };

      if (!isNaN(idx) && idx >= 0 && idx < stagedWalking.length) {
        stagedWalking[idx] = entry;
      } else {
        stagedWalking.push(entry);
      }

      syncState();
      closeModal();
    });
  }

  // Row button click handlers via event delegation
  document.addEventListener('click', (e) => {
    const editBtn = e.target.closest('.edit-walking-btn');
    if (editBtn) {
      const idx = parseInt(editBtn.getAttribute('data-index'), 10);
      if (!isNaN(idx)) openModal('edit', idx);
      return;
    }

    const deleteBtn = e.target.closest('.delete-walking-btn');
    if (deleteBtn) {
      const idx = parseInt(deleteBtn.getAttribute('data-index'), 10);
      if (!isNaN(idx) && idx >= 0 && idx < stagedWalking.length) {
        stagedWalking.splice(idx, 1);
        syncState();
      }
      return;
    }
  });
});
