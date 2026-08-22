/**
 * Database Storage View Controller.
 * Manages Grid.js data table rendering for SQLite database tables and row counts,
 * on-demand manual refresh requests, and automated background refresh every minute.
 */
document.addEventListener('DOMContentLoaded', () => {
  const gridContainer = document.getElementById('db-grid-wrapper');
  if (!gridContainer) return;

  const dataUrl = gridContainer.getAttribute('data-data-url') || '/config/db/data';
  const refreshBtn = document.getElementById('refresh-db-btn');
  const refreshIcon = document.getElementById('refresh-db-icon');
  const dbSizeEl = document.getElementById('stat-db-size');

  let gridInstance = null;
  let tables = [];

  const escapeHtml =
    (window.TransitUI && window.TransitUI.escapeHtml) ||
    ((str) => (str ? String(str) : ''));

  function formatDbGridData(tableList) {
    return tableList.map((tbl) => {
      const rowCountFormatted = Number(tbl.row_count || 0).toLocaleString();

      return [
        gridjs.html(`
          <div class="flex items-center">
            <code class="font-mono text-xs font-semibold text-slate-800 dark:text-slate-200 bg-slate-100 dark:bg-slate-800/80 px-2 py-0.5 rounded-md border border-slate-200/80 dark:border-slate-700">
              ${escapeHtml(tbl.name)}
            </code>
          </div>
        `),
        gridjs.html(`
          <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-sky-50 text-sky-700 dark:bg-sky-950/60 dark:text-sky-300 border border-sky-200/60 dark:border-sky-800/40 font-mono">
            ${rowCountFormatted}
          </span>
        `),
      ];
    });
  }

  function updateDbMetrics(json) {
    if (!json || !dbSizeEl) return;
    if (json.file_size_formatted) {
      dbSizeEl.textContent = json.file_size_formatted;
    }
    if (json.file_size_bytes !== undefined) {
      dbSizeEl.title = `${Number(json.file_size_bytes).toLocaleString()} bytes`;
    }
  }

  async function refreshDbData(isManual = false) {
    if (isManual) {
      if (refreshBtn) refreshBtn.disabled = true;
      if (refreshIcon) refreshIcon.classList.add('animate-spin');
    }

    try {
      const response = await fetch(dataUrl, {
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const json = await response.json();

      tables = Array.isArray(json.data) ? json.data : [];
      updateDbMetrics(json);

      if (gridInstance) {
        gridInstance.updateConfig({ data: formatDbGridData(tables) }).forceRender();
      }
    } catch (err) {
      console.error('Failed to refresh database statistics:', err);
    } finally {
      if (isManual) {
        if (refreshBtn) refreshBtn.disabled = false;
        if (refreshIcon) refreshIcon.classList.remove('animate-spin');
      }
    }
  }

  // Fetch remote data then render — loading/error UI managed by GridLoader
  GridLoader.load(dataUrl, gridContainer, {
    label: 'database statistics',
    onSuccess(json) {
      tables = Array.isArray(json.data) ? json.data : [];
      updateDbMetrics(json);
      gridInstance = new gridjs.Grid({
        columns: [
          { name: 'Table Name', width: '65%' },
          { name: 'Rows', width: '35%' },
        ],
        data: formatDbGridData(tables),
        search: false,
        pagination: false,
        sort: true,
      });
      gridInstance.render(gridContainer);
    },
  });

  // Manual refresh trigger
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => {
      refreshDbData(true);
    });
  }

  // Automatic background refresh every minute (60,000 ms)
  setInterval(() => {
    refreshDbData(false);
  }, 60000);
});

