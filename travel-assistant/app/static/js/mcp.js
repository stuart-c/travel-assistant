/**
 * Model Context Protocol (MCP) Configuration Controller
 * 
 * Manages client-side staged state for MCP tool permissions
 * using Grid.js and differential changeset persistence.
 */

document.addEventListener('DOMContentLoaded', () => {
  const configEl = document.getElementById('mcp-config');
  if (!configEl) return;

  const dataUrl = configEl.getAttribute('data-data-url') || '/config/mcp/data';

  // Staged changeset manager
  const changesetManager =
    window.TransitUI && window.TransitUI.createStagedChangesetManager
      ? window.TransitUI.createStagedChangesetManager('id')
      : new window.TransitUI.StagedChangesetManager('id');

  let currentPageItems = [];
  const gridWrapper = document.getElementById('mcp-tools-grid-wrapper');
  const emptyState = document.getElementById('mcp-grid-empty-state');
  const discardBtn = document.getElementById('config-discard-btn');

  const escapeHtml =
    (window.TransitUI && window.TransitUI.escapeHtml) ||
    ((str) => (str ? String(str) : ''));

  function syncDirtyStatus() {
    const isDirty = changesetManager.hasChanges();
    if (window.ConfigDirtyManager) {
      if (isDirty) {
        window.ConfigDirtyManager.markDirty();
      } else {
        window.ConfigDirtyManager.markClean();
      }
    }
  }

  function getDomainBadge(domain) {
    const d = String(domain || '').toLowerCase();
    let badgeClass = 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300';
    let icon = 'category';

    if (d === 'journey') {
      badgeClass = 'bg-indigo-100 text-indigo-800 dark:bg-indigo-950/80 dark:text-indigo-300';
      icon = 'route';
    } else if (d === 'timetable') {
      badgeClass = 'bg-sky-100 text-sky-800 dark:bg-sky-950/80 dark:text-sky-300';
      icon = 'table_chart';
    } else if (d === 'stops') {
      badgeClass = 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300';
      icon = 'pin_drop';
    } else if (d === 'walking') {
      badgeClass = 'bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-300';
      icon = 'directions_walk';
    } else if (d === 'dispatcher') {
      badgeClass = 'bg-purple-100 text-purple-800 dark:bg-purple-950/80 dark:text-purple-300';
      icon = 'notifications_active';
    } else if (d === 'sync') {
      badgeClass = 'bg-cyan-100 text-cyan-800 dark:bg-cyan-950/80 dark:text-cyan-300';
      icon = 'sync';
    }

    const label = d.charAt(0).toUpperCase() + d.slice(1);
    return `
      <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold ${badgeClass}">
        <span class="material-symbols-outlined text-sm leading-none">${icon}</span>
        ${escapeHtml(label)}
      </span>
    `;
  }

  function formatGridData(items) {
    return items.map((item) => {
      const stagedUpdate = changesetManager.getUpdated().find((u) => u.id === item.id);
      const currentLevel = stagedUpdate ? stagedUpdate.access_level : item.access_level;

      const typeBadge = item.is_mutating
        ? `<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-300">
             <span class="material-symbols-outlined text-xs leading-none">edit</span> Mutating
           </span>`
        : `<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-sky-100 text-sky-800 dark:bg-sky-950/80 dark:text-sky-300">
             <span class="material-symbols-outlined text-xs leading-none">visibility</span> Read-Only
           </span>`;

      let optionsHtml = '';
      if (item.is_mutating) {
        optionsHtml = `
          <option value="disabled" ${currentLevel === 'disabled' ? 'selected' : ''}>Disabled</option>
          <option value="read_write" ${currentLevel === 'read_write' ? 'selected' : ''}>Read / Write (Enabled)</option>
        `;
      } else {
        optionsHtml = `
          <option value="disabled" ${currentLevel === 'disabled' ? 'selected' : ''}>Disabled</option>
          <option value="read" ${currentLevel === 'read' ? 'selected' : ''}>Read (Enabled)</option>
        `;
      }

      const isChanged = stagedUpdate && stagedUpdate.access_level !== item.access_level;
      const borderStyle = isChanged
        ? 'border-indigo-500 bg-indigo-50/50 dark:border-indigo-400 dark:bg-indigo-950/30'
        : 'border-slate-300 bg-white dark:border-slate-700 dark:bg-slate-800';

      const selectControl = `
        <select 
          class="mcp-access-select px-3 py-1.5 rounded-xl border text-xs font-semibold text-slate-800 dark:text-slate-200 ${borderStyle} focus:outline-none focus:ring-2 focus:ring-indigo-500/20 cursor-pointer"
          data-item-id="${item.id}"
        >
          ${optionsHtml}
        </select>
      `;

      return [
        gridjs.html(`
          <div class="flex items-center gap-2">
            <span class="font-mono text-xs font-bold text-slate-900 dark:text-slate-100">${escapeHtml(item.tool_name)}</span>
            ${isChanged ? '<span class="inline-block w-2 h-2 rounded-full bg-indigo-500" title="Unsaved change"></span>' : ''}
          </div>
        `),
        gridjs.html(getDomainBadge(item.domain)),
        gridjs.html(typeBadge),
        gridjs.html(`<span class="text-xs text-slate-600 dark:text-slate-400 leading-relaxed">${escapeHtml(item.description)}</span>`),
        gridjs.html(selectControl),
      ];
    });
  }

  // Initialise Grid.js
  const mcpGrid = new gridjs.Grid({
    columns: [
      { name: 'Tool Identifier', width: '22%' },
      { name: 'Domain', width: '16%' },
      { name: 'Type', width: '14%' },
      { name: 'Description', width: '32%' },
      { name: 'Access Level', width: '16%' },
    ],
    server: {
      url: dataUrl,
      then: (data) => {
        currentPageItems = Array.isArray(data) ? data : data.data || [];
        if (emptyState && gridWrapper) {
          if (currentPageItems.length === 0) {
            emptyState.classList.remove('hidden');
            gridWrapper.classList.add('hidden');
          } else {
            emptyState.classList.add('hidden');
            gridWrapper.classList.remove('hidden');
          }
        }
        return formatGridData(currentPageItems);
      },
    },
    sort: true,
    search: true,
    pagination: {
      limit: 25,
      summary: true,
    },
    className: {
      table: 'w-full text-left border-collapse',
    },
  });

  if (gridWrapper) {
    mcpGrid.render(gridWrapper);
  }

  // Listen for access level dropdown changes
  if (gridWrapper) {
    gridWrapper.addEventListener('change', (e) => {
      const select = e.target.closest('.mcp-access-select');
      if (!select) return;

      const itemId = parseInt(select.getAttribute('data-item-id'), 10);
      const newLevel = select.value;

      changesetManager.stageUpdated({
        id: itemId,
        access_level: newLevel,
      });

      syncDirtyStatus();
      mcpGrid.forceRender();
    });
  }

  // Discard changes
  if (discardBtn) {
    discardBtn.addEventListener('click', () => {
      if (changesetManager.hasChanges()) {
        changesetManager.reset();
        syncDirtyStatus();
        mcpGrid.forceRender();
      }
    });
  }

  // Register with ConfigSave
  if (window.ConfigSave) {
    window.ConfigSave.register({
      endpoint: dataUrl,
      getChangeset: () => changesetManager.getChangeset(),
      onSaveSuccess: () => {
        changesetManager.reset();
        syncDirtyStatus();
        mcpGrid.forceRender();
      },
    });
  }
});
