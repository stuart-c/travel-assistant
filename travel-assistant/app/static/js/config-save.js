/**
 * Shared AJAX Save and Notification Manager for Configuration Pages.
 * Handles background POST persistence to /config/xxx/data endpoints,
 * Save button spinner states, and floating toast notifications.
 *
 * Exposed as: window.ConfigSave
 */
window.ConfigSave = (function () {
  'use strict';

  let currentOptions = null;
  let isSaving = false;

  /**
   * Register the active configuration page save handler.
   *
   * @param {Object} options
   * @param {string} options.endpoint - The AJAX POST endpoint (e.g. '/config/journeys/data').
   * @param {Function} options.getChangeset - Zero-argument function returning { added, updated, deleted }.
   * @param {Function} [options.onSaveSuccess] - Optional callback invoked after successful save.
   */
  function register(options) {
    currentOptions = options;
  }

  /**
   * Display a floating toast notification in the bottom-right corner.
   *
   * @param {string} message - Notification text message.
   * @param {'success'|'error'} [type='success'] - Toast style type.
   */
  function showToast(message, type = 'success') {
    let container = document.getElementById('config-toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'config-toast-container';
      container.className =
        'fixed bottom-5 right-5 z-50 flex flex-col gap-2 pointer-events-none max-w-sm w-full';
      document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    const isSuccess = type === 'success';
    const borderColor = isSuccess
      ? 'border-emerald-500/40 dark:border-emerald-500/40'
      : 'border-rose-500/40 dark:border-rose-500/40';
    const iconName = isSuccess ? 'check_circle' : 'error';
    const iconColor = isSuccess ? 'text-emerald-500' : 'text-rose-500';

    toast.className = `pointer-events-auto rounded-2xl border ${borderColor} bg-white dark:bg-slate-900 p-4 shadow-xl text-slate-800 dark:text-slate-100 flex items-center justify-between gap-3 text-sm font-medium transform transition-all duration-300 translate-y-4 opacity-0`;

    toast.innerHTML = `
      <div class="flex items-center gap-2.5 min-w-0">
        <span class="material-symbols-outlined text-xl ${iconColor} shrink-0">${iconName}</span>
        <span class="truncate">${message}</span>
      </div>
      <button type="button" class="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 text-xs shrink-0 cursor-pointer p-1" aria-label="Dismiss notification">
        <span class="material-symbols-outlined text-base">close</span>
      </button>
    `;

    const dismissBtn = toast.querySelector('button');
    let timeoutId = null;

    function removeToast() {
      if (timeoutId) clearTimeout(timeoutId);
      toast.classList.add('translate-y-4', 'opacity-0');
      setTimeout(() => {
        if (toast.parentNode) {
          toast.parentNode.removeChild(toast);
        }
      }, 300);
    }

    if (dismissBtn) {
      dismissBtn.addEventListener('click', removeToast);
    }

    container.appendChild(toast);

    // Trigger enter animation
    requestAnimationFrame(() => {
      toast.classList.remove('translate-y-4', 'opacity-0');
    });

    timeoutId = setTimeout(removeToast, 4000);
  }

  /**
   * Execute the asynchronous save request.
   */
  async function save() {
    if (!currentOptions || !currentOptions.endpoint || isSaving) return;

    const saveBtn = document.getElementById('config-save-btn');
    const defaultSaveHtml =
      '<span class="material-symbols-outlined text-base leading-none">save</span>\n            <span>Save Changes</span>';
    const originalContent =
      (saveBtn && saveBtn.getAttribute('data-original-html')) ||
      (saveBtn ? saveBtn.innerHTML : '') ||
      defaultSaveHtml;

    try {
      isSaving = true;

      // Set Save button to loading spinner state
      if (saveBtn) {
        if (!saveBtn.getAttribute('data-original-html')) {
          saveBtn.setAttribute('data-original-html', originalContent);
        }
        saveBtn.disabled = true;
        saveBtn.innerHTML = `
          <span class="material-symbols-outlined text-base leading-none animate-spin">progress_activity</span>
          <span>Saving&hellip;</span>
        `;
        saveBtn.className =
          'inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold bg-sky-600 text-white opacity-80 cursor-wait transition-all';
      }

      const changeset =
        typeof currentOptions.getChangeset === 'function'
          ? currentOptions.getChangeset()
          : { added: [], updated: [], deleted: [] };

      const response = await fetch(currentOptions.endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(changeset),
      });

      const result = await response.json().catch(() => ({}));

      if (response.ok && result.success) {
        if (saveBtn) {
          saveBtn.innerHTML = originalContent;
        }
        if (window.ConfigDirtyManager) {
          window.ConfigDirtyManager.clearDirty();
        }
        showToast(result.message || 'Changes saved successfully.', 'success');

        if (typeof currentOptions.onSaveSuccess === 'function') {
          currentOptions.onSaveSuccess(result);
        }
      } else {
        const errorMsg =
          result.message || `Save failed with status ${response.status}.`;
        showToast(errorMsg, 'error');

        // Restore active save button state so user can retry
        if (saveBtn) {
          saveBtn.disabled = false;
          saveBtn.innerHTML = originalContent;
          saveBtn.className =
            'inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold bg-sky-600 text-white hover:bg-sky-500 shadow-sm transition-all cursor-pointer';
        }
      }
    } catch (err) {
      console.error('ConfigSave: save request failed:', err);
      showToast(`Network error: ${err.message || 'Failed to save.'}`, 'error');

      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.innerHTML = originalContent;
        saveBtn.className =
          'inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold bg-sky-600 text-white hover:bg-sky-500 shadow-sm transition-all cursor-pointer';
      }
    } finally {
      isSaving = false;
      if (saveBtn && (!window.ConfigDirtyManager || !window.ConfigDirtyManager.isDirty())) {
        saveBtn.innerHTML = originalContent;
      }
    }
  }

  return {
    register,
    save,
    showToast,
    isSaving: () => isSaving,
  };
})();
