/**
 * API Credentials View Controller.
 * Manages live validation requests, status badge indicators, and dynamic model population.
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
  };

  // Track input modifications for dirty manager
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
    if (!badge) return;

    if (!config.hasValue()) {
      badge.className = 'hidden';
      badge.innerHTML = '';
      return;
    }

    // Show validating spinner state
    badge.className =
      'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-sky-100 text-sky-800 dark:bg-sky-950/80 dark:text-sky-300 dark:ring-1 dark:ring-sky-500/30 animate-pulse';
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
          'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300 dark:ring-1 dark:ring-emerald-500/30';
        badge.title = data.message || 'Valid';
        badge.innerHTML = `<span>✓</span> Valid`;

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
          'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 dark:bg-rose-950/80 dark:text-rose-300 dark:ring-1 dark:ring-rose-500/30 max-w-xs truncate';
        badge.title = data.message || 'Validation failed';
        badge.innerHTML = `<span>✗</span> <span class="truncate">${
          data.message || 'Invalid'
        }</span>`;
      }
    } catch (err) {
      badge.className =
        'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 dark:bg-rose-950/80 dark:text-rose-300 dark:ring-1 dark:ring-rose-500/30 max-w-xs truncate';
      badge.title = err.message || 'Network error';
      badge.innerHTML = `<span>✗</span> Network error`;
    }
  }

  // Bind Re-check buttons
  document.querySelectorAll('.recheck-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const service = btn.getAttribute('data-service');
      if (service) {
        validateService(service);
      }
    });
  });

  // Automatically trigger validation on page load for all populated sections
  Object.keys(serviceSections).forEach((serviceKey) => {
    validateService(serviceKey);
  });
});
