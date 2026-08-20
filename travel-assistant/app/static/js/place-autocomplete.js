/**
 * PlaceAutocomplete Component for Travel Assistant.
 * Provides unified place & transit search autocomplete dropdowns with pinned filter chips.
 */
window.PlaceAutocomplete = (function () {
  'use strict';

  const PLACE_TYPE_FILTERS = [
    { type: 'all', label: 'All', icon: 'apps' },
    { type: 'rail', label: 'Train', icon: 'train' },
    { type: 'bus', label: 'Bus', icon: 'directions_bus' },
    { type: 'metro', label: 'Metro', icon: 'subway' },
    { type: 'tram', label: 'Tram', icon: 'tram' },
    { type: 'ferry', label: 'Ferry', icon: 'directions_boat' },
    { type: 'air', label: 'Air', icon: 'flight' },
    { type: 'ha', label: 'HA', icon: 'home' },
    { type: 'custom', label: 'Custom', icon: 'pin_drop' },
  ];

  function escapeHtml(str) {
    if (window.TransitUI && typeof window.TransitUI.escapeHtml === 'function') {
      return window.TransitUI.escapeHtml(str);
    }
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function getIcon(type) {
    if (window.TransitUI && typeof window.TransitUI.getTransportIcon === 'function') {
      return window.TransitUI.getTransportIcon(type);
    }
    return 'place';
  }

  function getBadge(type) {
    if (window.TransitUI && typeof window.TransitUI.getTransportBadge === 'function') {
      return window.TransitUI.getTransportBadge(type);
    }
    return `<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-slate-100 text-slate-700">${escapeHtml(
      type || 'Place'
    )}</span>`;
  }

  /**
   * Initialises a PlaceAutocomplete instance on an input element.
   *
   * @param {Object} options
   * @param {HTMLElement} options.inputEl - The search input text field.
   * @param {HTMLElement} options.suggestionsEl - The container element to render suggestions into.
   * @param {string} [options.defaultFilter='all'] - Default active filter type.
   * @param {string} [options.searchBaseUrl] - Base search URL. Defaults to `<ingress_path>/config/search/places`.
   * @param {number} [options.limit=15] - Maximum number of search suggestions.
   * @param {string} [options.emptyText] - Custom empty state message.
   * @param {Function} [options.onSelect] - Callback invoked when a suggestion is clicked: `(item) => {}`.
   */
  function create(options) {
    const {
      inputEl,
      suggestionsEl,
      defaultFilter = 'all',
      searchBaseUrl = '',
      limit = 15,
      emptyText = '',
      onSelect = null,
    } = options || {};

    if (!inputEl || !suggestionsEl) return null;

    let debounceTimer = null;
    let activeFilter = defaultFilter;
    let currentResults = [];

    function getEffectiveSearchUrl() {
      if (searchBaseUrl) return searchBaseUrl;
      const ingress = document.body.getAttribute('data-ingress-path') || '';
      return `${ingress}/config/search/places`;
    }

    async function fetchPlaces() {
      const q = inputEl.value.trim();
      const typeParam = activeFilter !== 'all' ? `&type=${encodeURIComponent(activeFilter)}` : '';
      const url = `${getEffectiveSearchUrl()}?q=${encodeURIComponent(q)}${typeParam}&limit=${limit}`;

      try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error('Search failed');
        const data = await resp.json();
        currentResults = data.items || [];
        renderDropdown();
      } catch (err) {
        console.error('Place search error:', err);
        currentResults = [];
        renderDropdown();
      }
    }

    function renderDropdown() {
      const q = inputEl.value.trim();
      const hasQuery = q.length > 0;

      let chipsHtml = `
        <div class="px-2.5 py-2 border-b border-slate-100 dark:border-slate-800 bg-slate-50/80 dark:bg-slate-800/80 flex flex-wrap gap-1 items-center sticky top-0 z-10">
          <span class="text-[10px] font-bold uppercase tracking-wider text-slate-600 dark:text-slate-400 mr-1">Filter:</span>
      `;

      PLACE_TYPE_FILTERS.forEach((f) => {
        const isActive = f.type === activeFilter;
        const activeClass = isActive
          ? 'bg-sky-600 text-white font-bold'
          : 'bg-white dark:bg-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-600 border border-slate-200 dark:border-slate-600';

        chipsHtml += `
          <button 
            type="button" 
            class="place-filter-chip px-2 py-0.5 rounded-full text-[11px] inline-flex items-center gap-1 transition-colors cursor-pointer ${activeClass}" 
            data-filter="${f.type}"
          >
            <span class="material-symbols-outlined text-[12px] leading-none">${f.icon}</span>
            <span>${f.label}</span>
          </button>
        `;
      });
      chipsHtml += '</div>';

      let itemsHtml = '';
      if (currentResults.length === 0) {
        const message = emptyText
          ? emptyText
          : hasQuery
          ? `No places found for "${escapeHtml(q)}"`
          : 'Type to search stops or Home Assistant locations...';

        itemsHtml = `
          <div class="px-4 py-4 text-center text-xs text-slate-500 dark:text-slate-400">
            <span class="material-symbols-outlined text-base block mb-1">search_off</span>
            ${message}
          </div>
        `;
      } else {
        itemsHtml = `<div class="divide-y divide-slate-100 dark:divide-slate-800 max-h-56 overflow-y-auto">`;
        currentResults.forEach((item, idx) => {
          const badge = getBadge(item.type);
          const metaSub = [item.indicator, item.id ? `Code: ${item.id}` : '']
            .filter(Boolean)
            .join(' • ');

          itemsHtml += `
            <div 
              class="place-item px-3 py-2 hover:bg-sky-50 dark:hover:bg-sky-950/40 cursor-pointer flex items-center justify-between gap-2 transition-colors" 
              data-idx="${idx}"
            >
              <div class="flex items-center gap-2 min-w-0">
                <span class="material-symbols-outlined text-slate-600 dark:text-slate-400 text-lg flex-shrink-0">${getIcon(
                  item.type
                )}</span>
                <div class="truncate">
                  <div class="text-xs font-semibold text-slate-900 dark:text-slate-100 truncate">${escapeHtml(
                    item.name
                  )}</div>
                  ${
                    metaSub
                      ? `<div class="text-[10px] text-slate-600 dark:text-slate-400 truncate">${escapeHtml(
                          metaSub
                        )}</div>`
                      : ''
                  }
                </div>
              </div>
              <div class="flex-shrink-0">${badge}</div>
            </div>
          `;
        });
        itemsHtml += '</div>';
      }

      suggestionsEl.innerHTML = chipsHtml + itemsHtml;
      suggestionsEl.classList.remove('hidden');

      // Bind filter chip buttons
      suggestionsEl.querySelectorAll('.place-filter-chip').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          activeFilter = btn.getAttribute('data-filter') || 'all';
          fetchPlaces();
        });
      });

      // Bind item click
      suggestionsEl.querySelectorAll('.place-item').forEach((row) => {
        row.addEventListener('click', () => {
          const idx = parseInt(row.getAttribute('data-idx'), 10);
          const selected = currentResults[idx];
          if (selected) {
            suggestionsEl.classList.add('hidden');
            if (typeof onSelect === 'function') {
              onSelect(selected);
            }
          }
        });
      });
    }

    inputEl.addEventListener('input', () => {
      const q = inputEl.value.trim();
      clearTimeout(debounceTimer);

      if (!q) {
        suggestionsEl.innerHTML = '';
        suggestionsEl.classList.add('hidden');
        return;
      }

      debounceTimer = setTimeout(fetchPlaces, 200);
    });

    inputEl.addEventListener('focus', () => {
      const q = inputEl.value.trim();
      if (q) {
        fetchPlaces();
      }
    });

    // Close suggestions on outside click
    document.addEventListener('click', (e) => {
      if (!inputEl.contains(e.target) && !suggestionsEl.contains(e.target)) {
        suggestionsEl.classList.add('hidden');
      }
    });

    return {
      fetch: fetchPlaces,
      setFilter: (filterType) => {
        activeFilter = filterType;
      },
      resetFilter: (newDefault = defaultFilter) => {
        activeFilter = newDefault;
      },
      getFilter: () => activeFilter,
      hide: () => {
        suggestionsEl.classList.add('hidden');
      },
      clear: () => {
        suggestionsEl.innerHTML = '';
        suggestionsEl.classList.add('hidden');
        inputEl.value = '';
      },
    };
  }

  /**
   * Binds PlaceAutocomplete together with hidden type/id/name inputs,
   * search text input, selected preview chip container, and clear button.
   *
   * @param {Object} options
   * @param {HTMLElement} options.searchInput
   * @param {HTMLElement} options.suggestionsContainer
   * @param {HTMLElement} options.typeInput
   * @param {HTMLElement} options.idInput
   * @param {HTMLElement} options.nameInput
   * @param {HTMLElement} options.previewContainer
   * @param {HTMLElement} options.previewIcon
   * @param {HTMLElement} options.previewName
   * @param {HTMLElement} options.previewId
   * @param {HTMLElement} options.clearBtn
   * @param {string} [options.defaultFilter='all']
   * @param {Function} [options.onSelect]
   * @param {Function} [options.onClear]
   * @returns {Object} { setSelection, clearSelection, getSelection, autocomplete }
   */
  function bindSelection(options) {
    const {
      searchInput,
      suggestionsContainer,
      typeInput,
      idInput,
      nameInput,
      previewContainer,
      previewIcon,
      previewName,
      previewId,
      clearBtn,
      defaultFilter = 'all',
      onSelect = null,
      onClear = null,
    } = options || {};

    let currentItem = null;

    function setSelection(item) {
      currentItem = item || null;
      if (!item || (!item.id && !item.name)) {
        clearSelection();
        return;
      }

      if (typeInput) typeInput.value = item.type || '';
      if (idInput) idInput.value = item.id || '';
      if (nameInput) nameInput.value = item.name || '';

      if (previewIcon) {
        previewIcon.textContent = getIcon(item.type);
      }
      if (previewName) {
        previewName.textContent = item.name || '';
      }
      if (previewId) {
        previewId.textContent = item.id ? `(${item.id})` : '';
      }

      if (previewContainer) previewContainer.classList.remove('hidden');
      if (searchInput) {
        searchInput.value = '';
        searchInput.classList.add('hidden');
      }
      if (suggestionsContainer) suggestionsContainer.classList.add('hidden');

      if (typeof onSelect === 'function') {
        onSelect(item);
      }
    }

    function clearSelection() {
      currentItem = null;
      if (typeInput) typeInput.value = '';
      if (idInput) idInput.value = '';
      if (nameInput) nameInput.value = '';

      if (previewContainer) previewContainer.classList.add('hidden');
      if (searchInput) {
        searchInput.classList.remove('hidden');
        searchInput.value = '';
      }
      if (suggestionsContainer) suggestionsContainer.classList.add('hidden');

      if (typeof onClear === 'function') {
        onClear();
      }
    }

    const autocomplete = create({
      inputEl: searchInput,
      suggestionsEl: suggestionsContainer,
      defaultFilter,
      onSelect: (item) => {
        setSelection(item);
      },
    });

    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        clearSelection();
        if (searchInput) searchInput.focus();
      });
    }

    return {
      setSelection,
      clearSelection,
      getSelection: () => currentItem,
      autocomplete,
    };
  }

  return {
    create,
    bindSelection,
    FILTERS: PLACE_TYPE_FILTERS,
    getIcon,
    getBadge,
    escapeHtml,
  };
})();
