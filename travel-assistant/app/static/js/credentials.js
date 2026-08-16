/**
 * API Credentials View Controller.
 * Manages collapsible service sections, live validation requests,
 * green 'Valid' status indicators, and on-change revealed 'Check' buttons.
 */
document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('credentials-form');
  if (!form) return;

  const validateUrl =
    form.dataset.validateUrl ||
    (window.location.pathname.replace(/\/$/, '') + '/validate');

  const serviceSections = {
    bus: {
      badgeId: 'status-badge-bus',
      fields: ['bus_api_key'],
      hasValue: () => {
        const val = document.getElementById('bus_api_key')?.value.trim();
        return Boolean(val);
      },
    },
    train_s3: {
      badgeId: 'status-badge-train_s3',
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
      badgeId: 'status-badge-train_live',
      fields: ['train_live_api_key', 'train_live_endpoint'],
      hasValue: () => {
        const key = document.getElementById('train_live_api_key')?.value.trim();
        return Boolean(key);
      },
    },
    open_api: {
      badgeId: 'status-badge-open_api',
      fields: ['open_api_key', 'open_api_base_url'],
      hasValue: () => {
        const key = document.getElementById('open_api_key')?.value.trim();
        return Boolean(key);
      },
    },
    google_maps: {
      badgeId: 'status-badge-google_maps',
      fields: ['google_maps_api_key', 'google_maps_region'],
      hasValue: () => {
        const key = document.getElementById('google_maps_api_key')?.value.trim();
        return Boolean(key);
      },
    },
  };

  function toggleSection(serviceKey, forceState) {
    const content = document.getElementById(`collapsible-content-${serviceKey}`);
    const btn = document.querySelector(`.collapse-toggle-btn[data-service="${serviceKey}"]`);
    const icon = btn ? btn.querySelector('.collapse-icon') : null;
    if (!content) return;

    const isCurrentlyHidden = content.classList.contains('hidden');
    const shouldExpand = forceState !== undefined ? forceState : isCurrentlyHidden;

    if (shouldExpand) {
      content.classList.remove('hidden');
      if (icon) icon.textContent = 'keyboard_arrow_down';
    } else {
      content.classList.add('hidden');
      if (icon) icon.textContent = 'chevron_right';
    }
  }

  // Bind collapse toggle buttons
  document.querySelectorAll('.collapse-toggle-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const serviceKey = btn.getAttribute('data-service');
      if (serviceKey) {
        toggleSection(serviceKey);
      }
    });
  });

  function onSectionModified(serviceKey) {
    const badge = document.getElementById(serviceSections[serviceKey]?.badgeId);
    const checkBtn = document.querySelector(`.check-btn[data-service="${serviceKey}"]`);

    if (badge) {
      badge.className = 'hidden';
      badge.innerHTML = '';
    }
    if (checkBtn) {
      checkBtn.classList.remove('hidden');
    }
  }

  // Bind input change listeners to swap Valid badge with Check button
  Object.entries(serviceSections).forEach(([serviceKey, config]) => {
    config.fields.forEach((fieldId) => {
      const el = document.getElementById(fieldId);
      if (el) {
        el.addEventListener('input', () => onSectionModified(serviceKey));
        el.addEventListener('change', () => onSectionModified(serviceKey));
      }
    });
  });

  // Track form dirty status
  if (window.ConfigDirtyManager) {
    form.addEventListener('input', () => {
      window.ConfigDirtyManager.markDirty();
    });

    window.ConfigDirtyManager.registerDiscardHandler(() => {
      form.reset();
      Object.keys(serviceSections).forEach((serviceKey) => {
        validateService(serviceKey);
      });
    });

    form.addEventListener('submit', () => {
      window.ConfigDirtyManager.markSubmitting();
    });
  }

  async function validateService(serviceKey) {
    const config = serviceSections[serviceKey];
    if (!config) return;
    const badge = document.getElementById(config.badgeId);
    const checkBtn = document.querySelector(`.check-btn[data-service="${serviceKey}"]`);
    if (!badge) return;

    if (!config.hasValue()) {
      badge.className = 'hidden';
      badge.innerHTML = '';
      if (checkBtn) checkBtn.classList.add('hidden');
      return;
    }

    // Show validating spinner state and hide Check button
    if (checkBtn) checkBtn.classList.add('hidden');
    badge.className =
      'inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-sky-100 text-sky-800 dark:bg-sky-950/80 dark:text-sky-300 dark:ring-1 dark:ring-sky-500/30 animate-pulse';
    badge.innerHTML = `
      <span class="inline-block w-1.5 h-1.5 rounded-full bg-sky-500 animate-ping"></span>
      Validating...
    `;

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
        badge.className =
          'inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300 dark:ring-1 dark:ring-emerald-500/30';
        badge.title = data.message || 'Valid';
        badge.innerHTML = `<span>✓</span> Valid`;
        if (checkBtn) checkBtn.classList.add('hidden');

        // Collapse section by default when check is passing
        toggleSection(serviceKey, false);

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
        badge.className =
          'inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 dark:bg-rose-950/80 dark:text-rose-300 dark:ring-1 dark:ring-rose-500/30 max-w-xs truncate';
        badge.title = data.message || 'Validation failed';
        badge.innerHTML = `<span>✗</span> <span class="truncate">${
          data.message || 'Invalid'
        }</span>`;
        if (checkBtn) checkBtn.classList.remove('hidden');

        // Expand section to show error
        toggleSection(serviceKey, true);
      }
    } catch (err) {
      badge.className =
        'inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 dark:bg-rose-950/80 dark:text-rose-300 dark:ring-1 dark:ring-rose-500/30 max-w-xs truncate';
      badge.title = err.message || 'Network error';
      badge.innerHTML = `<span>✗</span> Network error`;
      if (checkBtn) checkBtn.classList.remove('hidden');
      toggleSection(serviceKey, true);
    }
  }

  // Bind Check buttons
  document.querySelectorAll('.check-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const service = btn.getAttribute('data-service');
      if (service) {
        validateService(service);
      }
    });
  });

  // Automatically trigger initial validation on page load for all populated sections
  Object.keys(serviceSections).forEach((serviceKey) => {
    validateService(serviceKey);
  });
});
