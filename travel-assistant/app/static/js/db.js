/**
 * Database Storage View Controller.
 * Manages Grid.js data table rendering for SQLite database tables and row counts.
 */
document.addEventListener('DOMContentLoaded', () => {
  const gridContainer = document.getElementById('db-grid-wrapper');
  if (!gridContainer) return;

  const dataUrl = gridContainer.getAttribute('data-data-url') || '/config/db/data';



  let tables = [];

  const escapeHtml = (window.TransitUI && window.TransitUI.escapeHtml) || function (str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  };

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

  // Fetch remote data then render — loading/error UI managed by GridLoader
  GridLoader.load(dataUrl, gridContainer, {
    label: 'database statistics',
    onSuccess(json) {
      tables = Array.isArray(json.data) ? json.data : [];
      new gridjs.Grid({
        columns: [
          { name: 'Table Name', width: '65%' },
          { name: 'Rows', width: '35%' },
        ],
        data: formatDbGridData(tables),
        search: false,
        pagination: false,
        sort: true,
      }).render(gridContainer);
    },
  });
});

