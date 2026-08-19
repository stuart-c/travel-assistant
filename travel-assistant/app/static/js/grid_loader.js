/**
 * Grid Loader Utility.
 *
 * Provides shared loading-state, error-state, and async fetch helpers used by
 * all Grid.js config page controllers (journeys, locations, timetables,
 * transfers, walking, db, sync).
 *
 * Exposed as: window.GridLoader
 *
 * Usage:
 *   GridLoader.load(dataUrl, containerEl, {
 *     label: 'locations',         // Human-readable label for status messages
 *     emptyState: emptyStateEl,   // Optional — hidden while loading/on error
 *     onSuccess(json) {           // Called with parsed response on success
 *       stagedLocations = json.data;
 *       grid.render(containerEl);
 *       syncState();
 *     },
 *   });
 */
(function () {
  'use strict';

  /**
   * Render a loading spinner inside a grid container element.
   * @param {HTMLElement} container - The grid wrapper element.
   * @param {string} label - Human-readable label, e.g. "locations".
   */
  function showLoading(container, label) {
    if (!container) return;
    container.innerHTML = `
      <div class="flex flex-col items-center justify-center py-12 text-slate-400 dark:text-slate-500 gap-3">
        <span class="material-symbols-outlined animate-spin text-3xl">progress_activity</span>
        <span class="text-sm">Loading ${label}&hellip;</span>
      </div>`;
    container.classList.remove('hidden');
  }

  /**
   * Render an in-grid error state with a Retry button.
   * @param {HTMLElement} container - The grid wrapper element.
   * @param {string} label - Human-readable label, e.g. "locations".
   * @param {Function} retryFn - Invoked when the Retry button is clicked.
   */
  function showError(container, label, retryFn) {
    if (!container) return;
    // Use a unique id to avoid collisions when multiple grids are on the page
    const btnId = `gl-retry-${Math.random().toString(36).slice(2, 9)}`;
    container.innerHTML = `
      <div class="flex flex-col items-center justify-center py-12 text-rose-500 dark:text-rose-400 gap-3">
        <span class="material-symbols-outlined text-3xl">error</span>
        <span class="text-sm font-medium">Failed to load ${label}.</span>
        <button id="${btnId}" type="button"
          class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-semibold
                 bg-sky-600 hover:bg-sky-500 text-white shadow-xs transition-colors cursor-pointer">
          <span class="material-symbols-outlined text-base leading-none">refresh</span>
          Retry
        </button>
      </div>`;
    container.classList.remove('hidden');
    const retryBtn = document.getElementById(btnId);
    if (retryBtn && typeof retryFn === 'function') {
      retryBtn.addEventListener('click', retryFn);
    }
  }

  /**
   * Fetch JSON data from a URL with automatic loading/error UI management.
   *
   * Shows a loading spinner immediately, fetches the endpoint, and on success
   * clears the container and calls onSuccess(json). On failure, shows an
   * in-grid error state with a Retry button that re-attempts the fetch.
   *
   * @param {string} url - The data endpoint URL.
   * @param {HTMLElement} container - The grid wrapper element.
   * @param {Object} options
   * @param {string} options.label - Human-readable label for status messages.
   * @param {HTMLElement} [options.emptyState] - Optional empty-state element;
   *   hidden while loading and on error so it does not overlap the status UI.
   * @param {Function} options.onSuccess - Called with the parsed JSON object on
   *   a successful fetch. Responsible for seeding staged data and rendering the
   *   grid.
   * @returns {Promise<void>}
   */
  async function load(url, container, { label, emptyState, onSuccess }) {
    showLoading(container, label);
    if (emptyState) emptyState.classList.add('hidden');

    async function attempt() {
      try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const json = await resp.json();
        // Clear loading spinner before handing control to onSuccess
        if (container) container.innerHTML = '';
        onSuccess(json);
      } catch (err) {
        console.error(`GridLoader: failed to load ${label}:`, err);
        showError(container, label, attempt);
        if (emptyState) emptyState.classList.add('hidden');
      }
    }

    await attempt();
  }

  window.GridLoader = { showLoading, showError, load };
})();
