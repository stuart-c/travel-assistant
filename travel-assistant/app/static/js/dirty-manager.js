/**
 * Global Dirty Manager for Travel Assistant Configuration Pages.
 * Handles unsaved changes tracking, navigation interception, confirmation modal, and mobile drawer.
 */
window.ConfigDirtyManager = (function () {
  let dirty = false;
  let pendingNavigationUrl = null;
  let onDiscardCallback = null;
  let isSubmitting = false;

  function getElements() {
    return {
      badge: document.getElementById('dirty-status-badge'),
      saveBtn: document.getElementById('config-save-btn'),
      discardBtn: document.getElementById('config-discard-btn'),
      modal: document.getElementById('unsaved-modal'),
      stayBtn: document.getElementById('unsaved-stay-btn'),
      leaveBtn: document.getElementById('unsaved-leave-btn'),
      toggleBtn: document.getElementById('mobile-config-toggle'),
      sidebar: document.getElementById('config-sidebar'),
      toggleIcon: document.getElementById('mobile-toggle-icon'),
    };
  }

  function updateUI() {
    const { badge, saveBtn, discardBtn } = getElements();
    if (dirty) {
      if (badge) {
        badge.className =
          'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-300 dark:ring-1 dark:ring-amber-500/30';
        badge.innerHTML =
          '<span class="inline-block w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse"></span> Unsaved changes';
      }
      if (discardBtn) {
        discardBtn.disabled = false;
        discardBtn.className =
          'inline-flex items-center justify-center px-4 py-2 rounded-xl text-sm font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700 transition-all cursor-pointer';
      }
      if (saveBtn) {
        saveBtn.classList.remove('opacity-90');
        saveBtn.classList.add('ring-2', 'ring-sky-500/50');
      }
    } else {
      if (badge) {
        badge.className =
          'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400';
        badge.innerHTML =
          '<span class="inline-block w-1.5 h-1.5 rounded-full bg-slate-400"></span> No unsaved changes';
      }
      if (discardBtn) {
        discardBtn.disabled = true;
        discardBtn.className =
          'inline-flex items-center justify-center px-4 py-2 rounded-xl text-sm font-semibold bg-slate-100 text-slate-400 dark:bg-slate-800/80 dark:text-slate-500 cursor-not-allowed transition-all';
      }
      if (saveBtn) {
        saveBtn.classList.remove('ring-2', 'ring-sky-500/50');
      }
    }
  }

  function setDirty(isDirty) {
    dirty = isDirty;
    updateUI();
  }

  function markDirty() {
    setDirty(true);
  }

  function clearDirty() {
    setDirty(false);
  }

  function registerDiscardHandler(fn) {
    onDiscardCallback = fn;
  }

  // Intercept internal navigation when unsaved changes exist
  function handleNavigation(e, href) {
    const { modal } = getElements();
    if (dirty && !isSubmitting) {
      e.preventDefault();
      pendingNavigationUrl = href;
      if (modal && typeof modal.showModal === 'function') {
        modal.showModal();
      } else {
        const leave = confirm(
          'You have unsaved changes. If you leave, your changes will be discarded. Continue?'
        );
        if (leave) {
          dirty = false;
          window.location.href = href;
        }
      }
    }
  }

  function init() {
    const {
      modal,
      stayBtn,
      leaveBtn,
      discardBtn,
      saveBtn,
      toggleBtn,
      sidebar,
      toggleIcon,
    } = getElements();

    // Bind navigation interceptors
    document.querySelectorAll('.config-nav-link').forEach((link) => {
      link.addEventListener('click', (e) => {
        const href = link.getAttribute('href');
        if (href && href !== '#' && !href.startsWith('javascript:')) {
          handleNavigation(e, href);
        }
      });
    });

    if (stayBtn && modal) {
      stayBtn.addEventListener('click', () => {
        modal.close();
        pendingNavigationUrl = null;
      });
    }

    if (leaveBtn && modal) {
      leaveBtn.addEventListener('click', () => {
        modal.close();
        dirty = false;
        if (pendingNavigationUrl) {
          window.location.href = pendingNavigationUrl;
        }
      });
    }

    if (discardBtn) {
      discardBtn.addEventListener('click', () => {
        if (!dirty) return;
        if (typeof onDiscardCallback === 'function') {
          onDiscardCallback();
        }
        clearDirty();
      });
    }

    // Save button delegates to active config form submission
    if (saveBtn) {
      saveBtn.addEventListener('click', () => {
        const form =
          document.querySelector('form.config-main-form') ||
          document.querySelector('form');
        if (form) {
          isSubmitting = true;
          dirty = false;
          form.submit();
        }
      });
    }

    // Intercept page reload / close
    window.addEventListener('beforeunload', (e) => {
      if (dirty && !isSubmitting) {
        e.preventDefault();
        e.returnValue = '';
      }
    });

    // Mobile sidebar toggle handler
    if (toggleBtn && sidebar) {
      toggleBtn.addEventListener('click', () => {
        const isHidden = sidebar.classList.contains('hidden');
        if (isHidden) {
          sidebar.classList.remove('hidden');
          toggleBtn.setAttribute('aria-expanded', 'true');
          if (toggleIcon) toggleIcon.textContent = 'close';
        } else {
          sidebar.classList.add('hidden');
          toggleBtn.setAttribute('aria-expanded', 'false');
          if (toggleIcon) toggleIcon.textContent = 'menu';
        }
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  return {
    setDirty,
    markDirty,
    clearDirty,
    isDirty: () => dirty,
    registerDiscardHandler,
    markSubmitting: () => {
      isSubmitting = true;
      dirty = false;
    },
  };
})();
