/**
 * API Credentials View Controller.
 * Manages combined Valid/Check button states, auto-collapsing valid sections,
 * and live credential validation probes.
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
      btnId: 'check-btn-bus',
      fields: ['bus_api_key'],
      hasValue: () => {
        const val = document.getElementById('bus_api_key')?.value.trim();
        return Boolean(val);
      },
    },
    train_s3: {
      sectionId: 'section-train_s3',
      btnId: 'check-btn-train_s3',
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
      btnId: 'check-btn-train_live',
      fields: ['train_live_api_key', 'train_live_endpoint'],
      hasValue: () => {
        const key = document.getElementById('train_live_api_key')?.value.trim();
        return Boolean(key);
      },
    },
    open_api: {
      sectionId: 'section-open_api',
      btnId: 'check-btn-open_api',
      fields: ['open_api_key', 'open_api_base_url', 'open_api_model'],
      hasValue: () => {
        const key = document.getElementById('open_api_key')?.value.trim();
        return Boolean(key);
      },
    },
    google_maps: {
      sectionId: 'section-google_maps',
      btnId: 'check-btn-google_maps',
      fields: ['google_maps_api_key', 'google_maps_region'],
      hasValue: () => {
        const key = document.getElementById('google_maps_api_key')?.value.trim();
        return Boolean(key);
      },
    },
  };

  // Section toggle handlers
  document.querySelectorAll('.section-toggle').forEach((header) => {
    header.addEventListener('click', (e) => {
      if (e.target.closest('button, input, select, a')) return;
      const targetId = header.getAttribute('data-target');
      const section = targetId
        ? document.getElementById(targetId)
        : header.closest('.collapsible-section');
      if (section) {
        section.classList.toggle('collapsed');
      }
    });
  });

  function setCombinedButtonState(serviceKey, state, message = '') {
    const config = serviceSections[serviceKey];
    if (!config) return;
    const btn = document.getElementById(config.btnId);
    if (!btn) return;

    if (state === 'valid') {
      btn.disabled = false;
      btn.className =
        'check-btn inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300 dark:ring-1 dark:ring-emerald-500/30 transition-all cursor-pointer';
      btn.innerHTML =
        '<span class="material-symbols-outlined text-[17px] leading-none text-emerald-600 dark:text-emerald-400">check_circle</span> <span>Valid</span>';
      btn.title = message || 'Credentials are valid. Click to re-check.';
    } else if (state === 'check') {
      btn.disabled = false;
      btn.className =
        'check-btn inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-semibold bg-sky-600 text-white hover:bg-sky-500 shadow-sm transition-all cursor-pointer';
      btn.innerHTML =
        '<span class="material-symbols-outlined text-[17px] leading-none">refresh</span> <span>Check</span>';
      btn.title = 'Click to validate updated credentials';
    } else if (state === 'validating') {
      btn.disabled = true;
      btn.className =
        'check-btn inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-sky-100 text-sky-800 dark:bg-sky-950/80 dark:text-sky-300 animate-pulse cursor-wait';
      btn.innerHTML =
        '<span class="material-symbols-outlined text-[17px] leading-none animate-spin">sync</span> <span>Validating...</span>';
      btn.title = 'Validating credentials...';
    } else if (state === 'invalid') {
      btn.disabled = false;
      btn.className =
        'check-btn inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-rose-100 text-rose-800 dark:bg-rose-950/80 dark:text-rose-300 dark:ring-1 dark:ring-rose-500/30 transition-all cursor-pointer';
      btn.innerHTML =
        '<span class="material-symbols-outlined text-[17px] leading-none text-rose-600 dark:text-rose-400">error</span> <span>Invalid</span>';
      btn.title = message || 'Validation failed. Click to re-check.';
    } else {
      // Empty / default state
      btn.disabled = true;
      btn.className =
        'check-btn inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-slate-100 text-slate-400 dark:bg-slate-800/60 dark:text-slate-500 cursor-not-allowed transition-all';
      btn.innerHTML =
        '<span class="material-symbols-outlined text-[17px] leading-none">check_circle</span> <span>Check</span>';
      btn.title = 'Enter credentials to validate';
    }
  }

  // Bind input change listeners: editing switches button to Check
  Object.entries(serviceSections).forEach(([serviceKey, config]) => {
    config.fields.forEach((fieldId) => {
      const el = document.getElementById(fieldId);
      if (el) {
        const onEdit = () => {
          if (config.hasValue()) {
            setCombinedButtonState(serviceKey, 'check');
          } else {
            setCombinedButtonState(serviceKey, 'empty');
          }
        };
        el.addEventListener('input', onEdit);
        el.addEventListener('change', onEdit);
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

    if (!config.hasValue()) {
      setCombinedButtonState(serviceKey, 'empty');
      return;
    }

    setCombinedButtonState(serviceKey, 'validating');

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
        setCombinedButtonState(serviceKey, 'valid', data.message || 'Valid');

        // On initial load, collapse sections that contain valid credentials
        if (isInitialLoad) {
          const section = document.getElementById(config.sectionId);
          if (section) {
            section.classList.add('collapsed');
          }
        }

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
        setCombinedButtonState(
          serviceKey,
          'invalid',
          data.message || 'Validation failed'
        );
      }
    } catch (err) {
      setCombinedButtonState(serviceKey, 'invalid', err.message || 'Network error');
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
