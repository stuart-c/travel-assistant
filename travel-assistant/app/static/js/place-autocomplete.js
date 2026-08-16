/**
 * PlaceAutocomplete Component for Travel Assistant.
 * Provides unified place & transit search autocomplete dropdowns with pinned filter chips.
 */
window.PlaceAutocomplete = (function () {
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

  const TYPE_META = {
    rail: {
      label: 'Train',
      icon: 'train',
      bg: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300',
    },
    bus: {
      label: 'Bus',
      icon: 'directions_bus',
      bg: 'bg-amber-50 text-amber-700 dark:bg-amber-950/60 dark:text-amber-300',
    },
    metro: {
      label: 'Metro',
      icon: 'subway',
      bg: 'bg-indigo-50 text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300',
    },
    tram: {
      label: 'Tram',
      icon: 'tram',
      bg: 'bg-purple-50 text-purple-700 dark:bg-purple-950/60 dark:text-purple-300',
    },
    ferry: {
      label: 'Ferry',
      icon: 'directions_boat',
      bg: 'bg-cyan-50 text-cyan-700 dark:bg-cyan-950/60 dark:text-cyan-300',
    },
    air: {
      label: 'Air',
      icon: 'flight',
      bg: 'bg-sky-50 text-sky-700 dark:bg-sky-950/60 dark:text-sky-300',
    },
    ha: {
      label: 'HA Zone',
      icon: 'home',
      bg: 'bg-rose-50 text-rose-700 dark:bg-rose-950/60 dark:text-rose-300',
    },
    custom: {
      label: 'Custom',
      icon: 'pin_drop',
      bg: 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-300',
    },
  };

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
    return (TYPE_META[type] && TYPE_META[type].icon) || 'place';
  }

  function getBadge(type) {
    const meta = TYPE_META[type] || {
      label: type || 'Place',
      bg: 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-300',
    };
    return `<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold ${meta.bg}">${escapeHtml(
      meta.label
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
      const typeParam = activeFilter === 'all' ? '' : activeFilter;
      const baseUrl = getEffectiveSearchUrl();
      const url = `${baseUrl}?type=${encodeURIComponent(
        typeParam
      )}&q=${encodeURIComponent(q)}&limit=${limit}`;

      try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error('Search failed');
        const data = await resp.json();
        currentResults = data.results || [];
        renderDropdown(currentResults);
      } catch (err) {
        console.error('Place search error:', err);
      }
    }

    function renderDropdown(items) {
      const filterBarHtml = `
        <div class="place-filter-bar p-1.5 border-b border-slate-100 dark:border-slate-700/60 bg-slate-50/90 dark:bg-slate-800/90 sticky top-0 z-10 backdrop-blur-xs">
          <div class="flex items-center gap-1 overflow-x-auto no-scrollbar py-0.5">
            ${PLACE_TYPE_FILTERS.map((f) => {
              const isActive = f.type === activeFilter;
              const activeClass = isActive
                ? 'bg-sky-600 text-white font-semibold shadow-xs dark:bg-sky-500'
                : 'bg-white dark:bg-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-600 border border-slate-200 dark:border-slate-600/80';
              return `
                <button
                  type="button"
                  class="filter-chip px-2 py-0.5 rounded-md text-[11px] flex items-center gap-1 shrink-0 cursor-pointer transition-all duration-150 select-none ${activeClass}"
                  data-filter-type="${f.type}"
                >
                  <span class="material-symbols-outlined text-[13px] leading-none">${f.icon}</span>
                  <span>${f.label}</span>
                </button>
              `;
            }).join('')}
          </div>
        </div>
      `;

      let listHtml = '';
      if (!items || items.length === 0) {
        const filterObj = PLACE_TYPE_FILTERS.find(
          (f) => f.type === activeFilter
        );
        const filterLabel = filterObj ? filterObj.label : activeFilter;
        const defaultMsg = `No matching ${escapeHtml(
          filterLabel === 'All' ? 'places' : filterLabel + ' locations'
        )} found.`;
        listHtml = `
          <div class="px-3.5 py-4 text-xs text-slate-500 dark:text-slate-400 text-center">
            ${emptyText ? escapeHtml(emptyText) : defaultMsg}
          </div>
        `;
      } else {
        listHtml = `
          <div class="place-results-list divide-y divide-slate-100 dark:divide-slate-700/50">
            ${items
              .map((item, idx) => {
                const icon = item.icon || getIcon(item.type);
                const badge = getBadge(item.type);
                return `
                <div 
                  class="suggestion-item px-3.5 py-2.5 hover:bg-sky-50 dark:hover:bg-slate-700/60 cursor-pointer flex items-center justify-between gap-3 transition-colors"
                  data-index="${idx}"
                >
                  <div class="flex items-center gap-2.5 min-w-0">
                    <span class="material-symbols-outlined text-slate-400 dark:text-slate-500 text-base shrink-0">${escapeHtml(
                      icon
                    )}</span>
                    <div class="truncate min-w-0">
                      <div class="text-xs font-semibold text-slate-900 dark:text-slate-100 truncate">${escapeHtml(
                        item.name
                      )}</div>
                      <div class="text-[11px] text-slate-500 dark:text-slate-400 truncate">${escapeHtml(
                        item.description || item.indicator || item.id
                      )}</div>
                    </div>
                  </div>
                  <div class="flex items-center gap-1.5 shrink-0">
                    ${badge}
                    ${
                      item.id
                        ? `<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-mono bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300">${escapeHtml(
                            item.id
                          )}</span>`
                        : ''
                    }
                  </div>
                </div>
              `;
              })
              .join('')}
          </div>
        `;
      }

      suggestionsEl.innerHTML = filterBarHtml + listHtml;
      suggestionsEl.classList.remove('hidden');

      // Bind filter chip clicks
      suggestionsEl.querySelectorAll('.filter-chip').forEach((chipBtn) => {
        chipBtn.addEventListener('mousedown', (e) => {
          e.preventDefault();
        });
        chipBtn.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          const newType = chipBtn.getAttribute('data-filter-type');
          if (newType !== activeFilter) {
            activeFilter = newType;
            fetchPlaces();
          }
          inputEl.focus();
        });
      });

      // Bind suggestion item clicks
      suggestionsEl.querySelectorAll('.suggestion-item').forEach((el) => {
        el.addEventListener('click', () => {
          const idx = parseInt(el.getAttribute('data-index'), 10);
          const selectedItem = items[idx];
          if (selectedItem && typeof onSelect === 'function') {
            onSelect(selectedItem);
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

  return {
    create,
    FILTERS: PLACE_TYPE_FILTERS,
    getIcon,
    getBadge,
    escapeHtml,
  };
})();
