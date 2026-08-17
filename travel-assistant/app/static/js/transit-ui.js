/**
 * TransitUI - Shared UI utilities, components, and formatters for Travel Assistant.
 * Provides unified escaping, transport mode badges, action buttons, timestamps,
 * and collapsible section management.
 */
window.TransitUI = (function () {
  'use strict';

  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  const TRANSPORT_MODES = {
    rail: {
      label: 'Train / Rail',
      shortLabel: 'Rail',
      icon: 'train',
      badgeClass:
        'bg-indigo-100 text-indigo-800 dark:bg-indigo-950/80 dark:text-indigo-300 dark:ring-1 dark:ring-indigo-500/30',
    },
    bus: {
      label: 'Bus',
      shortLabel: 'Bus',
      icon: 'directions_bus',
      badgeClass:
        'bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-300 dark:ring-1 dark:ring-amber-500/30',
    },
    metro: {
      label: 'Metro',
      shortLabel: 'Metro',
      icon: 'subway',
      badgeClass:
        'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300 dark:ring-1 dark:ring-emerald-500/30',
    },
    tram: {
      label: 'Tram',
      shortLabel: 'Tram',
      icon: 'tram',
      badgeClass:
        'bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-300 dark:ring-1 dark:ring-amber-500/30',
    },
    ferry: {
      label: 'Ferry',
      shortLabel: 'Ferry',
      icon: 'directions_boat',
      badgeClass:
        'bg-cyan-100 text-cyan-800 dark:bg-cyan-950/80 dark:text-cyan-300 dark:ring-1 dark:ring-cyan-500/30',
    },
    air: {
      label: 'Flight',
      shortLabel: 'Air',
      icon: 'flight',
      badgeClass:
        'bg-purple-100 text-purple-800 dark:bg-purple-950/80 dark:text-purple-300 dark:ring-1 dark:ring-purple-500/30',
    },
    ha: {
      label: 'Home Assistant',
      shortLabel: 'HA',
      icon: 'home',
      badgeClass:
        'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300 dark:ring-1 dark:ring-emerald-500/30',
    },
    custom: {
      label: 'Custom',
      shortLabel: 'Custom',
      icon: 'pin_drop',
      badgeClass:
        'bg-sky-100 text-sky-800 dark:bg-sky-950/80 dark:text-sky-300 dark:ring-1 dark:ring-sky-500/30',
    },
  };

  function getTransportMeta(type) {
    const key = String(type || '').toLowerCase();
    return TRANSPORT_MODES[key] || TRANSPORT_MODES.custom;
  }

  function getTransportIcon(type) {
    return getTransportMeta(type).icon;
  }

  function getTransportBadge(type, labelOverride = null, short = false) {
    const meta = getTransportMeta(type);
    const label = labelOverride || (short ? meta.shortLabel : meta.label);
    return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${meta.badgeClass}"><span class="material-symbols-outlined text-xs leading-none">${meta.icon}</span> ${escapeHtml(label)}</span>`;
  }

  /**
   * Generates standardised HTML for Grid.js 28x28px action buttons.
   *
   * @param {Object} options
   * @param {number|string} options.index - Row index or identifier.
   * @param {boolean} [options.showEdit=true] - Include edit button.
   * @param {boolean} [options.showDelete=true] - Include delete button.
   * @param {boolean} [options.showView=false] - Include read-only view button.
   * @param {boolean} [options.showGrid=false] - Include grid matrix editor button.
   * @param {boolean} [options.isReadOnly=false] - If true, replaces edit/delete with view.
   * @param {string} [options.editClass='action-btn-edit'] - Class for edit button event delegation.
   * @param {string} [options.deleteClass='action-btn-delete'] - Class for delete button event delegation.
   * @param {string} [options.viewClass='action-btn-view'] - Class for view button event delegation.
   * @param {string} [options.gridClass='action-btn-grid'] - Class for grid button event delegation.
   * @param {string} [options.editTitle='Edit'] - Tooltip text for edit button.
   * @param {string} [options.deleteTitle='Delete'] - Tooltip text for delete button.
   * @param {string} [options.viewTitle='View details (Read-only)'] - Tooltip text for view button.
   * @param {string} [options.gridTitle='Open Grid Editor'] - Tooltip text for grid button.
   * @returns {string} HTML string containing the action buttons.
   */
  function renderActionButtons(options) {
    const {
      index,
      showEdit = true,
      showDelete = true,
      showView = false,
      showGrid = false,
      isReadOnly = false,
      editClass = 'action-btn-edit',
      deleteClass = 'action-btn-delete',
      viewClass = 'action-btn-view',
      gridClass = 'action-btn-grid',
      editTitle = 'Edit',
      deleteTitle = 'Delete',
      viewTitle = 'View details (Read-only)',
      gridTitle = 'Open Grid Editor',
    } = options || {};

    const buttons = [];

    if (showGrid) {
      buttons.push(`
        <button 
          type="button" 
          class="${gridClass} w-7 h-7 rounded-lg inline-flex items-center justify-center bg-indigo-50 text-indigo-600 hover:bg-indigo-100 dark:bg-indigo-950/60 dark:text-indigo-300 dark:hover:bg-indigo-900/60 transition-colors cursor-pointer"
          data-index="${index}"
          title="${escapeHtml(gridTitle)}"
          aria-label="${escapeHtml(gridTitle)}"
        >
          <span class="material-symbols-outlined text-[15px] leading-none">grid_on</span>
        </button>
      `);
    }

    if (isReadOnly || showView) {
      buttons.push(`
        <button 
          type="button" 
          class="${viewClass} w-7 h-7 rounded-lg inline-flex items-center justify-center bg-sky-50 text-sky-600 hover:bg-sky-100 dark:bg-sky-950/60 dark:text-sky-300 dark:hover:bg-sky-900/60 transition-colors cursor-pointer"
          data-index="${index}"
          title="${escapeHtml(viewTitle)}"
          aria-label="${escapeHtml(viewTitle)}"
        >
          <span class="material-symbols-outlined text-[15px] leading-none">visibility</span>
        </button>
      `);
    } else {
      if (showEdit) {
        buttons.push(`
          <button 
            type="button" 
            class="${editClass} w-7 h-7 rounded-lg inline-flex items-center justify-center bg-sky-50 text-sky-600 hover:bg-sky-100 dark:bg-sky-950/60 dark:text-sky-300 dark:hover:bg-sky-900/60 transition-colors cursor-pointer"
            data-index="${index}"
            title="${escapeHtml(editTitle)}"
            aria-label="${escapeHtml(editTitle)}"
          >
            <span class="material-symbols-outlined text-[15px] leading-none">edit</span>
          </button>
        `);
      }
      if (showDelete) {
        buttons.push(`
          <button 
            type="button" 
            class="${deleteClass} w-7 h-7 rounded-lg inline-flex items-center justify-center bg-rose-50 text-rose-600 hover:bg-rose-100 dark:bg-rose-950/60 dark:text-rose-300 dark:hover:bg-rose-900/60 transition-colors cursor-pointer"
            data-index="${index}"
            title="${escapeHtml(deleteTitle)}"
            aria-label="${escapeHtml(deleteTitle)}"
          >
            <span class="material-symbols-outlined text-[15px] leading-none">delete</span>
          </button>
        `);
      }
    }

    return `<div class="flex items-center justify-end gap-1.5">${buttons.join('')}</div>`;
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

  function formatDaysSummary(days) {
    if (!days || !days.length) return 'All days';
    const dayMap = {
      mon: 'Mon',
      tue: 'Tue',
      wed: 'Wed',
      thu: 'Thu',
      fri: 'Fri',
      sat: 'Sat',
      sun: 'Sun',
      bank_holiday: 'Bank Holiday',
      monday: 'Mon',
      tuesday: 'Tue',
      wednesday: 'Wed',
      thursday: 'Thu',
      friday: 'Fri',
      saturday: 'Sat',
      sunday: 'Sun',
    };
    const normDays = days.map((d) => String(d).toLowerCase());
    const isWeekdays =
      ['mon', 'tue', 'wed', 'thu', 'fri'].every((d) => normDays.includes(d)) ||
      ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'].every((d) =>
        normDays.includes(d)
      );
    const hasWeekends =
      (normDays.includes('sat') && normDays.includes('sun')) ||
      (normDays.includes('saturday') && normDays.includes('sunday'));

    if (normDays.length === 8 || (isWeekdays && hasWeekends && (normDays.includes('bank_holiday') || normDays.length >= 7))) {
      return 'All days & Bank Holidays';
    }
    if (isWeekdays && normDays.length === 5) {
      return 'Weekdays (Mon–Fri)';
    }
    if (hasWeekends && normDays.length === 2) {
      return 'Weekends (Sat–Sun)';
    }

    return normDays.map((d) => dayMap[d] || d).join(', ');
  }

  /**
   * CollapsibleSection Manager.
   * Handles toggling collapsible cards, chevron animation, and initial collapse states.
   */
  const CollapsibleManager = {
    setSectionCollapseState: function (sectionIdOrEl, collapse) {
      const section =
        typeof sectionIdOrEl === 'string'
          ? document.getElementById(sectionIdOrEl)
          : sectionIdOrEl;
      if (!section) return;
      const icon = section.querySelector('.collapse-icon, .collapsible-chevron');

      if (collapse) {
        section.classList.add('collapsed');
        if (icon) icon.textContent = 'chevron_right';
      } else {
        section.classList.remove('collapsed');
        if (icon) icon.textContent = 'keyboard_arrow_down';
      }
    },

    initialise: function (root = document) {
      root.querySelectorAll('.collapse-toggle-btn').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          const targetId = btn.getAttribute('data-target');
          const section = targetId
            ? document.getElementById(targetId)
            : btn.closest('.collapsible-section');
          if (section) {
            const isCollapsed = section.classList.contains('collapsed');
            CollapsibleManager.setSectionCollapseState(section, !isCollapsed);
          }
        });
      });

      root.querySelectorAll('.section-toggle').forEach((header) => {
        header.addEventListener('click', (e) => {
          if (
            e.target.closest(
              'button, input, select, a, .check-btn, .status-valid-badge'
            )
          ) {
            return;
          }
          const targetId = header.getAttribute('data-target');
          const section = targetId
            ? document.getElementById(targetId)
            : header.closest('.collapsible-section');
          if (section) {
            const isCollapsed = section.classList.contains('collapsed');
            CollapsibleManager.setSectionCollapseState(section, !isCollapsed);
          }
        });
      });
    },
  };
  /**
   * Display a styled notification alert banner in a container element.
   *
   * @param {HTMLElement|string} container - The container element or selector.
   * @param {string} message - Text or HTML message content.
   * @param {'success'|'error'|'info'|'warning'} [type='info'] - Alert category.
   * @param {Object} [options] - Configuration options.
   * @param {number} [options.autoDismissMs] - Auto dismiss timeout in ms (default 0 = permanent until replaced).
   * @param {boolean} [options.isHtml=false] - Whether message contains HTML.
   */
  function showNotification(container, message, type = 'info', options = {}) {
    const el = typeof container === 'string' ? document.querySelector(container) : container;
    if (!el) return;

    const isSuccess = type === 'success';
    const isError = type === 'error';
    const isWarning = type === 'warning';

    const icon = isSuccess ? 'check_circle' : isError ? 'error' : isWarning ? 'warning' : 'info';

    el.className = el.className
      .replace(/\b(bg|text|border)-(emerald|rose|amber|sky|slate)-[^\s]+/g, '')
      .trim();

    let typeClasses = 'bg-sky-50 border-sky-200 text-sky-800 dark:bg-sky-950/40 dark:border-sky-800/60 dark:text-sky-300';
    let iconClass = 'text-sky-600 dark:text-sky-400';

    if (isSuccess) {
      typeClasses = 'bg-emerald-50 border-emerald-200 text-emerald-800 dark:bg-emerald-950/40 dark:border-emerald-800/60 dark:text-emerald-300';
      iconClass = 'text-emerald-600 dark:text-emerald-400';
    } else if (isError) {
      typeClasses = 'bg-rose-50 border-rose-200 text-rose-800 dark:bg-rose-950/40 dark:border-rose-800/60 dark:text-rose-300';
      iconClass = 'text-rose-600 dark:text-rose-400';
    } else if (isWarning) {
      typeClasses = 'bg-amber-50 border-amber-200 text-amber-800 dark:bg-amber-950/40 dark:border-amber-800/60 dark:text-amber-300';
      iconClass = 'text-amber-600 dark:text-amber-400';
    }

    el.classList.add(
      'p-4',
      'rounded-xl',
      'text-sm',
      'font-medium',
      'border',
      'flex',
      'items-center',
      'gap-3',
      'transition-all',
      ...typeClasses.split(' ')
    );
    el.classList.remove('hidden');

    const msgHtml = options.isHtml ? message : escapeHtml(message);
    el.innerHTML = `
      <span class="material-symbols-outlined text-xl shrink-0 leading-none ${iconClass}">${icon}</span>
      <div class="flex-1">${msgHtml}</div>
    `;

    const autoDismiss = options.autoDismissMs !== undefined ? options.autoDismissMs : 0;
    if (autoDismiss > 0) {
      clearTimeout(el._dismissTimeout);
      el._dismissTimeout = setTimeout(() => {
        el.classList.add('hidden');
      }, autoDismiss);
    }
  }

  /**
   * ChangesetTracker - Componentised staged collection manager for configuration pages.
   * Handles staged state, deletion tracking, modal adjustment detection, and standard
   * { added, updated, deleted } changeset generation.
   */
  class ChangesetTracker {
    constructor(initialData = [], options = {}) {
      this.keyField = options.keyField || 'id';
      this.compareFunc = typeof options.compareFunc === 'function' ? options.compareFunc : null;
      this.initialItems = JSON.parse(JSON.stringify(initialData || []));
      this.stagedItems = JSON.parse(JSON.stringify(initialData || []));

      this.initialMap = new Map();
      this.initialItems.forEach((item) => {
        const key = this._getItemKey(item);
        if (key !== null) {
          this.initialMap.set(key, JSON.parse(JSON.stringify(item)));
        }
      });

      this.updatedKeys = new Set();
      this.deletedKeys = new Set();
    }

    _getItemKey(item) {
      if (!item) return null;
      const val = item[this.keyField];
      if (val === null || val === undefined || val === '') return null;
      return String(val);
    }

    hasAdjustments(original, current) {
      if (this.compareFunc) {
        return this.compareFunc(original, current);
      }
      return JSON.stringify(original) !== JSON.stringify(current);
    }

    getItems() {
      return this.stagedItems;
    }

    getItem(index) {
      return this.stagedItems[index];
    }

    setItems(items) {
      this.stagedItems = items || [];
    }

    saveModalItem(index, item) {
      const idx = parseInt(index, 10);
      if (!isNaN(idx) && idx >= 0 && idx < this.stagedItems.length) {
        const existing = this.stagedItems[idx];
        const key = this._getItemKey(existing);

        this.stagedItems[idx] = item;

        if (key !== null && this.initialMap.has(key)) {
          const initial = this.initialMap.get(key);
          if (this.hasAdjustments(initial, item)) {
            this.updatedKeys.add(key);
          } else {
            this.updatedKeys.delete(key);
          }
        }
        return item;
      } else {
        this.stagedItems.push(item);
        return item;
      }
    }

    markUpdated(index) {
      const idx = parseInt(index, 10);
      if (!isNaN(idx) && idx >= 0 && idx < this.stagedItems.length) {
        const key = this._getItemKey(this.stagedItems[idx]);
        if (key !== null && this.initialMap.has(key)) {
          this.updatedKeys.add(key);
        }
      }
    }

    deleteItem(index) {
      const idx = parseInt(index, 10);
      if (!isNaN(idx) && idx >= 0 && idx < this.stagedItems.length) {
        const [removed] = this.stagedItems.splice(idx, 1);
        if (removed) {
          const key = this._getItemKey(removed);
          if (key !== null && this.initialMap.has(key)) {
            this.deletedKeys.add(removed[this.keyField]);
            this.updatedKeys.delete(key);
          }
        }
        return removed;
      }
      return null;
    }

    getChangeset() {
      const added = [];
      const updated = [];
      const deleted = Array.from(this.deletedKeys);

      for (const item of this.stagedItems) {
        const key = this._getItemKey(item);
        if (key === null || !this.initialMap.has(key)) {
          added.push(item);
        } else if (this.updatedKeys.has(key)) {
          updated.push(item);
        }
      }

      return { added, updated, deleted };
    }

    isDirty() {
      const cs = this.getChangeset();
      return cs.added.length > 0 || cs.updated.length > 0 || cs.deleted.length > 0;
    }

    discard() {
      this.stagedItems = JSON.parse(JSON.stringify(this.initialItems));
      this.updatedKeys.clear();
      this.deletedKeys.clear();
    }
  }

  function createChangesetTracker(initialData = [], options = {}) {
    return new ChangesetTracker(initialData, options);
  }

  return {
    escapeHtml,
    TRANSPORT_MODES,
    getTransportBadge,
    getTransportIcon,
    renderActionButtons,
    parseDate,
    formatRelativeTime,
    formatExactTime,
    formatDaysSummary,
    CollapsibleManager,
    showNotification,
    ChangesetTracker,
    createChangesetTracker,
  };
})();
