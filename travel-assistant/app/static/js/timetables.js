/**
 * Timetables View Controller.
 * Manages Grid.js data table rendering, in-memory staged mutations,
 * asynchronous station/feed search autocomplete, and modal interactions.
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
    (window.location.pathname.replace(/\/$/, '') + '/search');

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
  const modalSearchInput = document.getElementById('modal-search-input');
  const searchSuggestions = document.getElementById('search-suggestions');
  const searchSpinner = document.getElementById('search-spinner');
  const modalNameInput = document.getElementById('modal_name');
  const modalIdInput = document.getElementById('modal_identifier');
  const modalStatusSelect = document.getElementById('modal_status');
  const modalError = document.getElementById('modal-validation-error');

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
      { name: 'Identifier / Feed', width: '180px' },
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

    // Update empty state vs grid visibility
    if (stagedTimetables.length === 0) {
      gridContainer.classList.add('hidden');
      emptyState.classList.remove('hidden');
    } else {
      gridContainer.classList.remove('hidden');
      emptyState.classList.add('hidden');
    }

    // Re-render Grid.js
    grid
      .updateConfig({
        data: formatGridData(stagedTimetables),
      })
      .forceRender();

    // Check dirty state
    if (window.ConfigDirtyManager) {
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
      stagedTimetables = JSON.parse(initialSnapshot);
      syncState();
    });
  }

  // Delegate row removal clicks
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

  // Open Add Modal
  function showAddModal() {
    if (modalError) modalError.classList.add('hidden');
    if (modalSearchInput) modalSearchInput.value = '';
    if (modalNameInput) modalNameInput.value = '';
    if (modalIdInput) modalIdInput.value = '';
    if (modalStatusSelect) modalStatusSelect.value = 'active';
    if (searchSuggestions) {
      searchSuggestions.innerHTML = '';
      searchSuggestions.classList.add('hidden');
    }
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
        document
          .querySelectorAll('.transport-type-label')
          .forEach((lbl) => {
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
        if (modalSearchInput) {
          triggerSearch(modalSearchInput.value.trim());
        }
      });
    });

  // Dynamic autocomplete search querying searchUrl
  let searchDebounce = null;
  async function triggerSearch(query) {
    const type = getSelectedTransportType();
    if (searchSpinner) searchSpinner.classList.remove('hidden');

    try {
      const sep = searchUrl.includes('?') ? '&' : '?';
      const res = await fetch(
        `${searchUrl}${sep}type=${encodeURIComponent(
          type
        )}&q=${encodeURIComponent(query)}`
      );
      const data = await res.json();
      renderSuggestions(data.results || []);
    } catch (err) {
      console.error('Search lookup failed:', err);
    } finally {
      if (searchSpinner) searchSpinner.classList.add('hidden');
    }
  }

  function renderSuggestions(results) {
    if (!searchSuggestions) return;
    if (!results || results.length === 0) {
      searchSuggestions.innerHTML = `<div class="p-3 text-xs text-slate-500 dark:text-slate-400 text-center">No matching templates found. Enter custom details below.</div>`;
      searchSuggestions.classList.remove('hidden');
      return;
    }

    searchSuggestions.innerHTML = '';
    results.forEach((item) => {
      const div = document.createElement('div');
      div.className =
        'p-2.5 hover:bg-sky-50 dark:hover:bg-slate-700/60 cursor-pointer rounded-lg transition-colors flex items-center justify-between gap-3';
      div.innerHTML = `
        <div class="min-w-0">
          <div class="text-xs font-semibold text-slate-900 dark:text-slate-100 truncate">${escapeHtml(
            item.name
          )}</div>
          <div class="text-xs text-slate-500 dark:text-slate-400 truncate">${escapeHtml(
            item.description || item.identifier
          )}</div>
        </div>
        <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 shrink-0">${escapeHtml(
          item.identifier
        )}</span>
      `;
      div.addEventListener('click', () => {
        if (modalNameInput) modalNameInput.value = item.name;
        if (modalIdInput) modalIdInput.value = item.identifier;
        searchSuggestions.classList.add('hidden');
      });
      searchSuggestions.appendChild(div);
    });
    searchSuggestions.classList.remove('hidden');
  }

  if (modalSearchInput) {
    modalSearchInput.addEventListener('input', () => {
      clearTimeout(searchDebounce);
      searchDebounce = setTimeout(() => {
        triggerSearch(modalSearchInput.value.trim());
      }, 250);
    });

    modalSearchInput.addEventListener('focus', () => {
      if (
        searchSuggestions &&
        searchSuggestions.children &&
        searchSuggestions.children.length > 0
      ) {
        searchSuggestions.classList.remove('hidden');
      } else {
        triggerSearch(modalSearchInput.value.trim());
      }
    });
  }

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
