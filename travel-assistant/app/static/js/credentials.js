/**
 * API Credentials View Controller.
 * Manages collapsible sections toggled via arrow buttons, initial auto-collapse
 * for verified credentials, green Valid badges, and on-edit revealed Check buttons.
 */
document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('credentials-form');
  if (!form) return;

  const validateUrl =
    form.dataset.validateUrl ||
    (window.location.pathname.replace(/\/$/, '') + '/validate');

  const serviceSections = {
    bus: {
      sectionId: 'section-bus',
      validBadgeId: 'valid-badge-bus',
      checkBtnId: 'check-btn-bus',
      fields: ['bus_api_key'],
      hasValue: () => {
        const val = document.getElementById('bus_api_key')?.value.trim();
        return Boolean(val);
      },
    },
    train_s3: {
      sectionId: 'section-train_s3',
      validBadgeId: 'valid-badge-train_s3',
      checkBtnId: 'check-btn-train_s3',
      fields: [
        'train_s3_bucket',
        'train_s3_region',
        'train_s3_access_key',
        'train_s3_secret_key',
      ],
      hasValue: () => {
        const bucket = document.getElementById('train_s3_bucket')?.value.trim();
        const access = document.getElementById('train_s3_access_key')?.value.trim();
        return Boolean(bucket || access);
      },
    },
    train_live: {
      sectionId: 'section-train_live',
      validBadgeId: 'valid-badge-train_live',
      checkBtnId: 'check-btn-train_live',
      fields: ['train_live_api_key', 'train_live_endpoint'],
      hasValue: () => {
        const key = document.getElementById('train_live_api_key')?.value.trim();
        return Boolean(key);
      },
    },
    open_api: {
      sectionId: 'section-open_api',
      validBadgeId: 'valid-badge-open_api',
      checkBtnId: 'check-btn-open_api',
      fields: ['open_api_key', 'open_api_base_url', 'open_api_model'],
      hasValue: () => {
        const key = document.getElementById('open_api_key')?.value.trim();
        return Boolean(key);
      },
    },
    google_maps: {
      sectionId: 'section-google_maps',
      validBadgeId: 'valid-badge-google_maps',
      checkBtnId: 'check-btn-google_maps',
      fields: ['google_maps_api_key', 'google_maps_region'],
      hasValue: () => {
        const key = document.getElementById('google_maps_api_key')?.value.trim();
        return Boolean(key);
      },
    },
  };

  function setSectionCollapseState(sectionId, collapse) {
    const section = document.getElementById(sectionId);
    if (!section) return;
    const icon = section.querySelector('.collapse-icon');

    if (collapse) {
      section.classList.add('collapsed');
      if (icon) icon.textContent = 'chevron_right';
    } else {
      section.classList.remove('collapsed');
      if (icon) icon.textContent = 'keyboard_arrow_down';
    }
  }

  // Section toggle handlers - only the arrow button toggles
  document.querySelectorAll('.collapse-toggle-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const targetId = btn.getAttribute('data-target');
      const section = targetId
        ? document.getElementById(targetId)
        : btn.closest('.collapsible-section');
      if (section) {
        const isCollapsed = section.classList.contains('collapsed');
        setSectionCollapseState(section.id, !isCollapsed);
      }
    });
  });

  function onSectionInput(serviceKey) {
    const config = serviceSections[serviceKey];
    if (!config) return;
    const badge = document.getElementById(config.validBadgeId);
    const checkBtn = document.getElementById(config.checkBtnId);

    if (badge) {
      badge.classList.add('hidden');
    }
    if (checkBtn) {
      if (config.hasValue()) {
        checkBtn.classList.remove('hidden');
        checkBtn.disabled = false;
      } else {
        checkBtn.classList.add('hidden');
      }
    }
  }

  // Bind input change listeners: editing switches badge to Check button
  Object.entries(serviceSections).forEach(([serviceKey, config]) => {
    config.fields.forEach((fieldId) => {
      const el = document.getElementById(fieldId);
      if (el) {
        el.addEventListener('input', () => onSectionInput(serviceKey));
        el.addEventListener('change', () => onSectionInput(serviceKey));
      }
    });
  });

  // Track input modifications for dirty manager
  if (window.ConfigDirtyManager) {
    form.addEventListener('input', () => {
      window.ConfigDirtyManager.markDirty();
    });

    window.ConfigDirtyManager.registerDiscardHandler(() => {
      form.reset();
      Object.keys(serviceSections).forEach((serviceKey) => {
        validateService(serviceKey, false);
      });
    });
  }

  async function validateService(serviceKey, isInitialLoad = false) {
    const config = serviceSections[serviceKey];
    if (!config) return;

    const badge = document.getElementById(config.validBadgeId);
    const checkBtn = document.getElementById(config.checkBtnId);

    if (!config.hasValue()) {
      if (badge) badge.classList.add('hidden');
      if (checkBtn) checkBtn.classList.add('hidden');
      return;
    }

    if (checkBtn) {
      checkBtn.classList.remove('hidden');
      checkBtn.disabled = true;
      checkBtn.className =
        'check-btn inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-semibold bg-sky-100 text-sky-800 dark:bg-sky-950/80 dark:text-sky-300 animate-pulse cursor-wait';
      checkBtn.innerHTML =
        '<span class="material-symbols-outlined text-[17px] leading-none animate-spin">sync</span> <span>Validating...</span>';
    }

    const payload = { service: serviceKey };
    config.fields.forEach((fieldId) => {
      const el = document.getElementById(fieldId);
      if (el) {
        payload[fieldId] = el.value.trim();
      }
    });

    try {
      const response = await fetch(validateUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify(payload),
      });
      const data = await response.json();

      if (data.valid) {
        if (checkBtn) {
          checkBtn.classList.add('hidden');
          checkBtn.disabled = false;
          checkBtn.className =
            'check-btn inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-semibold bg-sky-600 text-white hover:bg-sky-500 shadow-sm transition-all cursor-pointer hidden';
          checkBtn.innerHTML =
            '<span class="material-symbols-outlined text-[17px] leading-none">check_circle</span> <span>Check</span>';
        }

        if (badge) {
          badge.classList.remove('hidden');
          badge.className =
            'status-valid-badge inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300 dark:ring-1 dark:ring-emerald-500/30';
          badge.title = data.message || 'Credentials verified and valid';
          badge.innerHTML = `
            <span class="material-symbols-outlined text-base leading-none text-emerald-600 dark:text-emerald-400">check_circle</span>
            <span>Valid</span>
          `;
        }

        // Collapse section by default on verified valid credentials
        setSectionCollapseState(config.sectionId, true);

        if (
          serviceKey === 'open_api' &&
          Array.isArray(data.models) &&
          data.models.length > 0
        ) {
          const modelSelect = document.getElementById('open_api_model');
          if (modelSelect) {
            const currentVal = modelSelect.value;
            modelSelect.innerHTML = '';
            data.models.forEach((modelId) => {
              const opt = document.createElement('option');
              opt.value = modelId;
              opt.textContent = modelId;
              if (modelId === currentVal) {
                opt.selected = true;
              }
              modelSelect.appendChild(opt);
            });
            if (!modelSelect.value && data.models.includes('gpt-4o-mini')) {
              modelSelect.value = 'gpt-4o-mini';
            } else if (!modelSelect.value) {
              modelSelect.value = data.models[0];
            }
          }
        }
      } else {
        if (badge) {
          badge.classList.remove('hidden');
          badge.className =
            'status-valid-badge inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 dark:bg-rose-950/80 dark:text-rose-300 dark:ring-1 dark:ring-rose-500/30 max-w-xs truncate';
          badge.title = data.message || 'Validation failed';
          badge.innerHTML = `
            <span class="material-symbols-outlined text-base leading-none text-rose-600 dark:text-rose-400">error</span>
            <span class="truncate">${data.message || 'Invalid'}</span>
          `;
        }

        if (checkBtn) {
          checkBtn.classList.remove('hidden');
          checkBtn.disabled = false;
          checkBtn.className =
            'check-btn inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-semibold bg-sky-600 text-white hover:bg-sky-500 shadow-sm transition-all cursor-pointer';
          checkBtn.innerHTML =
            '<span class="material-symbols-outlined text-[17px] leading-none">check_circle</span> <span>Check</span>';
        }

        // Expand section to show error
        setSectionCollapseState(config.sectionId, false);
      }
    } catch (err) {
      if (badge) {
        badge.classList.remove('hidden');
        badge.className =
          'status-valid-badge inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 dark:bg-rose-950/80 dark:text-rose-300 dark:ring-1 dark:ring-rose-500/30 max-w-xs truncate';
        badge.title = err.message || 'Network error';
        badge.innerHTML = `
          <span class="material-symbols-outlined text-base leading-none text-rose-600 dark:text-rose-400">error</span>
          <span>Network error</span>
        `;
      }
      if (checkBtn) {
        checkBtn.classList.remove('hidden');
        checkBtn.disabled = false;
        checkBtn.className =
          'check-btn inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-semibold bg-sky-600 text-white hover:bg-sky-500 shadow-sm transition-all cursor-pointer';
        checkBtn.innerHTML =
          '<span class="material-symbols-outlined text-[17px] leading-none">check_circle</span> <span>Check</span>';
      }
      setSectionCollapseState(config.sectionId, false);
    }
  }

  // Bind Check buttons
  document.querySelectorAll('.check-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const service = btn.getAttribute('data-service');
      if (service && !btn.disabled) {
        validateService(service, false);
      }
    });
  });

  // Automatically trigger initial validation on page load for all populated sections
  Object.keys(serviceSections).forEach((serviceKey) => {
    validateService(serviceKey, true);
  });
});

