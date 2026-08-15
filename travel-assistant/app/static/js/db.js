/**
 * Database Storage & Dataset Refresh View Controller.
 * Manages Grid.js data table rendering for schema tables,
 * on-demand asynchronous dataset refresh requests, metric updates,
 * and top-level alert notifications.
 */
document.addEventListener('DOMContentLoaded', () => {
  const container = document.getElementById('db-stats-container');
  if (!container) return;

  const dataEl = document.getElementById('initial-db-stats');
  let currentStats = null;
  try {
    currentStats = dataEl ? JSON.parse(dataEl.textContent || '{}') : {};
  } catch (e) {
    console.error('Failed to parse initial database stats:', e);
  }

  const gridContainer = document.getElementById('db-grid-wrapper');
  const emptyState = document.getElementById('grid-empty-state');
  const ingressPath = container.dataset.ingressPath || '';
  const toastBox = document.getElementById('sync-toast-box');
  const syncAllBtn = document.getElementById('sync-all-btn');
  const syncAllIcon = document.getElementById('sync-all-icon');
  const syncAllText = document.getElementById('sync-all-text');

  let stagedTables = (currentStats && Array.isArray(currentStats.tables)) ? currentStats.tables : [];

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function getTableIcon(name) {
    switch (name) {
      case 'bus_routes': return 'alt_route';
      case 'bus_stops': return 'directions_bus';
      case 'stations': return 'train';
      case 'sync_metadata': return 'sync';
      case 'timetables': return 'schedule';
      case 'settings': return 'tune';
      default: return 'table_rows';
    }
  }

  function formatGridData(tables) {
    return tables.map((tbl) => {
      const icon = getTableIcon(tbl.name);
      const rowCountFormatted = Number(tbl.row_count || 0).toLocaleString();

      let statusBadge = '';
      if (tbl.sync_status === 'success') {
        statusBadge = `
          <span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300 dark:ring-1 dark:ring-emerald-500/30">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> Refreshed
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
          <span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 dark:bg-rose-950/80 dark:text-rose-300 dark:ring-1 dark:ring-rose-500/30" title="${escapeHtml(tbl.error_message || 'Refresh error')}">
            <span class="w-1.5 h-1.5 rounded-full bg-rose-500"></span> Error
          </span>
        `;
      } else {
        statusBadge = `
          <span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400">
            <span class="w-1.5 h-1.5 rounded-full bg-slate-400"></span> Managed
          </span>
        `;
      }

      const lastUpdatedHtml = tbl.last_updated_at
        ? `<div class="font-medium text-slate-700 dark:text-slate-300 text-xs">${escapeHtml(tbl.last_updated_at)}</div>`
        : `<div class="text-slate-400 dark:text-slate-500 italic text-xs">Never / Not updated</div>`;

      let actionHtml = `<span class="text-xs text-slate-400 dark:text-slate-500 italic">Static</span>`;
      if (tbl.syncable) {
        actionHtml = `
          <button 
            type="button" 
            class="row-refresh-btn inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 hover:text-sky-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700 dark:hover:text-sky-400 transition-colors shadow-xs cursor-pointer"
            data-table="${escapeHtml(tbl.name)}"
            title="Refresh ${escapeHtml(tbl.name)} dataset"
          >
            <span class="material-symbols-outlined text-xs leading-none" id="sync-icon-${escapeHtml(tbl.name)}">refresh</span>
            <span>Refresh</span>
          </button>
        `;
      }

      return [
        gridjs.html(`
          <div class="flex items-center gap-2">
            <span class="material-symbols-outlined text-base text-slate-400 dark:text-slate-500 leading-none">${icon}</span>
            <code class="font-mono text-xs font-semibold text-slate-900 dark:text-slate-100">${escapeHtml(tbl.name)}</code>
          </div>
        `),
        gridjs.html(`
          <div class="space-y-1">
            ${lastUpdatedHtml}
            <div>${statusBadge}</div>
          </div>
        `),
        gridjs.html(`
          <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-sky-50 text-sky-700 dark:bg-sky-950/60 dark:text-sky-300 border border-sky-200/60 dark:border-sky-800/40">
            ${rowCountFormatted}
          </span>
        `),
        gridjs.html(actionHtml),
      ];
    });
  }

  // Initialise Grid.js instance
  const grid = new gridjs.Grid({
    columns: [
      { name: 'Table Name', width: '220px' },
      { name: 'Last Updated', width: '240px' },
      { name: 'Row Count', width: '130px' },
      { name: 'Actions', width: '120px', sort: false },
    ],
    data: formatGridData(stagedTables),
    search: {
      placeholder: 'Search database tables...',
    },
    sort: true,
    pagination: {
      limit: 8,
      summary: true,
    },
    language: {
      search: {
        placeholder: 'Search database tables...',
      },
      pagination: {
        previous: 'Previous',
        next: 'Next',
        showing: 'Showing',
        results: () => 'tables',
      },
    },
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
      data: formatGridData(stagedTables),
    }).forceRender();
  }

  syncGridDisplay();

  function updateMetrics(stats) {
    if (!stats) return;

    if (stats.file_size_formatted) {
      const sizeEl = document.getElementById('stat-db-size');
      if (sizeEl) sizeEl.textContent = stats.file_size_formatted;
      const sizeBytesEl = document.getElementById('stat-db-size-bytes');
      if (sizeBytesEl && stats.file_size_bytes !== undefined) {
        sizeBytesEl.textContent = `${Number(stats.file_size_bytes).toLocaleString()} bytes`;
      }
    }
    if (stats.total_tables !== undefined) {
      const tablesEl = document.getElementById('stat-total-tables');
      if (tablesEl) tablesEl.textContent = stats.total_tables;
    }
    if (stats.total_rows !== undefined) {
      const totalEl = document.getElementById('stat-total-rows');
      if (totalEl) totalEl.textContent = Number(stats.total_rows).toLocaleString();
    }

    if (Array.isArray(stats.tables)) {
      stagedTables = stats.tables;
      syncGridDisplay();
    }
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
    const isAll = tableName === 'all';
    const rowBtn = isAll ? null : document.querySelector(`.row-refresh-btn[data-table="${tableName}"]`);
    const rowIcon = rowBtn ? rowBtn.querySelector('.material-symbols-outlined') : null;

    if (isAll) {
      if (syncAllBtn) syncAllBtn.disabled = true;
      if (syncAllIcon) syncAllIcon.classList.add('animate-spin');
      if (syncAllText) syncAllText.textContent = 'Refreshing All...';
    } else {
      if (rowBtn) rowBtn.disabled = true;
      if (rowIcon) rowIcon.classList.add('animate-spin');
      // Set table in staged state to syncing
      const tblObj = stagedTables.find(t => t.name === tableName);
      if (tblObj) {
        tblObj.sync_status = 'syncing';
        grid.updateConfig({ data: formatGridData(stagedTables) }).forceRender();
      }
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

      if (isAll) {
        showToast('success', '<strong>Dataset refresh complete:</strong> Updated all transit datasets.');
      } else if (data.status === 'success') {
        showToast('success', `<strong>Success (${escapeHtml(tableName)}):</strong> ${escapeHtml(data.message || 'Dataset refreshed successfully.')}`);
      } else if (data.status === 'skipped_no_credentials') {
        showToast('warning', `<strong>Notice (${escapeHtml(tableName)}):</strong> ${escapeHtml(data.message || 'Skipped because API credentials are not configured.')}`);
      } else {
        showToast('error', `<strong>Error (${escapeHtml(tableName)}):</strong> ${escapeHtml(data.message || 'Failed to refresh dataset.')}`);
      }

      if (data.stats) {
        updateMetrics(data.stats);
      }
    } catch (err) {
      showToast('error', `<strong>Request Failed:</strong> ${escapeHtml(err.message || 'Could not trigger dataset refresh.')}`);
    } finally {
      if (isAll) {
        if (syncAllBtn) syncAllBtn.disabled = false;
        if (syncAllIcon) syncAllIcon.classList.remove('animate-spin');
        if (syncAllText) syncAllText.textContent = 'Refresh All Datasets';
      } else {
        if (rowBtn) rowBtn.disabled = false;
        if (rowIcon) rowIcon.classList.remove('animate-spin');
      }
    }
  }

  // Bind Sync All button
  if (syncAllBtn) {
    syncAllBtn.addEventListener('click', () => triggerRefresh('all'));
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
