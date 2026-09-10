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
    if (window.ConfigDirtyManager) {
      if (changesetManager.isDirty()) {
        window.ConfigDirtyManager.markDirty();
      } else {
        window.ConfigDirtyManager.clearDirty();
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
    } else if (d === 'database') {
      badgeClass = 'bg-rose-100 text-rose-800 dark:bg-rose-950/80 dark:text-rose-300';
      icon = 'database';
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
      const stagedUpdate = changesetManager.getUpdated(item.id);
      const isEnabled =
        stagedUpdate !== undefined
          ? Boolean(stagedUpdate.enabled)
          : Boolean(item.enabled);
      const isChanged =
        stagedUpdate !== undefined &&
        Boolean(stagedUpdate.enabled) !== Boolean(item.enabled);

      const typeBadge = item.is_mutating
        ? `<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-300">
             <span class="material-symbols-outlined text-xs leading-none">edit</span> Mutating
           </span>`
        : `<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-sky-100 text-sky-800 dark:bg-sky-950/80 dark:text-sky-300">
             <span class="material-symbols-outlined text-xs leading-none">visibility</span> Read-Only
           </span>`;

      const toggleControl = `
        <label class="relative inline-flex items-center cursor-pointer select-none">
          <input 
            type="checkbox" 
            class="sr-only peer mcp-enabled-toggle" 
            data-item-id="${item.id}"
            ${isEnabled ? 'checked' : ''}
          >
          <div class="w-11 h-6 bg-slate-200 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-indigo-500/30 dark:peer-focus:ring-indigo-600/30 rounded-full peer dark:bg-slate-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-slate-600 peer-checked:bg-indigo-600 ${isChanged ? 'ring-2 ring-indigo-400' : ''}"></div>
          <span class="ml-2.5 text-xs font-semibold ${isEnabled ? 'text-indigo-600 dark:text-indigo-400' : 'text-slate-500 dark:text-slate-400'}">
            ${isEnabled ? 'Enabled' : 'Disabled'}
          </span>
        </label>
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
        gridjs.html(toggleControl),
      ];
    });
  }

  // Initialise Grid.js
  const mcpGrid = new gridjs.Grid({
    columns: [
      { name: 'Tool Identifier', width: '22%' },
      { name: 'Domain', width: '15%' },
      { name: 'Type', width: '14%' },
      { name: 'Description', width: '31%' },
      { name: 'Status', width: '18%' },
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

  // Listen for toggle status changes
  if (gridWrapper) {
    gridWrapper.addEventListener('change', (e) => {
      const toggle = e.target.closest('.mcp-enabled-toggle');
      if (!toggle) return;

      const itemId = parseInt(toggle.getAttribute('data-item-id'), 10);
      const newEnabled = toggle.checked;
      const originalItem = currentPageItems.find((i) => i.id === itemId);

      if (originalItem && Boolean(originalItem.enabled) === newEnabled) {
        changesetManager.updated.delete(String(itemId));
      } else {
        changesetManager.update(itemId, {
          id: itemId,
          enabled: newEnabled,
        });
      }

      syncDirtyStatus();
      mcpGrid.forceRender();
    });
  }

  function handleDiscard() {
    if (changesetManager.isDirty()) {
      changesetManager.reset();
      syncDirtyStatus();
      mcpGrid.forceRender();
    }
  }

  // Discard changes
  if (discardBtn) {
    discardBtn.addEventListener('click', handleDiscard);
  }

  if (window.ConfigDirtyManager) {
    window.ConfigDirtyManager.registerDiscardHandler(handleDiscard);
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
