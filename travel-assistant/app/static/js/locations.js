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
    });

    leafletMap.on('click', (e) => {
      if (isReadOnlyMode) return;
      const { lat, lng } = e.latlng;
      setMarkerPosition(lat, lng, false);
      updateCoordinateInputs(lat, lng);
    });
  }

  function setMarkerPosition(lat, lng, panTo = false) {
    const validLat = typeof lat === 'number' && !isNaN(lat) ? lat : DEFAULT_LAT;
    const validLng = typeof lng === 'number' && !isNaN(lng) ? lng : DEFAULT_LNG;
    const newLatLng = [validLat, validLng];

    if (leafletMarker) {
      leafletMarker.setLatLng(newLatLng);
    }

    if (panTo && leafletMap) {
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

      const sourceIcon = isHa ? 'home' : 'pin_drop';
      const sourceIconClass = isHa ? 'text-sky-600 dark:text-sky-400' : 'text-slate-400 dark:text-slate-500';
      const sourceTitle = isHa ? 'Home Assistant location (Read-only)' : 'Custom location';

      const actionButtons = isHa
        ? `<button 
             type="button" 
             class="view-location-btn inline-flex items-center justify-center w-7 h-7 rounded-lg bg-sky-50 text-sky-600 hover:bg-sky-100 hover:text-sky-700 dark:bg-sky-950/50 dark:text-sky-400 dark:hover:bg-sky-900/60 transition-colors cursor-pointer"
             data-index="${index}"
             title="View location details"
             aria-label="View location details"
           >
             <span class="material-symbols-outlined text-[17px] leading-none">visibility</span>
           </button>`
        : `<div class="flex items-center gap-1.5">
             <button 
               type="button" 
               class="edit-location-btn inline-flex items-center justify-center w-7 h-7 rounded-lg bg-sky-50 text-sky-600 hover:bg-sky-100 hover:text-sky-700 dark:bg-sky-950/50 dark:text-sky-400 dark:hover:bg-sky-900/60 transition-colors cursor-pointer"
               data-index="${index}"
               title="Edit location"
               aria-label="Edit location"
             >
               <span class="material-symbols-outlined text-[17px] leading-none">edit</span>
             </button>
             <button 
               type="button" 
               class="delete-location-btn inline-flex items-center justify-center w-7 h-7 rounded-lg bg-rose-50 text-rose-600 hover:bg-rose-100 hover:text-rose-700 dark:bg-rose-950/50 dark:text-rose-400 dark:hover:bg-rose-900/60 transition-colors cursor-pointer"
               data-index="${index}"
               title="Delete location"
               aria-label="Delete location"
             >
               <span class="material-symbols-outlined text-[17px] leading-none">delete</span>
             </button>
           </div>`;

      return [
        gridjs.html(`
          <div class="flex items-center gap-2.5">
            <span class="material-symbols-outlined text-lg ${sourceIconClass} shrink-0" title="${escapeHtml(sourceTitle)}">${sourceIcon}</span>
            <span class="font-medium text-slate-900 dark:text-slate-100">${escapeHtml(item.name)}</span>
          </div>
        `),
        gridjs.html(`
          <code class="px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 text-xs font-mono">${formattedLat}</code>
        `),
        gridjs.html(`
          <code class="px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 text-xs font-mono">${formattedLng}</code>
        `),
        gridjs.html(actionButtons),
      ];
    });
  }

  const columnsConfig = [
    { name: 'Name', width: 'auto', sort: true },
    { name: 'Latitude', width: '150px', sort: true },
    { name: 'Longitude', width: '150px', sort: true },
    { name: 'Actions', width: '100px', sort: false },
  ];

  // Initialise Grid.js instance
  const grid = new gridjs.Grid({
    columns: columnsConfig,
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

    if (gridContainer && gridContainer.querySelector('.gridjs-container')) {
      if (stagedLocations.length <= 10) {
        gridContainer.querySelector('.gridjs-container').setAttribute('data-single-page', 'true');
      } else {
        gridContainer.querySelector('.gridjs-container').removeAttribute('data-single-page');
      }
    }

    grid.updateConfig({
      columns: columnsConfig,
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

  const normalInputClass =
    'w-full px-3.5 py-2 rounded-xl border border-slate-300 bg-white text-sm text-slate-900 placeholder-slate-400 focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-500/20 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 dark:placeholder-slate-500 transition-colors';
  const readOnlyInputClass =
    'w-full px-3.5 py-2 rounded-xl border border-slate-200 bg-slate-100 text-sm font-medium text-slate-400 dark:border-slate-700/80 dark:bg-slate-800 dark:text-slate-500 cursor-not-allowed transition-colors select-none';

  // Open modal helper
  function openModal(mode = 'add', index = -1) {
    if (modalError) modalError.classList.add('hidden');
    editIndexInput.value = index;
    isReadOnlyMode = mode === 'view';

    if (isReadOnlyMode) {
      const item = stagedLocations[index];
      modalTitle.textContent = 'View Location (Read-Only)';
      modalIcon.textContent = 'home';
      if (haNotice) haNotice.classList.remove('hidden');

      nameInput.value = item ? item.name : '';
      nameInput.disabled = true;
      nameInput.readOnly = true;
      nameInput.className = readOnlyInputClass;

      const lat = item ? parseFloat(item.latitude) || DEFAULT_LAT : DEFAULT_LAT;
      const lng = item ? parseFloat(item.longitude) || DEFAULT_LNG : DEFAULT_LNG;
      latInput.value = formatCoord(lat);
      latInput.disabled = true;
      latInput.readOnly = true;
      latInput.className = readOnlyInputClass;

      lngInput.value = formatCoord(lng);
      lngInput.disabled = true;
      lngInput.readOnly = true;
      lngInput.className = readOnlyInputClass;

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
      nameInput.className = normalInputClass;

      const lat = parseFloat(item.latitude) || DEFAULT_LAT;
      const lng = parseFloat(item.longitude) || DEFAULT_LNG;
      latInput.value = formatCoord(lat);
      latInput.disabled = false;
      latInput.readOnly = false;
      latInput.className = normalInputClass;

      lngInput.value = formatCoord(lng);
      lngInput.disabled = false;
      lngInput.readOnly = false;
      lngInput.className = normalInputClass;

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
      nameInput.className = normalInputClass;

      latInput.value = formatCoord(DEFAULT_LAT);
      latInput.disabled = false;
      latInput.readOnly = false;
      latInput.className = normalInputClass;

      lngInput.value = formatCoord(DEFAULT_LNG);
      lngInput.disabled = false;
      lngInput.readOnly = false;
      lngInput.className = normalInputClass;

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
      const isHa =
        !isNaN(idx) && idx >= 0 && idx < stagedLocations.length
          ? Boolean(stagedLocations[idx].ha)
          : false;
      const existingId =
        !isNaN(idx) && idx >= 0 && idx < stagedLocations.length
          ? stagedLocations[idx].id
          : undefined;

      const entry = {
        ...(existingId ? { id: existingId } : {}),
        name,
        latitude: lat,
        longitude: lng,
        ha: isHa,
      };

      if (!isNaN(idx) && idx >= 0 && idx < stagedLocations.length) {
        stagedLocations[idx] = entry;
      } else {
        stagedLocations.push(entry);
      }

      syncState();
      closeModal();
    });
  }

  // Row button click handlers via event delegation
  document.addEventListener('click', (e) => {
    const editBtn = e.target.closest('.edit-location-btn');
    if (editBtn) {
      const idx = parseInt(editBtn.getAttribute('data-index'), 10);
      if (!isNaN(idx)) openModal('edit', idx);
      return;
    }

    const viewBtn = e.target.closest('.view-location-btn');
    if (viewBtn) {
      const idx = parseInt(viewBtn.getAttribute('data-index'), 10);
      if (!isNaN(idx)) openModal('view', idx);
      return;
    }

    const deleteBtn = e.target.closest('.delete-location-btn');
    if (deleteBtn) {
      const idx = parseInt(deleteBtn.getAttribute('data-index'), 10);
      if (!isNaN(idx) && idx >= 0 && idx < stagedLocations.length) {
        stagedLocations.splice(idx, 1);
        syncState();
      }
      return;
    }
  });
});
