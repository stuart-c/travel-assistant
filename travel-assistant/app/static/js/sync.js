/**
 * Background Sync View Controller.
 * Manages Grid.js data table rendering for transit datasets (bus_routes, bus_stops, stations),
 * on-demand asynchronous dataset refresh requests, and notification alerts.
 */
document.addEventListener('DOMContentLoaded', () => {
  const container = document.getElementById('sync-page-container');
  if (!container) return;

  const dataEl = document.getElementById('initial-sync-stats');
  let currentStats = null;
  try {
    currentStats = dataEl ? JSON.parse(dataEl.textContent || '{}') : {};
  } catch (e) {
    console.error('Failed to parse initial sync stats:', e);
  }

  const gridContainer = document.getElementById('sync-grid-wrapper');
  const emptyState = document.getElementById('grid-empty-state');
  const ingressPath = container.dataset.ingressPath || '';
  const toastBox = document.getElementById('sync-toast-box');
  const syncAllBtn = document.getElementById('sync-all-btn');
  const syncAllIcon = document.getElementById('sync-all-icon');
  const syncAllText = document.getElementById('sync-all-text');

  const SYNCABLE_NAMES = ['bus_routes', 'stops', 'ha_locations', 'locations'];

  function extractSyncableTables(stats) {
    const allTables = (stats && Array.isArray(stats.tables)) ? stats.tables : [];
    return allTables.filter(t => t.syncable || SYNCABLE_NAMES.includes(t.name));
  }

  let stagedTables = extractSyncableTables(currentStats);

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function parseDate(isoString) {
    if (!isoString) return null;
    const str = String(isoString).trim();
    if (!str) return null;
    const hasTimezone = str.endsWith('Z') || /[+-]\d{2}(:\d{2})?$/.test(str);
    const normalized = hasTimezone ? str : `${str}Z`;
    const d = new Date(normalized);
    return isNaN(d.getTime()) ? null : d;
  }

  function formatRelativeTime(isoString) {
    const date = parseDate(isoString);
    if (!date) return 'Never updated';

    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffSec = Math.floor(diffMs / 1000);

    if (diffSec < 0 || diffSec < 45) {
      return 'Just now';
    }
    if (diffSec < 90) {
      return '1 minute ago';
    }
    const diffMins = Math.round(diffSec / 60);
    if (diffMins < 45) {
      return `${diffMins} minutes ago`;
    }
    if (diffSec < 90 * 60) {
      return '1 hour ago';
    }
    const diffHours = Math.round(diffSec / 3600);
    if (diffHours < 22) {
      return `${diffHours} hours ago`;
    }
    if (diffSec < 36 * 3600) {
      return 'Yesterday';
    }
    const diffDays = Math.round(diffSec / 86400);
    if (diffDays < 25) {
      return `${diffDays} days ago`;
    }
    if (diffDays < 45) {
      return '1 month ago';
    }
    const diffMonths = Math.round(diffDays / 30);
    if (diffDays < 345) {
      return `${diffMonths} months ago`;
    }
    if (diffDays < 545) {
      return '1 year ago';
    }
    const diffYears = Math.round(diffDays / 365);
    return `${diffYears} years ago`;
  }

  function formatExactTime(isoString) {
    const date = parseDate(isoString);
    if (!date) return '';

    return new Intl.DateTimeFormat('en-GB', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }).format(date);
  }

  function getDatasetIcon(name) {
    switch (name) {
      case 'bus_routes': return 'alt_route';
      case 'stops': return 'directions_transit';
      case 'ha_locations': return 'pin_drop';
      case 'locations': return 'pin_drop';
      default: return 'sync';
    }
  }

  function getDatasetDisplayName(name) {
    switch (name) {
      case 'bus_routes': return 'Bus Routes';
      case 'stops': return 'Transit Stops (NaPTAN)';
      case 'ha_locations': return 'Home Assistant Locations';
      case 'locations': return 'Home Assistant Locations';
      default: return name;
    }
  }

  function formatGridData(tables) {
    return tables.map((tbl) => {
      const icon = getDatasetIcon(tbl.name);
      const displayName = getDatasetDisplayName(tbl.name);

      let statusBadge = '';
      if (tbl.sync_status === 'success') {
        statusBadge = `
          <span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300 dark:ring-1 dark:ring-emerald-500/30">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> Updated
          </span>
        `;
      } else if (tbl.sync_status === 'syncing') {
        statusBadge = `
          <span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-300 dark:ring-1 dark:ring-amber-500/30">
            <span class="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse"></span> Refreshing...
          </span>
        `;
      } else if (tbl.sync_status === 'skipped_no_credentials') {
        statusBadge = `
          <span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300" title="${escapeHtml(tbl.error_message || 'Credentials unconfigured')}">
            <span class="w-1.5 h-1.5 rounded-full bg-slate-400"></span> Unconfigured
          </span>
        `;
      } else if (tbl.sync_status === 'error') {
        statusBadge = `
          <span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 dark:bg-rose-950/80 dark:text-rose-300 dark:ring-1 dark:ring-rose-500/30" title="${escapeHtml(tbl.error_message || 'Sync error')}">
            <span class="w-1.5 h-1.5 rounded-full bg-rose-500"></span> Error
          </span>
        `;
      } else {
        statusBadge = `
          <span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400">
            <span class="w-1.5 h-1.5 rounded-full bg-slate-400"></span> Idle
          </span>
        `;
      }

      const relativeTime = formatRelativeTime(tbl.last_updated_at);
      const exactTime = formatExactTime(tbl.last_updated_at);
      const isNever = !tbl.last_updated_at || relativeTime === 'Never updated';

      const lastUpdatedHtml = isNever
        ? `<div class="text-slate-400 dark:text-slate-500 italic text-xs">Never updated</div>`
        : `<div class="font-medium text-slate-700 dark:text-slate-300 text-xs cursor-help" title="${escapeHtml(exactTime)}">${escapeHtml(relativeTime)}</div>`;

      const actionHtml = `
        <button 
          type="button" 
          class="row-refresh-btn inline-flex items-center justify-center w-7 h-7 rounded-lg bg-sky-50 text-sky-600 hover:bg-sky-100 hover:text-sky-700 dark:bg-sky-950/50 dark:text-sky-400 dark:hover:bg-sky-900/60 transition-colors cursor-pointer"
          data-table="${escapeHtml(tbl.name)}"
          title="Refresh ${escapeHtml(displayName)} dataset now"
          aria-label="Refresh ${escapeHtml(displayName)} dataset now"
        >
          <span class="material-symbols-outlined text-[17px] leading-none" id="sync-icon-${escapeHtml(tbl.name)}">refresh</span>
        </button>
      `;

      return [
        gridjs.html(`
          <div class="flex items-center gap-2.5">
            <span class="material-symbols-outlined text-base text-slate-400 dark:text-slate-500 leading-none">${icon}</span>
            <span class="font-medium text-sm text-slate-900 dark:text-slate-100">${escapeHtml(displayName)}</span>
          </div>
        `),
        gridjs.html(lastUpdatedHtml),
        gridjs.html(statusBadge),
        gridjs.html(actionHtml),
      ];
    });
  }

  const columnsConfig = [
    { name: 'Dataset', width: 'auto', sort: true },
    { name: 'Last updated', width: '180px', sort: true },
    { name: 'Status', width: '160px', sort: true },
    { name: 'Actions', width: '90px', sort: false },
  ];

  // Initialise Grid.js instance
  const grid = new gridjs.Grid({
    columns: columnsConfig,
    data: formatGridData(stagedTables),
    sort: true,
    search: false,
    pagination: false,
  }).render(gridContainer);

  function syncGridDisplay() {
    if (stagedTables.length === 0) {
      gridContainer.classList.add('hidden');
      if (emptyState) emptyState.classList.remove('hidden');
    } else {
      gridContainer.classList.remove('hidden');
      if (emptyState) emptyState.classList.add('hidden');
    }

    grid.updateConfig({
      columns: columnsConfig,
      data: formatGridData(stagedTables),
    }).forceRender();
  }

  syncGridDisplay();

  // Periodic interval to refresh relative timestamp displays every 30 seconds
  setInterval(() => {
    if (stagedTables.length > 0) {
      syncGridDisplay();
    }
  }, 30000);

  function updateMetrics(stats) {
    if (!stats) return;
    stagedTables = extractSyncableTables(stats);
    syncGridDisplay();
  }

  function showToast(category, htmlContent) {
    if (!toastBox) return;

    toastBox.className = 'mb-6 p-4 rounded-xl text-sm font-medium border flex items-center gap-3 transition-all';
    let iconChar = 'ℹ';
    if (category === 'success') {
      toastBox.className += ' bg-emerald-50 text-emerald-900 border-emerald-200 dark:bg-emerald-950/60 dark:text-emerald-200 dark:border-emerald-800/50';
      iconChar = '✓';
    } else if (category === 'warning') {
      toastBox.className += ' bg-amber-50 text-amber-900 border-amber-200 dark:bg-amber-950/60 dark:text-amber-200 dark:border-amber-800/50';
      iconChar = '⚠';
    } else {
      toastBox.className += ' bg-rose-50 text-rose-900 border-rose-200 dark:bg-rose-950/60 dark:text-rose-200 dark:border-rose-800/50';
      iconChar = '✗';
    }

    toastBox.innerHTML = `
      <span class="font-bold text-base leading-none">${iconChar}</span>
      <div class="flex-1">${htmlContent}</div>
    `;
    toastBox.classList.remove('hidden');
  }

  async function triggerRefresh(tableName) {
    const rowBtn = document.querySelector(`.row-refresh-btn[data-table="${tableName}"]`);
    const rowIcon = rowBtn ? rowBtn.querySelector('.material-symbols-outlined') : null;

    if (rowBtn) rowBtn.disabled = true;
    if (rowIcon) rowIcon.classList.add('animate-spin');
    const tblObj = stagedTables.find(t => t.name === tableName);
    if (tblObj) {
      tblObj.sync_status = 'syncing';
      grid.updateConfig({ data: formatGridData(stagedTables) }).forceRender();
    }

    try {
      const targetUrl = `${ingressPath}/config/db/sync/${tableName}`;
      const response = await fetch(targetUrl, {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
        },
      });

      const data = await response.json();

      if (data.status === 'success') {
        showToast('success', `<strong>Success (${escapeHtml(getDatasetDisplayName(tableName))}):</strong> ${escapeHtml(data.message || 'Dataset synchronised successfully.')}`);
      } else if (data.status === 'skipped_no_credentials') {
        showToast('warning', `<strong>Notice (${escapeHtml(getDatasetDisplayName(tableName))}):</strong> ${escapeHtml(data.message || 'Skipped because API credentials are not configured.')}`);
      } else {
        showToast('error', `<strong>Error (${escapeHtml(getDatasetDisplayName(tableName))}):</strong> ${escapeHtml(data.message || 'Failed to synchronise dataset.')}`);
      }

      if (data.stats) {
        updateMetrics(data.stats);
      }
    } catch (err) {
      showToast('error', `<strong>Request Failed:</strong> ${escapeHtml(err.message || 'Could not trigger dataset synchronisation.')}`);
    } finally {
      if (rowBtn) rowBtn.disabled = false;
      if (rowIcon) rowIcon.classList.remove('animate-spin');
    }
  }

  // Delegate click for row refresh buttons
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.row-refresh-btn');
    if (btn) {
      const tblName = btn.getAttribute('data-table');
      if (tblName) {
        triggerRefresh(tblName);
      }
    }
  });

  window.triggerSync = triggerRefresh;
});
