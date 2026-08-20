/**
 * Background Sync View Controller.
 * Manages Grid.js data table rendering for transit datasets,
 * on-demand asynchronous dataset refresh requests, and notification alerts.
 */
document.addEventListener('DOMContentLoaded', () => {
  const container = document.getElementById('sync-page-container');
  if (!container) return;

  const gridContainer = document.getElementById('sync-grid-wrapper');
  const emptyState = document.getElementById('grid-empty-state');
  const ingressPath = container.dataset.ingressPath || '';
  const toastBox = document.getElementById('sync-toast-box');
  const syncAllBtn = document.getElementById('sync-all-btn');
  const syncAllIcon = document.getElementById('sync-all-icon');
  const syncAllText = document.getElementById('sync-all-text');

  const dataUrl = (gridContainer && gridContainer.getAttribute('data-data-url')) || '/config/sync/data';

  const SYNCABLE_NAMES = ['bus_routes', 'stops', 'ha_locations', 'locations', 'train_timetables', 'bus_timetables', 'walking'];

  function extractSyncableTables(tablesList) {
    return (Array.isArray(tablesList) ? tablesList : []).filter(t => t.syncable || SYNCABLE_NAMES.includes(t.name));
  }

  let stagedTables = [];

  const escapeHtml = (window.TransitUI && window.TransitUI.escapeHtml) || ((str) => (str ? String(str) : ''));
  const formatRelativeTime = (window.TransitUI && window.TransitUI.formatRelativeTime) || ((str) => str || 'Never updated');
  const formatExactTime = (window.TransitUI && window.TransitUI.formatExactTime) || ((str) => str || '');


  function getDatasetIcon(name) {
    switch (name) {
      case 'bus_routes': return 'alt_route';
      case 'stops': return 'directions_transit';
      case 'ha_locations': return 'pin_drop';
      case 'locations': return 'pin_drop';
      case 'train_timetables': return 'train';
      case 'bus_timetables': return 'directions_bus';
      case 'walking': return 'directions_walk';
      default: return 'sync';
    }
  }

  function getDatasetDisplayName(name) {
    switch (name) {
      case 'bus_routes': return 'Bus Routes';
      case 'stops': return 'Transit Stops (NaPTAN)';
      case 'ha_locations': return 'Home Assistant Locations';
      case 'locations': return 'Home Assistant Locations';
      case 'train_timetables': return 'Train Timetables (Darwin S3)';
      case 'bus_timetables': return 'Bus Timetables (BODS)';
      case 'walking': return 'Walking Connections';
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



  // Initialise Grid.js instance (renders after loadData populates stagedTables)
  const grid = new gridjs.Grid({
    columns: columnsConfig,
    data: formatGridData(stagedTables),
    sort: true,
    search: false,
    pagination: false,
  });

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

  // Fetch remote data then render — loading/error UI managed by GridLoader
  GridLoader.load(dataUrl, gridContainer, {
    label: 'sync status',
    emptyState,
    onSuccess(json) {
      stagedTables = extractSyncableTables(Array.isArray(json.data) ? json.data : []);
      grid.render(gridContainer);
      syncGridDisplay();
    },
  });

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
    if (window.TransitUI && window.TransitUI.showNotification) {
      window.TransitUI.showNotification(toastBox, htmlContent, category, { isHtml: true });
      return;
    }
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
