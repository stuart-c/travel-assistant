/**
 * Locations Configuration Controller.
 * 
 * Manages client-side staged state for configured geographic locations
 * using Grid.js and Leaflet interactive map with bidirectional coordinate synchronisation.
 * Provides read-only viewing protections for Home Assistant synchronised locations.
 */

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('locations-form');
  if (!form) return;

  const dataEl = document.getElementById('initial-locations-data');
  let initialRaw = [];
  try {
    initialRaw = dataEl && dataEl.textContent ? JSON.parse(dataEl.textContent) : [];
  } catch (e) {
    console.error('Failed to parse initial locations data:', e);
  }

  // In-memory staged state
  let stagedLocations = JSON.parse(JSON.stringify(initialRaw || []));
  const initialSnapshot = JSON.stringify(stagedLocations);

  const hiddenInput = document.getElementById('locations_json');
  const emptyState = document.getElementById('locations-grid-empty-state');
  const gridContainer = document.getElementById('locations-grid-wrapper');

  // Modal elements
  const modal = document.getElementById('location-modal');
  const openAddBtn = document.getElementById('open-add-location-modal-btn');
  const emptyAddBtn = document.getElementById('empty-add-location-btn');
  const closeModalBtn = document.getElementById('close-location-modal-btn');
  const cancelModalBtn = document.getElementById('cancel-location-modal-btn');
  const confirmBtn = document.getElementById('confirm-location-btn');
  const modalTitle = document.getElementById('location-modal-title');
  const modalIcon = document.getElementById('location-modal-icon');
  const editIndexInput = document.getElementById('edit-location-index');
  const nameInput = document.getElementById('location_name');
  const latInput = document.getElementById('location_latitude');
  const lngInput = document.getElementById('location_longitude');
  const modalError = document.getElementById('location-modal-error');
  const haNotice = document.getElementById('location-ha-readonly-notice');

  // Map state
  let leafletMap = null;
  let leafletMarker = null;
  let isReadOnlyMode = false;
  const DEFAULT_LAT = 51.5074;
  const DEFAULT_LNG = -0.1278;
  const DEFAULT_ZOOM = 13;

  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function formatCoord(val) {
    const num = parseFloat(val);
    return isNaN(num) ? '0.000000' : num.toFixed(6);
  }

  function updateCoordinateInputs(lat, lng) {
    if (isReadOnlyMode) return;
    latInput.value = formatCoord(lat);
    lngInput.value = formatCoord(lng);
  }

  function initialiseMap() {
    if (leafletMap) return;

    const mapContainer = document.getElementById('location-map');
    if (!mapContainer || typeof L === 'undefined') return;

    leafletMap = L.map('location-map').setView([DEFAULT_LAT, DEFAULT_LNG], DEFAULT_ZOOM);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
    }).addTo(leafletMap);

    leafletMarker = L.marker([DEFAULT_LAT, DEFAULT_LNG], {
      draggable: !isReadOnlyMode,
      autoPan: true,
    }).addTo(leafletMap);

    leafletMarker.on('drag', (e) => {
      if (isReadOnlyMode) return;
      const pos = e.target.getLatLng();
      updateCoordinateInputs(pos.lat, pos.lng);
    });

    leafletMarker.on('dragend', (e) => {
      if (isReadOnlyMode) return;
      const pos = e.target.getLatLng();
      updateCoordinateInputs(pos.lat, pos.lng);
      leafletMap.panTo(pos);
    });

    leafletMap.on('click', (e) => {
      if (isReadOnlyMode) return;
      setMarkerPosition(e.latlng.lat, e.latlng.lng, true);
    });
  }

  function setMarkerPosition(lat, lng, panTo = false) {
    if (!leafletMarker || !leafletMap) return;
    const safeLat = parseFloat(lat);
    const safeLng = parseFloat(lng);
    if (isNaN(safeLat) || isNaN(safeLng)) return;

    const newLatLng = [safeLat, safeLng];
    leafletMarker.setLatLng(newLatLng);
    if (!isReadOnlyMode) {
      updateCoordinateInputs(safeLat, safeLng);
    }

    if (panTo) {
      leafletMap.panTo(newLatLng);
    }
  }

  // Handle manual coordinate input changes
  function onCoordinateInputChange() {
    if (isReadOnlyMode) return;
    const lat = parseFloat(latInput.value);
    const lng = parseFloat(lngInput.value);
    if (!isNaN(lat) && !isNaN(lng) && lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180) {
      if (leafletMarker && leafletMap) {
        leafletMarker.setLatLng([lat, lng]);
        leafletMap.panTo([lat, lng]);
      }
    }
  }

  if (latInput) latInput.addEventListener('input', onCoordinateInputChange);
  if (lngInput) lngInput.addEventListener('input', onCoordinateInputChange);

  // Format data rows for Grid.js
  function formatGridData(items) {
    return items.map((item, index) => {
      const formattedLat = formatCoord(item.latitude);
      const formattedLng = formatCoord(item.longitude);
      const isHa = Boolean(item.ha);

      const sourceBadge = isHa
        ? `<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-sky-100 text-sky-800 dark:bg-sky-900/60 dark:text-sky-300">
             <span class="material-symbols-outlined text-xs">home</span>
             Home Assistant
           </span>`
        : `<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300">
             Custom
           </span>`;

      const actionButtons = isHa
        ? `<button 
             type="button" 
             class="view-location-btn inline-flex items-center gap-1 px-2.5 py-1 text-xs font-semibold rounded-lg text-sky-600 hover:text-sky-900 hover:bg-sky-50 dark:text-sky-400 dark:hover:bg-sky-950/60 transition-colors cursor-pointer"
             data-index="${index}"
             title="View Location Details"
           >
             <span class="material-symbols-outlined text-xs leading-none">visibility</span>
             View
           </button>`
        : `<div class="flex items-center gap-1.5">
             <button 
               type="button" 
               class="edit-location-btn inline-flex items-center gap-1 px-2.5 py-1 text-xs font-semibold rounded-lg text-slate-600 hover:text-slate-900 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800 transition-colors cursor-pointer"
               data-index="${index}"
               title="Edit Location"
             >
               <span class="material-symbols-outlined text-xs leading-none">edit</span>
               Edit
             </button>
             <button 
               type="button" 
               class="delete-location-btn inline-flex items-center gap-1 px-2.5 py-1 text-xs font-semibold rounded-lg text-rose-600 hover:text-white hover:bg-rose-600 dark:text-rose-400 dark:hover:bg-rose-700/80 transition-colors cursor-pointer"
               data-index="${index}"
               title="Delete Location"
             >
               <span class="material-symbols-outlined text-xs leading-none">delete</span>
               Delete
             </button>
           </div>`;

      return [
        gridjs.html(`
          <div class="flex items-center gap-2">
            <span class="material-symbols-outlined text-base text-sky-500">pin_drop</span>
            <span class="font-medium text-slate-900 dark:text-slate-100">${escapeHtml(item.name)}</span>
          </div>
        `),
        gridjs.html(`
          <code class="px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 text-xs font-mono">${formattedLat}</code>
        `),
        gridjs.html(`
          <code class="px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 text-xs font-mono">${formattedLng}</code>
        `),
        gridjs.html(sourceBadge),
        gridjs.html(actionButtons),
      ];
    });
  }

  // Initialise Grid.js instance
  const grid = new gridjs.Grid({
    columns: [
      { name: 'Name', width: 'auto' },
      { name: 'Latitude', width: '130px' },
      { name: 'Longitude', width: '130px' },
      { name: 'Source', width: '150px' },
      { name: 'Actions', width: '150px', sort: false },
    ],
    data: formatGridData(stagedLocations),
    sort: true,
    search: {
      enabled: true,
      placeholder: 'Search locations...',
    },
    pagination: {
      enabled: true,
      limit: 10,
      summary: true,
    },
    className: {
      table: 'w-full text-left border-collapse text-sm',
      thead: 'bg-slate-50 dark:bg-slate-800/80 text-slate-700 dark:text-slate-300 uppercase text-xs tracking-wider border-b border-slate-200 dark:border-slate-800 font-semibold',
      tbody: 'divide-y divide-slate-100 dark:divide-slate-800 text-slate-700 dark:text-slate-300',
      search: 'w-full sm:w-72 mb-4',
    },
    language: {
      search: {
        placeholder: 'Search locations...',
      },
      pagination: {
        previous: 'Previous',
        next: 'Next',
        showing: 'Showing',
        of: 'of',
        to: 'to',
        results: 'locations',
      },
      noRecordsFound: 'No matching locations found',
    },
  });

  if (gridContainer) {
    grid.render(gridContainer);
  }

  function syncState() {
    if (hiddenInput) {
      hiddenInput.value = JSON.stringify(stagedLocations);
    }

    if (stagedLocations.length === 0) {
      if (emptyState) emptyState.classList.remove('hidden');
      if (gridContainer) gridContainer.classList.add('hidden');
    } else {
      if (emptyState) emptyState.classList.add('hidden');
      if (gridContainer) gridContainer.classList.remove('hidden');
    }

    grid.updateConfig({
      data: formatGridData(stagedLocations),
    }).forceRender();

    // Trigger DirtyManager check
    if (window.ConfigDirtyManager) {
      const currentJson = JSON.stringify(stagedLocations);
      if (currentJson !== initialSnapshot) {
        window.ConfigDirtyManager.markDirty();
      } else {
        window.ConfigDirtyManager.clearDirty();
      }
    }
  }

  // Initial sync
  syncState();

  // Register discard handler
  if (window.ConfigDirtyManager) {
    window.ConfigDirtyManager.registerDiscardHandler(() => {
      stagedLocations = JSON.parse(initialSnapshot);
      syncState();
    });
  }

  // Open modal helper
  function openModal(mode = 'add', index = -1) {
    if (modalError) modalError.classList.add('hidden');
    editIndexInput.value = index;
    isReadOnlyMode = mode === 'view';

    if (isReadOnlyMode) {
      const item = stagedLocations[index];
      modalTitle.textContent = 'View Location';
      modalIcon.textContent = 'visibility';
      if (haNotice) haNotice.classList.remove('hidden');

      nameInput.value = item ? item.name : '';
      nameInput.disabled = true;
      nameInput.readOnly = true;

      const lat = item ? parseFloat(item.latitude) || DEFAULT_LAT : DEFAULT_LAT;
      const lng = item ? parseFloat(item.longitude) || DEFAULT_LNG : DEFAULT_LNG;
      latInput.value = formatCoord(lat);
      latInput.disabled = true;
      latInput.readOnly = true;

      lngInput.value = formatCoord(lng);
      lngInput.disabled = true;
      lngInput.readOnly = true;

      if (confirmBtn) confirmBtn.classList.add('hidden');
      if (cancelModalBtn) cancelModalBtn.textContent = 'Close';

      if (modal && typeof modal.showModal === 'function') {
        modal.showModal();
      }

      setTimeout(() => {
        initialiseMap();
        if (leafletMap) {
          leafletMap.invalidateSize();
          setMarkerPosition(lat, lng, true);
          leafletMap.setView([lat, lng], 14);
          if (leafletMarker && leafletMarker.dragging) {
            leafletMarker.dragging.disable();
          }
        }
      }, 100);
    } else if (mode === 'edit' && index >= 0 && index < stagedLocations.length) {
      const item = stagedLocations[index];
      modalTitle.textContent = 'Edit Location';
      modalIcon.textContent = 'edit';
      if (haNotice) haNotice.classList.add('hidden');

      nameInput.value = item.name || '';
      nameInput.disabled = false;
      nameInput.readOnly = false;

      const lat = parseFloat(item.latitude) || DEFAULT_LAT;
      const lng = parseFloat(item.longitude) || DEFAULT_LNG;
      latInput.value = formatCoord(lat);
      latInput.disabled = false;
      latInput.readOnly = false;

      lngInput.value = formatCoord(lng);
      lngInput.disabled = false;
      lngInput.readOnly = false;

      if (confirmBtn) confirmBtn.classList.remove('hidden');
      if (cancelModalBtn) cancelModalBtn.textContent = 'Cancel';

      if (modal && typeof modal.showModal === 'function') {
        modal.showModal();
      }

      setTimeout(() => {
        initialiseMap();
        if (leafletMap) {
          leafletMap.invalidateSize();
          setMarkerPosition(lat, lng, true);
          leafletMap.setView([lat, lng], 14);
          if (leafletMarker && leafletMarker.dragging) {
            leafletMarker.dragging.enable();
          }
        }
      }, 100);
    } else {
      modalTitle.textContent = 'Add New Location';
      modalIcon.textContent = 'pin_drop';
      if (haNotice) haNotice.classList.add('hidden');

      nameInput.value = '';
      nameInput.disabled = false;
      nameInput.readOnly = false;

      latInput.value = formatCoord(DEFAULT_LAT);
      latInput.disabled = false;
      latInput.readOnly = false;

      lngInput.value = formatCoord(DEFAULT_LNG);
      lngInput.disabled = false;
      lngInput.readOnly = false;

      if (confirmBtn) confirmBtn.classList.remove('hidden');
      if (cancelModalBtn) cancelModalBtn.textContent = 'Cancel';

      if (modal && typeof modal.showModal === 'function') {
        modal.showModal();
      }

      setTimeout(() => {
        initialiseMap();
        if (leafletMap) {
          leafletMap.invalidateSize();
          setMarkerPosition(DEFAULT_LAT, DEFAULT_LNG, true);
          leafletMap.setView([DEFAULT_LAT, DEFAULT_LNG], DEFAULT_ZOOM);
          if (leafletMarker && leafletMarker.dragging) {
            leafletMarker.dragging.enable();
          }
        }
      }, 100);
    }
  }

  function closeModal() {
    if (modal && typeof modal.close === 'function') {
      modal.close();
    }
  }

  if (openAddBtn) openAddBtn.addEventListener('click', () => openModal('add'));
  if (emptyAddBtn) emptyAddBtn.addEventListener('click', () => openModal('add'));
  if (closeModalBtn) closeModalBtn.addEventListener('click', closeModal);
  if (cancelModalBtn) cancelModalBtn.addEventListener('click', closeModal);

  // Save location from modal
  if (confirmBtn) {
    confirmBtn.addEventListener('click', () => {
      if (isReadOnlyMode) return;

      const name = nameInput.value.trim();
      const lat = parseFloat(latInput.value);
      const lng = parseFloat(lngInput.value);

      if (!name || isNaN(lat) || isNaN(lng) || lat < -90 || lat > 90 || lng < -180 || lng > 180) {
        if (modalError) modalError.classList.remove('hidden');
        return;
      }

      const idx = parseInt(editIndexInput.value, 10);
      const isHa = !isNaN(idx) && idx >= 0 && idx < stagedLocations.length ? Boolean(stagedLocations[idx].ha) : false;

      const entry = {
        name,
        latitude: parseFloat(lat.toFixed(6)),
        longitude: parseFloat(lng.toFixed(6)),
        ha: isHa,
      };

      if (!isNaN(idx) && idx >= 0 && idx < stagedLocations.length) {
        stagedLocations[idx] = entry;
      } else {
        stagedLocations.push(entry);
      }

      closeModal();
      syncState();
    });
  }

  // Row event delegation for View, Edit, and Delete
  document.addEventListener('click', (e) => {
    const viewBtn = e.target.closest('.view-location-btn');
    if (viewBtn) {
      const idx = parseInt(viewBtn.getAttribute('data-index'), 10);
      if (!isNaN(idx) && idx >= 0 && idx < stagedLocations.length) {
        openModal('view', idx);
      }
      return;
    }

    const editBtn = e.target.closest('.edit-location-btn');
    if (editBtn) {
      const idx = parseInt(editBtn.getAttribute('data-index'), 10);
      if (!isNaN(idx) && idx >= 0 && idx < stagedLocations.length) {
        openModal('edit', idx);
      }
      return;
    }

    const deleteBtn = e.target.closest('.delete-location-btn');
    if (deleteBtn) {
      const idx = parseInt(deleteBtn.getAttribute('data-index'), 10);
      if (!isNaN(idx) && idx >= 0 && idx < stagedLocations.length) {
        if (stagedLocations[idx] && stagedLocations[idx].ha) {
          return; // Synced locations cannot be deleted
        }
        stagedLocations.splice(idx, 1);
        syncState();
      }
    }
  });
});
