/**
 * Timetables View Controller.
 * Manages Grid.js data table rendering, in-memory staged timetable schedules,
 * full-width matrix grid editor, stop search autocompletion, multi-column trip duplication,
 * and chronological timing validation.
 */
document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('timetables-form');
  if (!form) return;

  const dataEl = document.getElementById('initial-timetables-data');
  let initialRaw = [];
  try {
    initialRaw = dataEl ? JSON.parse(dataEl.textContent || '[]') : [];
  } catch (e) {
    console.error('Failed to parse initial timetables data:', e);
  }

  // Transport mode definitions
  const TRANSPORT_MODES = {
    bus: {
      label: 'Bus',
      icon: 'directions_bus',
      badgeClass:
        'bg-sky-100 text-sky-800 dark:bg-sky-950/80 dark:text-sky-300 dark:ring-1 dark:ring-sky-500/30',
    },
    rail: {
      label: 'Train / Rail',
      icon: 'train',
      badgeClass:
        'bg-indigo-100 text-indigo-800 dark:bg-indigo-950/80 dark:text-indigo-300 dark:ring-1 dark:ring-indigo-500/30',
    },
    tram: {
      label: 'Tram',
      icon: 'tram',
      badgeClass:
        'bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-300 dark:ring-1 dark:ring-amber-500/30',
    },
    metro: {
      label: 'Metro',
      icon: 'subway',
      badgeClass:
        'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300 dark:ring-1 dark:ring-emerald-500/30',
    },
    ferry: {
      label: 'Ferry',
      icon: 'directions_boat',
      badgeClass:
        'bg-cyan-100 text-cyan-800 dark:bg-cyan-950/80 dark:text-cyan-300 dark:ring-1 dark:ring-cyan-500/30',
    },
    air: {
      label: 'Flight',
      icon: 'flight',
      badgeClass:
        'bg-purple-100 text-purple-800 dark:bg-purple-950/80 dark:text-purple-300 dark:ring-1 dark:ring-purple-500/30',
    },
  };

  // Sanitise initial items into standard schema format
  function normaliseItem(item) {
    let content = { stops: [], trips: [] };
    if (item.content) {
      if (typeof item.content === 'string') {
        try {
          content = JSON.parse(item.content);
        } catch (e) {
          content = { stops: [], trips: [] };
        }
      } else if (typeof item.content === 'object' && item.content !== null) {
        content = item.content;
      }
    }

    const stops = Array.isArray(content.stops) ? content.stops : [];
    const trips = Array.isArray(content.trips) ? content.trips : [];

    // Ensure all trips have matching time array lengths
    trips.forEach((trip) => {
      if (!Array.isArray(trip.times)) {
        trip.times = [];
      }
      while (trip.times.length < stops.length) {
        trip.times.push('');
      }
    });

    return {
      id: item.id || null,
      name: item.name || '',
      transport_type: (item.transport_type || 'bus').toLowerCase(),
      start_date: item.start_date || '',
      end_date: item.end_date || '',
      monday: item.monday !== undefined ? Boolean(item.monday) : true,
      tuesday: item.tuesday !== undefined ? Boolean(item.tuesday) : true,
      wednesday: item.wednesday !== undefined ? Boolean(item.wednesday) : true,
      thursday: item.thursday !== undefined ? Boolean(item.thursday) : true,
      friday: item.friday !== undefined ? Boolean(item.friday) : true,
      saturday: item.saturday !== undefined ? Boolean(item.saturday) : true,
      sunday: item.sunday !== undefined ? Boolean(item.sunday) : true,
      bank_holiday:
        item.bank_holiday !== undefined ? Boolean(item.bank_holiday) : true,
      content: {
        stops,
        trips,
      },
    };
  }

  // In-memory staged state
  let stagedTimetables = (initialRaw || []).map(normaliseItem);
  const initialSnapshot = JSON.stringify(stagedTimetables);
  let currentEditIndex = -1;
  let activeEditorIndex = -1;
  const selectedTripIndices = new Set();

  const hiddenInput = document.getElementById('timetables_json');
  const emptyState = document.getElementById('grid-empty-state');
  const gridContainer = document.getElementById('timetables-grid-wrapper');

  // Views
  const listView = document.getElementById('timetables-list-view');
  const editorView = document.getElementById('timetable-editor-view');
  const editorBreadcrumbName = document.getElementById('editor-breadcrumb-name');
  const editorTitle = document.getElementById('editor-title');
  const editorModeBadge = document.getElementById('editor-mode-badge');
  const editorModeIcon = document.getElementById('editor-mode-icon');
  const editorModeText = document.getElementById('editor-mode-text');
  const editorBackBtn = document.getElementById('editor-back-btn');
  const editorBackLink = document.getElementById('editor-back-link');
  const matrixMount = document.getElementById('timetable-matrix-mount');
  const validationBanner = document.getElementById('grid-validation-banner');

  // Editor Actions
  const addTripBtn = document.getElementById('editor-add-trip-btn');
  const clearTripsBtn = document.getElementById('editor-clear-trips-btn');
  const selectionBar = document.getElementById('editor-selection-bar');
  const selectionCountText = document.getElementById('selection-count-text');
  const retimeSelectedBtn = document.getElementById('editor-retime-selected-btn');
  const deleteSelectedBtn = document.getElementById('editor-delete-selected-btn');
  const deselectBtn = document.getElementById('editor-deselect-btn');

  // Modal elements (Add/Edit Timetable Metadata)
  const timetableModal = document.getElementById('timetable-modal');
  const openAddBtn = document.getElementById('open-add-modal-btn');
  const emptyAddBtn = document.getElementById('empty-add-btn');
  const closeModalBtn = document.getElementById('close-modal-btn');
  const cancelModalBtn = document.getElementById('cancel-modal-btn');
  const confirmBtn = document.getElementById('confirm-timetable-btn');
  const modalTitle = document.getElementById('modal-title');
  const modalIcon = document.getElementById('modal-icon');
  const modalNameInput = document.getElementById('modal_name');
  const modalTransportTypeSelect = document.getElementById('modal_transport_type');
  const modalStartDateInput = document.getElementById('modal_start_date');
  const modalEndDateInput = document.getElementById('modal_end_date');
  const modalError = document.getElementById('modal-validation-error');

  // Retime Modal elements
  const retimeModal = document.getElementById('retime-modal');
  const closeRetimeBtn = document.getElementById('close-retime-btn');
  const cancelRetimeBtn = document.getElementById('cancel-retime-btn');
  const confirmRetimeBtn = document.getElementById('confirm-retime-btn');
  const retimeSingleOptions = document.getElementById('retime-single-trip-options');
  const retimeMethodOffset = document.getElementById('retime-method-offset');
  const retimeMethodStartTime = document.getElementById('retime-method-starttime');
  const retimeMethodOffsetLbl = document.getElementById('retime-method-offset-lbl');
  const retimeMethodStartTimeLbl = document.getElementById('retime-method-starttime-lbl');
  const retimeStartTimeContainer = document.getElementById('retime-starttime-container');
  const retimeStartTimeInput = document.getElementById('retime_start_time');
  const retimeOffsetContainer = document.getElementById('retime-offset-container');
  const retimeOffsetInput = document.getElementById('retime_offset_minutes');
  const retimeCopyCountInput = document.getElementById('retime_copy_count');
  const retimePreviewText = document.getElementById('retime-preview-text');
  const retimeError = document.getElementById('retime-validation-error');
  let targetRetimeIndices = [];

  // Day pill inputs
  const dayKeys = [
    'monday',
    'tuesday',
    'wednesday',
    'thursday',
    'friday',
    'saturday',
    'sunday',
    'bank_holiday',
  ];
  const dayCheckboxes = {};
  dayKeys.forEach((key) => {
    dayCheckboxes[key] = document.getElementById(`modal_${key}`);
  });

  // Quick select helper buttons
  const btnSelectAll = document.getElementById('days-select-all');
  const btnSelectWeekdays = document.getElementById('days-select-weekdays');
  const btnSelectWeekends = document.getElementById('days-select-weekends');
  const btnClearAll = document.getElementById('days-clear-all');

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // Parse HH:MM into minutes from midnight
  function timeToMinutes(timeStr) {
    if (!timeStr || typeof timeStr !== 'string') return null;
    const parts = timeStr.trim().split(':');
    if (parts.length < 2) return null;
    const h = parseInt(parts[0], 10);
    const m = parseInt(parts[1], 10);
    if (isNaN(h) || isNaN(m)) return null;
    return h * 60 + m;
  }

  // Format minutes from midnight into HH:MM
  function minutesToTime(totalMinutes) {
    let normalized = totalMinutes % (24 * 60);
    if (normalized < 0) normalized += 24 * 60;
    const h = Math.floor(normalized / 60);
    const m = normalized % 60;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  }

  // Add minutes to HH:MM string
  function shiftTime(timeStr, deltaMinutes) {
    const mins = timeToMinutes(timeStr);
    if (mins === null) return '';
    return minutesToTime(mins + deltaMinutes);
  }

  // Get initial departure time in minutes for a trip column
  function getTripFirstDepartureMinutes(trip) {
    if (!trip || !Array.isArray(trip.times)) return null;
    for (let i = 0; i < trip.times.length; i++) {
      const mins = timeToMinutes(trip.times[i]);
      if (mins !== null) return mins;
    }
    return null;
  }

  // Sort trips chronologically
  function sortTripsChronologically(trips) {
    return [...trips].sort((a, b) => {
      const aMin = getTripFirstDepartureMinutes(a);
      const bMin = getTripFirstDepartureMinutes(b);
      if (aMin === null && bMin === null) return 0;
      if (aMin === null) return 1;
      if (bMin === null) return -1;
      return aMin - bMin;
    });
  }

  // Update visual appearance of a day pill based on checkbox state
  function updateDayPillStyle(cb) {
    if (!cb) return;
    const pill = cb.closest('.day-pill');
    if (!pill) return;

    if (cb.checked) {
      pill.classList.remove(
        'border-slate-200',
        'dark:border-slate-800',
        'bg-white',
        'dark:bg-slate-900',
        'text-slate-400',
        'dark:text-slate-500'
      );
      pill.classList.add(
        'border-sky-500',
        'bg-sky-50',
        'dark:bg-sky-950/50',
        'text-sky-700',
        'dark:text-sky-300'
      );
    } else {
      pill.classList.remove(
        'border-sky-500',
        'bg-sky-50',
        'dark:bg-sky-950/50',
        'text-sky-700',
        'dark:text-sky-300'
      );
      pill.classList.add(
        'border-slate-200',
        'dark:border-slate-800',
        'bg-white',
        'dark:bg-slate-900',
        'text-slate-400',
        'dark:text-slate-500'
      );
    }
  }

  function setDayValues(values) {
    dayKeys.forEach((k) => {
      if (dayCheckboxes[k]) {
        dayCheckboxes[k].checked = Boolean(values[k]);
        updateDayPillStyle(dayCheckboxes[k]);
      }
    });
  }

  // Attach change listeners to day checkboxes
  dayKeys.forEach((k) => {
    const cb = dayCheckboxes[k];
    if (cb) {
      cb.addEventListener('change', () => updateDayPillStyle(cb));
    }
  });

  // Attach quick selection buttons
  if (btnSelectAll) {
    btnSelectAll.addEventListener('click', () => {
      dayKeys.forEach((k) => {
        if (dayCheckboxes[k]) {
          dayCheckboxes[k].checked = true;
          updateDayPillStyle(dayCheckboxes[k]);
        }
      });
    });
  }

  if (btnSelectWeekdays) {
    btnSelectWeekdays.addEventListener('click', () => {
      ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'].forEach((k) => {
        if (dayCheckboxes[k]) {
          dayCheckboxes[k].checked = true;
          updateDayPillStyle(dayCheckboxes[k]);
        }
      });
      ['saturday', 'sunday', 'bank_holiday'].forEach((k) => {
        if (dayCheckboxes[k]) {
          dayCheckboxes[k].checked = false;
          updateDayPillStyle(dayCheckboxes[k]);
        }
      });
    });
  }

  if (btnSelectWeekends) {
    btnSelectWeekends.addEventListener('click', () => {
      ['saturday', 'sunday'].forEach((k) => {
        if (dayCheckboxes[k]) {
          dayCheckboxes[k].checked = true;
          updateDayPillStyle(dayCheckboxes[k]);
        }
      });
      [
        'monday',
        'tuesday',
        'wednesday',
        'thursday',
        'friday',
        'bank_holiday',
      ].forEach((k) => {
        if (dayCheckboxes[k]) {
          dayCheckboxes[k].checked = false;
          updateDayPillStyle(dayCheckboxes[k]);
        }
      });
    });
  }

  if (btnClearAll) {
    btnClearAll.addEventListener('click', () => {
      dayKeys.forEach((k) => {
        if (dayCheckboxes[k]) {
          dayCheckboxes[k].checked = false;
          updateDayPillStyle(dayCheckboxes[k]);
        }
      });
    });
  }

  // Format active days summary HTML badges
  function renderDaysHtml(item) {
    const daysConfig = [
      { label: 'M', active: item.monday, title: 'Monday' },
      { label: 'T', active: item.tuesday, title: 'Tuesday' },
      { label: 'W', active: item.wednesday, title: 'Wednesday' },
      { label: 'T', active: item.thursday, title: 'Thursday' },
      { label: 'F', active: item.friday, title: 'Friday' },
      { label: 'S', active: item.saturday, title: 'Saturday' },
      { label: 'S', active: item.sunday, title: 'Sunday' },
      { label: 'BH', active: item.bank_holiday, title: 'Bank Holiday' },
    ];

    const badges = daysConfig
      .map((d) => {
        const cls = d.active
          ? 'bg-sky-100 text-sky-800 dark:bg-sky-950/80 dark:text-sky-300 font-bold'
          : 'bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-600 opacity-40';
        return `<span class="inline-flex items-center justify-center min-w-[20px] px-1 py-0.5 rounded text-[10px] ${cls}" title="${d.title}">${d.label}</span>`;
      })
      .join(' ');

    return `<div class="flex items-center gap-1 flex-nowrap whitespace-nowrap">${badges}</div>`;
  }

  // Format data rows for Grid.js list view
  function formatGridData(items) {
    return items.map((item, index) => {
      const mode = TRANSPORT_MODES[item.transport_type] || TRANSPORT_MODES.bus;
      const startDateHtml = item.start_date
        ? `<span class="font-mono text-xs text-slate-700 dark:text-slate-300">${escapeHtml(
            item.start_date
          )}</span>`
        : `<span class="text-slate-400 text-xs">—</span>`;

      const endDateHtml = item.end_date
        ? `<span class="font-mono text-xs text-slate-700 dark:text-slate-300">${escapeHtml(
            item.end_date
          )}</span>`
        : `<span class="text-slate-400 text-xs">—</span>`;

      const stopsCount = item.content?.stops?.length || 0;
      const tripsCount = item.content?.trips?.length || 0;
      const summaryText = `${stopsCount} ${
        stopsCount === 1 ? 'stop' : 'stops'
      }, ${tripsCount} ${tripsCount === 1 ? 'trip' : 'trips'}`;

      return [
        gridjs.html(
          `<div class="flex items-center gap-2.5">
            <span class="material-symbols-outlined text-slate-500 dark:text-slate-400 text-xl">${mode.icon}</span>
            <div>
              <div class="font-semibold text-slate-900 dark:text-slate-100">${escapeHtml(
                item.name
              )}</div>
              <div class="text-xs text-slate-500 dark:text-slate-400">${summaryText}</div>
            </div>
          </div>`
        ),
        gridjs.html(
          `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold ${mode.badgeClass}">
            <span class="material-symbols-outlined text-xs leading-none">${mode.icon}</span>
            ${mode.label}
          </span>`
        ),
        gridjs.html(startDateHtml),
        gridjs.html(endDateHtml),
        gridjs.html(renderDaysHtml(item)),
        gridjs.html(`
          <div class="flex items-center gap-1.5 justify-end">
            <button 
              type="button" 
              class="edit-matrix-btn inline-flex items-center justify-center w-7 h-7 rounded-lg bg-sky-50 text-sky-600 hover:bg-sky-100 hover:text-sky-700 dark:bg-sky-950/50 dark:text-sky-400 dark:hover:bg-sky-900/60 transition-colors cursor-pointer" 
              data-index="${index}" 
              title="Edit timetable grid and timings"
              aria-label="Edit timetable grid and timings"
            >
              <span class="material-symbols-outlined text-[17px] leading-none">grid_on</span>
            </button>
            <button 
              type="button" 
              class="edit-timetable-btn inline-flex items-center justify-center w-7 h-7 rounded-lg bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700 transition-colors cursor-pointer" 
              data-index="${index}" 
              title="Edit timetable metadata"
              aria-label="Edit timetable metadata"
            >
              <span class="material-symbols-outlined text-[17px] leading-none">edit</span>
            </button>
            <button 
              type="button" 
              class="delete-timetable-btn inline-flex items-center justify-center w-7 h-7 rounded-lg bg-rose-50 text-rose-600 hover:bg-rose-100 hover:text-rose-700 dark:bg-rose-950/50 dark:text-rose-400 dark:hover:bg-rose-900/60 transition-colors cursor-pointer" 
              data-index="${index}" 
              title="Delete timetable"
              aria-label="Delete timetable"
            >
              <span class="material-symbols-outlined text-[17px] leading-none">delete</span>
            </button>
          </div>
        `),
      ];
    });
  }

  const columnsConfig = [
    { name: 'Timetable Name', width: 'auto', sort: true },
    { name: 'Type', width: '130px', sort: true },
    { name: 'Start Date', width: '130px', sort: true },
    { name: 'End Date', width: '130px', sort: true },
    { name: 'Applicable Days', width: '280px', sort: false },
    { name: 'Actions', width: '100px', sort: false },
  ];

  // Initialise Grid.js instance
  const grid = new gridjs.Grid({
    columns: columnsConfig,
    data: formatGridData(stagedTimetables),
    search: {
      placeholder: 'Search timetables...',
    },
    pagination: {
      limit: 8,
      summary: true,
    },
    language: {
      search: {
        placeholder: 'Search timetables...',
      },
      pagination: {
        previous: 'Previous',
        next: 'Next',
        showing: 'Showing',
        results: () => 'timetables',
      },
    },
  }).render(gridContainer);

  // Sync in-memory changes with hidden form input and dirty manager
  function syncState() {
    const currentJson = JSON.stringify(stagedTimetables);
    if (hiddenInput) {
      hiddenInput.value = currentJson;
    }

    // Update empty state vs grid visibility in list view
    if (stagedTimetables.length === 0) {
      gridContainer.classList.add('hidden');
      emptyState.classList.remove('hidden');
    } else {
      gridContainer.classList.remove('hidden');
      emptyState.classList.add('hidden');
    }

    if (gridContainer && gridContainer.querySelector('.gridjs-container')) {
      if (stagedTimetables.length <= 8) {
        gridContainer
          .querySelector('.gridjs-container')
          .setAttribute('data-single-page', 'true');
      } else {
        gridContainer
          .querySelector('.gridjs-container')
          .removeAttribute('data-single-page');
      }
    }

    // Re-render Grid.js list
    grid
      .updateConfig({
        columns: columnsConfig,
        data: formatGridData(stagedTimetables),
      })
      .forceRender();

    // Check dirty state
    if (window.ConfigDirtyManager) {
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
      stagedTimetables = JSON.parse(initialSnapshot);
      selectedTripIndices.clear();
      if (activeEditorIndex >= 0) {
        if (activeEditorIndex >= stagedTimetables.length) {
          closeEditor();
        } else {
          renderMatrix();
        }
      }
      syncState();
    });
  }

  // Open Add Timetable Modal
  function showAddModal() {
    currentEditIndex = -1;
    if (modalTitle) modalTitle.textContent = 'Add New Timetable';
    if (modalIcon) modalIcon.textContent = 'calendar_add_on';
    if (confirmBtn) confirmBtn.textContent = 'Add Timetable';
    if (modalError) modalError.classList.add('hidden');

    if (modalNameInput) modalNameInput.value = '';
    if (modalTransportTypeSelect) modalTransportTypeSelect.value = 'bus';
    if (modalStartDateInput) modalStartDateInput.value = '';
    if (modalEndDateInput) modalEndDateInput.value = '';

    // Default all days enabled
    setDayValues({
      monday: true,
      tuesday: true,
      wednesday: true,
      thursday: true,
      friday: true,
      saturday: true,
      sunday: true,
      bank_holiday: true,
    });

    if (timetableModal && typeof timetableModal.showModal === 'function') {
      timetableModal.showModal();
    }
  }

  // Open Edit Timetable Metadata Modal
  function showEditModal(index) {
    if (index < 0 || index >= stagedTimetables.length) return;
    currentEditIndex = index;
    const item = stagedTimetables[index];

    if (modalTitle) modalTitle.textContent = 'Edit Timetable Schedule';
    if (modalIcon) modalIcon.textContent = 'edit_calendar';
    if (confirmBtn) confirmBtn.textContent = 'Update Timetable';
    if (modalError) modalError.classList.add('hidden');

    if (modalNameInput) modalNameInput.value = item.name || '';
    if (modalTransportTypeSelect)
      modalTransportTypeSelect.value = item.transport_type || 'bus';
    if (modalStartDateInput) modalStartDateInput.value = item.start_date || '';
    if (modalEndDateInput) modalEndDateInput.value = item.end_date || '';

    setDayValues(item);

    if (timetableModal && typeof timetableModal.showModal === 'function') {
      timetableModal.showModal();
    }
  }

  if (openAddBtn) openAddBtn.addEventListener('click', showAddModal);
  if (emptyAddBtn) emptyAddBtn.addEventListener('click', showAddModal);

  function closeModal() {
    if (timetableModal && typeof timetableModal.close === 'function') {
      timetableModal.close();
    }
  }

  if (closeModalBtn) closeModalBtn.addEventListener('click', closeModal);
  if (cancelModalBtn) cancelModalBtn.addEventListener('click', closeModal);

  // Delegate Grid.js row actions (Open Editor, Edit Metadata, Delete)
  document.addEventListener('click', (e) => {
    const openEditorBtn = e.target.closest('.open-editor-btn');
    if (openEditorBtn) {
      const idx = parseInt(openEditorBtn.getAttribute('data-index'), 10);
      if (!isNaN(idx)) {
        openEditor(idx);
      }
      return;
    }

    const editBtn = e.target.closest('.edit-row-btn');
    if (editBtn) {
      const idx = parseInt(editBtn.getAttribute('data-index'), 10);
      if (!isNaN(idx)) {
        showEditModal(idx);
      }
      return;
    }

    const removeBtn = e.target.closest('.remove-row-btn');
    if (removeBtn) {
      const idx = parseInt(removeBtn.getAttribute('data-index'), 10);
      if (!isNaN(idx) && idx >= 0 && idx < stagedTimetables.length) {
        stagedTimetables.splice(idx, 1);
        syncState();
      }
    }
  });

  // Confirm adding / updating timetable metadata
  if (confirmBtn) {
    confirmBtn.addEventListener('click', () => {
      const name = modalNameInput ? modalNameInput.value.trim() : '';
      const transport_type = modalTransportTypeSelect
        ? modalTransportTypeSelect.value.trim().toLowerCase()
        : 'bus';
      const start_date = modalStartDateInput
        ? modalStartDateInput.value.trim()
        : '';
      const end_date = modalEndDateInput ? modalEndDateInput.value.trim() : '';

      if (!name) {
        if (modalError) {
          modalError.textContent = 'Please provide a timetable name.';
          modalError.classList.remove('hidden');
        }
        return;
      }

      if (start_date && end_date && end_date < start_date) {
        if (modalError) {
          modalError.textContent =
            'End Date cannot be earlier than Start Date.';
          modalError.classList.remove('hidden');
        }
        return;
      }

      const days = {};
      let atLeastOneDay = false;
      dayKeys.forEach((k) => {
        days[k] = dayCheckboxes[k] ? dayCheckboxes[k].checked : true;
        if (days[k]) atLeastOneDay = true;
      });

      if (!atLeastOneDay) {
        if (modalError) {
          modalError.textContent =
            'Please select at least one applicable operating day.';
          modalError.classList.remove('hidden');
        }
        return;
      }

      const payloadItem = {
        name,
        transport_type,
        start_date: start_date || null,
        end_date: end_date || null,
        ...days,
      };

      if (currentEditIndex >= 0 && currentEditIndex < stagedTimetables.length) {
        payloadItem.id = stagedTimetables[currentEditIndex].id;
        payloadItem.content = stagedTimetables[currentEditIndex].content;
        stagedTimetables[currentEditIndex] = normaliseItem(payloadItem);
      } else {
        payloadItem.content = { stops: [], trips: [] };
        stagedTimetables.push(normaliseItem(payloadItem));
      }

      syncState();
      closeModal();
    });
  }

  // =========================================================================
  // FULL-WIDTH TIMETABLE GRID EDITOR CONTROLLER
  // =========================================================================

  function openEditor(index) {
    if (index < 0 || index >= stagedTimetables.length) return;
    activeEditorIndex = index;
    selectedTripIndices.clear();

    const item = stagedTimetables[activeEditorIndex];
    const mode = TRANSPORT_MODES[item.transport_type] || TRANSPORT_MODES.bus;

    if (editorBreadcrumbName) editorBreadcrumbName.textContent = item.name;
    if (editorTitle) editorTitle.textContent = `${item.name}`;
    if (editorModeIcon) editorModeIcon.textContent = mode.icon;
    if (editorModeText) editorModeText.textContent = mode.label;
    if (editorModeBadge) {
      editorModeBadge.className = `inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold ${mode.badgeClass}`;
    }

    listView.classList.add('hidden');
    editorView.classList.remove('hidden');
    renderMatrix();
  }

  function closeEditor() {
    activeEditorIndex = -1;
    selectedTripIndices.clear();
    editorView.classList.add('hidden');
    listView.classList.remove('hidden');
    syncState();
  }

  if (editorBackBtn) editorBackBtn.addEventListener('click', closeEditor);
  if (editorBackLink) editorBackLink.addEventListener('click', closeEditor);

  // Validate timing sequences down a trip column
  function validateTripColumn(trip, stopsCount) {
    const times = trip.times || [];
    const errors = new Set();
    let prevMinutes = null;

    for (let sIdx = 0; sIdx < stopsCount; sIdx++) {
      const val = times[sIdx] || '';
      if (!val) continue;

      const currentMinutes = timeToMinutes(val);
      if (currentMinutes === null) {
        errors.add(sIdx);
        continue;
      }

      if (prevMinutes !== null && currentMinutes < prevMinutes) {
        errors.add(sIdx);
      }

      prevMinutes = currentMinutes;
    }

    return errors;
  }

  // Update selection UI toolbar
  function updateSelectionBar() {
    if (!selectionBar) return;
    const count = selectedTripIndices.size;
    if (count > 0) {
      selectionBar.classList.remove('hidden');
      if (selectionCountText) {
        selectionCountText.textContent = `${count} selected`;
      }
    } else {
      selectionBar.classList.add('hidden');
    }
  }

  // Render the Matrix Grid
  function renderMatrix() {
    if (activeEditorIndex < 0 || activeEditorIndex >= stagedTimetables.length)
      return;

    const timetable = stagedTimetables[activeEditorIndex];
    const stops = timetable.content.stops || [];
    let trips = timetable.content.trips || [];

    // Ensure all trips have matching time array lengths
    trips.forEach((t) => {
      if (!Array.isArray(t.times)) t.times = [];
      while (t.times.length < stops.length) t.times.push('');
    });

    let hasAnySequenceError = false;

    // Check for column timing errors
    const tripErrors = trips.map((t) => {
      const errs = validateTripColumn(t, stops.length);
      if (errs.size > 0) hasAnySequenceError = true;
      return errs;
    });

    if (validationBanner) {
      if (hasAnySequenceError) {
        validationBanner.classList.remove('hidden');
      } else {
        validationBanner.classList.add('hidden');
      }
    }

    updateSelectionBar();

    // Generate Matrix Table HTML
    let tableHtml = `
      <table class="w-full text-left border-collapse border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden bg-white dark:bg-slate-900">
        <thead>
          <tr class="bg-slate-50 dark:bg-slate-800/60 border-b border-slate-200 dark:border-slate-800">
            <!-- Fixed Left Header: Stops -->
            <th class="sticky left-0 z-20 bg-slate-100 dark:bg-slate-800 min-w-[280px] max-w-[320px] p-3 text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300 border-r border-slate-200 dark:border-slate-700 shadow-sm">
              <div class="flex items-center justify-between">
                <span>Stops &amp; Places (${stops.length})</span>
                <span class="text-[11px] font-normal text-slate-500 dark:text-slate-400">Sequence</span>
              </div>
            </th>
    `;

    // Render Trip Column Headers
    if (trips.length === 0) {
      tableHtml += `
            <th class="p-6 text-center text-xs font-semibold text-slate-400 dark:text-slate-500 italic">
              No trip columns configured. Click "Add Trip Column" above.
            </th>
      `;
    } else {
      trips.forEach((trip, tIdx) => {
        const isSelected = selectedTripIndices.has(tIdx);
        const firstDep = getTripFirstDepartureMinutes(trip);
        const firstDepStr =
          firstDep !== null ? minutesToTime(firstDep) : `Trip ${tIdx + 1}`;
        const hasErr = tripErrors[tIdx].size > 0;

        tableHtml += `
            <th class="min-w-[120px] p-2.5 text-center border-r border-slate-200 dark:border-slate-800 ${
              isSelected ? 'bg-sky-50 dark:bg-sky-950/40' : ''
            }">
              <div class="flex flex-col items-center gap-1.5">
                <div class="flex items-center justify-between w-full px-1">
                  <input 
                    type="checkbox" 
                    class="trip-select-cb rounded border-slate-300 text-sky-600 focus:ring-sky-500 dark:border-slate-700 dark:bg-slate-800 cursor-pointer"
                    data-trip-index="${tIdx}"
                    ${isSelected ? 'checked' : ''}
                    title="Select trip for duplicate/delete"
                  >
                  <div class="flex items-center gap-0.5">
                    <button 
                      type="button" 
                      class="trip-retime-btn p-1 text-slate-400 hover:text-sky-600 dark:hover:text-sky-400 cursor-pointer rounded"
                      data-trip-index="${tIdx}"
                      title="Duplicate &amp; retime this trip"
                    >
                      <span class="material-symbols-outlined text-sm leading-none">content_copy</span>
                    </button>
                    <button 
                      type="button" 
                      class="trip-delete-btn p-1 text-slate-400 hover:text-rose-600 dark:hover:text-rose-400 cursor-pointer rounded"
                      data-trip-index="${tIdx}"
                      title="Delete this trip column"
                    >
                      <span class="material-symbols-outlined text-sm leading-none">delete</span>
                    </button>
                  </div>
                </div>
                <div class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-mono font-bold ${
                  hasErr
                    ? 'bg-rose-100 text-rose-800 dark:bg-rose-950/80 dark:text-rose-300 ring-1 ring-rose-500/50'
                    : 'bg-slate-200/80 text-slate-800 dark:bg-slate-700 dark:text-slate-200'
                }">
                  ${firstDepStr}
                </div>
              </div>
            </th>
        `;
      });
    }

    tableHtml += `
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-200 dark:divide-slate-800">
    `;

    // Render Stop Rows
    if (stops.length === 0) {
      tableHtml += `
          <tr>
            <td colspan="${
              Math.max(1, trips.length) + 1
            }" class="p-8 text-center text-slate-500 dark:text-slate-400">
              <span class="material-symbols-outlined text-3xl text-slate-400 dark:text-slate-500 mb-1">signpost</span>
              <p class="text-sm font-semibold">No stops configured for this timetable</p>
              <p class="text-xs text-slate-400 mt-0.5">Use the search box below to add stops matching this timetable type, custom locations, or Home Assistant zones.</p>
            </td>
          </tr>
      `;
    } else {
      stops.forEach((stop, sIdx) => {
        const icon = stop.icon || 'place';
        const indicator = stop.indicator || stop.type || 'Stop';

        tableHtml += `
          <tr class="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
            <!-- Left Sticky Cell: Stop Info & Controls -->
            <td class="sticky left-0 z-10 bg-white dark:bg-slate-900 p-2.5 border-r border-slate-200 dark:border-slate-800 shadow-sm">
              <div class="flex items-center justify-between gap-2">
                <div class="flex items-center gap-2 min-w-0">
                  <span class="material-symbols-outlined text-slate-400 text-base flex-shrink-0">${icon}</span>
                  <div class="min-w-0">
                    <div class="text-xs font-semibold text-slate-900 dark:text-slate-100 truncate" title="${escapeHtml(
                      stop.name
                    )}">
                      ${escapeHtml(stop.name)}
                    </div>
                    <div class="text-[10px] text-slate-400 dark:text-slate-500 truncate">
                      ${escapeHtml(indicator)}
                    </div>
                  </div>
                </div>
                <div class="flex items-center gap-0.5 flex-shrink-0">
                  <button 
                    type="button" 
                    class="stop-move-up-btn p-1 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed"
                    data-stop-index="${sIdx}"
                    ${sIdx === 0 ? 'disabled' : ''}
                    title="Move stop up"
                  >
                    <span class="material-symbols-outlined text-sm leading-none">arrow_upward</span>
                  </button>
                  <button 
                    type="button" 
                    class="stop-move-down-btn p-1 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed"
                    data-stop-index="${sIdx}"
                    ${sIdx === stops.length - 1 ? 'disabled' : ''}
                    title="Move stop down"
                  >
                    <span class="material-symbols-outlined text-sm leading-none">arrow_downward</span>
                  </button>
                  <button 
                    type="button" 
                    class="stop-delete-btn p-1 text-slate-400 hover:text-rose-600 dark:hover:text-rose-400 cursor-pointer rounded"
                    data-stop-index="${sIdx}"
                    title="Remove stop"
                  >
                    <span class="material-symbols-outlined text-sm leading-none">close</span>
                  </button>
                </div>
              </div>
            </td>
        `;

        // Render Trip Cells for this Stop
        trips.forEach((trip, tIdx) => {
          const val = trip.times[sIdx] || '';
          const isErr = tripErrors[tIdx].has(sIdx);
          const isSelected = selectedTripIndices.has(tIdx);

          tableHtml += `
            <td class="p-1.5 text-center border-r border-slate-200 dark:border-slate-800 ${
              isSelected ? 'bg-sky-50/40 dark:bg-sky-950/20' : ''
            }">
              <input 
                type="time" 
                class="matrix-time-input w-24 px-2 py-1 text-xs font-mono rounded-lg border text-center transition-colors ${
                  isErr
                    ? 'border-rose-500 bg-rose-50 dark:bg-rose-950/50 text-rose-700 dark:text-rose-300 ring-2 ring-rose-500/30'
                    : 'border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:border-sky-500 focus:ring-2 focus:ring-sky-500/20'
                }"
                data-stop-index="${sIdx}"
                data-trip-index="${tIdx}"
                value="${escapeHtml(val)}"
                title="${
                  isErr
                    ? 'Invalid sequence: Time cannot be earlier than a preceding stop in this trip.'
                    : 'Scheduled departure time (optional)'
                }"
              >
            </td>
          `;
        });

        tableHtml += `</tr>`;
      });
    }

    // Bottom Add Stop Row
    tableHtml += `
          <tr class="bg-slate-50/40 dark:bg-slate-800/20 border-t-2 border-slate-200 dark:border-slate-700">
            <td class="sticky left-0 z-10 bg-slate-50 dark:bg-slate-800/90 p-3 border-r border-slate-200 dark:border-slate-700">
              <div class="relative">
                <div class="flex items-center gap-2">
                  <span class="material-symbols-outlined text-slate-400 text-sm">search</span>
                  <input 
                    type="text" 
                    id="matrix-stop-search-input" 
                    placeholder="Search stops, stations, HA &amp; custom places to add..." 
                    class="w-full px-3 py-1.5 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 placeholder-slate-400 focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-500/20"
                    autocomplete="off"
                  >
                </div>
                <!-- Autocomplete Dropdown List Mount -->
                <div id="matrix-stop-search-results" class="hidden absolute top-full left-0 right-0 mt-1.5 max-h-60 overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-800 z-50 divide-y divide-slate-100 dark:divide-slate-700"></div>
              </div>
            </td>
            <td colspan="${Math.max(
              1,
              trips.length
            )}" class="p-3 text-xs text-slate-400 dark:text-slate-500 italic">
              Add stops above to extend this route pattern.
            </td>
          </tr>
        </tbody>
      </table>
    `;

    matrixMount.innerHTML = tableHtml;
    attachMatrixEventListeners();
  }

  // Attach dynamic event listeners for Matrix table inputs and controls
  function attachMatrixEventListeners() {
    if (activeEditorIndex < 0) return;
    const timetable = stagedTimetables[activeEditorIndex];

    // Time cell input listener
    const timeInputs = matrixMount.querySelectorAll('.matrix-time-input');
    timeInputs.forEach((input) => {
      input.addEventListener('change', (e) => {
        const sIdx = parseInt(e.target.getAttribute('data-stop-index'), 10);
        const tIdx = parseInt(e.target.getAttribute('data-trip-index'), 10);
        if (
          !isNaN(sIdx) &&
          !isNaN(tIdx) &&
          timetable.content.trips[tIdx] &&
          timetable.content.trips[tIdx].times
        ) {
          timetable.content.trips[tIdx].times[sIdx] = e.target.value.trim();

          // Re-sort trips chronologically and re-render
          timetable.content.trips = sortTripsChronologically(
            timetable.content.trips
          );
          renderMatrix();
          syncState();
        }
      });
    });

    // Column selection checkbox listener
    const tripCheckboxes = matrixMount.querySelectorAll('.trip-select-cb');
    tripCheckboxes.forEach((cb) => {
      cb.addEventListener('change', (e) => {
        const tIdx = parseInt(e.target.getAttribute('data-trip-index'), 10);
        if (!isNaN(tIdx)) {
          if (e.target.checked) {
            selectedTripIndices.add(tIdx);
          } else {
            selectedTripIndices.delete(tIdx);
          }
          renderMatrix();
        }
      });
    });

    // Stop move up
    const moveUpBtns = matrixMount.querySelectorAll('.stop-move-up-btn');
    moveUpBtns.forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const sIdx = parseInt(
          e.target.closest('button').getAttribute('data-stop-index'),
          10
        );
        if (!isNaN(sIdx) && sIdx > 0) {
          // Swap stop in stops list
          const tempStop = timetable.content.stops[sIdx];
          timetable.content.stops[sIdx] = timetable.content.stops[sIdx - 1];
          timetable.content.stops[sIdx - 1] = tempStop;

          // Swap times in all trips
          timetable.content.trips.forEach((trip) => {
            const tempTime = trip.times[sIdx];
            trip.times[sIdx] = trip.times[sIdx - 1];
            trip.times[sIdx - 1] = tempTime;
          });

          renderMatrix();
          syncState();
        }
      });
    });

    // Stop move down
    const moveDownBtns = matrixMount.querySelectorAll('.stop-move-down-btn');
    moveDownBtns.forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const sIdx = parseInt(
          e.target.closest('button').getAttribute('data-stop-index'),
          10
        );
        if (!isNaN(sIdx) && sIdx < timetable.content.stops.length - 1) {
          // Swap stop in stops list
          const tempStop = timetable.content.stops[sIdx];
          timetable.content.stops[sIdx] = timetable.content.stops[sIdx + 1];
          timetable.content.stops[sIdx + 1] = tempStop;

          // Swap times in all trips
          timetable.content.trips.forEach((trip) => {
            const tempTime = trip.times[sIdx];
            trip.times[sIdx] = trip.times[sIdx + 1];
            trip.times[sIdx + 1] = tempTime;
          });

          renderMatrix();
          syncState();
        }
      });
    });

    // Stop delete
    const deleteStopBtns = matrixMount.querySelectorAll('.stop-delete-btn');
    deleteStopBtns.forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const sIdx = parseInt(
          e.target.closest('button').getAttribute('data-stop-index'),
          10
        );
        if (
          !isNaN(sIdx) &&
          sIdx >= 0 &&
          sIdx < timetable.content.stops.length
        ) {
          timetable.content.stops.splice(sIdx, 1);
          timetable.content.trips.forEach((trip) => {
            if (trip.times.length > sIdx) {
              trip.times.splice(sIdx, 1);
            }
          });
          renderMatrix();
          syncState();
        }
      });
    });

    // Trip Retime (Single Trip Column)
    const tripRetimeBtns = matrixMount.querySelectorAll('.trip-retime-btn');
    tripRetimeBtns.forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const tIdx = parseInt(
          e.target.closest('button').getAttribute('data-trip-index'),
          10
        );
        if (!isNaN(tIdx)) {
          openRetimeModal([tIdx]);
        }
      });
    });

    // Trip Delete (Single Trip Column)
    const tripDeleteBtns = matrixMount.querySelectorAll('.trip-delete-btn');
    tripDeleteBtns.forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const tIdx = parseInt(
          e.target.closest('button').getAttribute('data-trip-index'),
          10
        );
        if (
          !isNaN(tIdx) &&
          tIdx >= 0 &&
          tIdx < timetable.content.trips.length
        ) {
          timetable.content.trips.splice(tIdx, 1);
          selectedTripIndices.delete(tIdx);
          renderMatrix();
          syncState();
        }
      });
    });

    // Autocomplete Stop Search
    setupStopSearchAutocomplete();
  }

  // Setup stop search autocomplete against /config/search/places
  let searchDebounceTimer = null;
  function setupStopSearchAutocomplete() {
    const searchInput = document.getElementById('matrix-stop-search-input');
    const resultsContainer = document.getElementById(
      'matrix-stop-search-results'
    );
    if (!searchInput || !resultsContainer) return;

    searchInput.addEventListener('input', () => {
      const q = searchInput.value.trim();
      clearTimeout(searchDebounceTimer);

      if (q.length < 1) {
        resultsContainer.innerHTML = '';
        resultsContainer.classList.add('hidden');
        return;
      }

      searchDebounceTimer = setTimeout(async () => {
        const timetable = stagedTimetables[activeEditorIndex];
        const transportType = timetable ? timetable.transport_type : 'bus';
        const ingressPath =
          document.body.getAttribute('data-ingress-path') || '';

        try {
          const res = await fetch(
            `${ingressPath}/config/search/places?type=${encodeURIComponent(
              transportType
            )}&q=${encodeURIComponent(q)}&limit=15`
          );
          if (!res.ok) throw new Error('Search failed');
          const data = await res.json();
          const results = data.results || [];

          if (results.length === 0) {
            resultsContainer.innerHTML = `
              <div class="p-3 text-xs text-slate-500 dark:text-slate-400 text-center">
                No matching places found.
              </div>
            `;
            resultsContainer.classList.remove('hidden');
            return;
          }

          resultsContainer.innerHTML = results
            .map(
              (place) => `
              <button 
                type="button" 
                class="add-searched-stop-btn w-full text-left p-2.5 hover:bg-sky-50 dark:hover:bg-slate-700/60 flex items-center justify-between gap-2 transition-colors cursor-pointer"
                data-place='${escapeHtml(JSON.stringify(place))}'
              >
                <div class="flex items-center gap-2 min-w-0">
                  <span class="material-symbols-outlined text-slate-400 text-sm flex-shrink-0">${
                    place.icon || 'place'
                  }</span>
                  <div class="min-w-0">
                    <div class="text-xs font-semibold text-slate-900 dark:text-slate-100 truncate">${escapeHtml(
                      place.name
                    )}</div>
                    <div class="text-[10px] text-slate-400 dark:text-slate-500 truncate">${escapeHtml(
                      place.description || place.indicator
                    )}</div>
                  </div>
                </div>
                <span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300 flex-shrink-0">
                  ${escapeHtml(place.indicator || place.type)}
                </span>
              </button>
            `
            )
            .join('');

          resultsContainer.classList.remove('hidden');

          // Attach click listeners to results
          resultsContainer
            .querySelectorAll('.add-searched-stop-btn')
            .forEach((btn) => {
              btn.addEventListener('click', () => {
                const placeDataRaw = btn.getAttribute('data-place');
                try {
                  const place = JSON.parse(placeDataRaw);
                  addStopToTimetable(place);
                  searchInput.value = '';
                  resultsContainer.innerHTML = '';
                  resultsContainer.classList.add('hidden');
                } catch (err) {
                  console.error('Failed to add stop:', err);
                }
              });
            });
        } catch (err) {
          console.error('Search places error:', err);
        }
      }, 200);
    });

    // Close autocomplete on click outside
    document.addEventListener('click', (e) => {
      if (
        !e.target.closest('#matrix-stop-search-input') &&
        !e.target.closest('#matrix-stop-search-results')
      ) {
        resultsContainer.classList.add('hidden');
      }
    });
  }

  // Add stop to active timetable and pad trips
  function addStopToTimetable(place) {
    if (activeEditorIndex < 0) return;
    const timetable = stagedTimetables[activeEditorIndex];
    if (!timetable.content.stops) timetable.content.stops = [];
    if (!timetable.content.trips) timetable.content.trips = [];

    timetable.content.stops.push({
      id: place.id,
      name: place.name,
      type: place.type,
      indicator: place.indicator,
      icon: place.icon,
      latitude: place.latitude,
      longitude: place.longitude,
    });

    // Append empty time to all existing trip columns
    timetable.content.trips.forEach((trip) => {
      if (!Array.isArray(trip.times)) trip.times = [];
      trip.times.push('');
    });

    renderMatrix();
    syncState();
  }

  // Add Trip Column Action
  if (addTripBtn) {
    addTripBtn.addEventListener('click', () => {
      if (activeEditorIndex < 0) return;
      const timetable = stagedTimetables[activeEditorIndex];
      const stopsCount = timetable.content.stops?.length || 0;

      // Default empty times for each stop
      const emptyTimes = new Array(stopsCount).fill('');
      timetable.content.trips.push({
        id: `trip_${Date.now()}_${Math.random().toString(16).slice(2, 6)}`,
        times: emptyTimes,
      });

      renderMatrix();
      syncState();
    });
  }

  // Clear Trips Action
  if (clearTripsBtn) {
    clearTripsBtn.addEventListener('click', () => {
      if (activeEditorIndex < 0) return;
      const timetable = stagedTimetables[activeEditorIndex];
      timetable.content.trips = [];
      selectedTripIndices.clear();
      renderMatrix();
      syncState();
    });
  }

  // Batch Retime Action
  if (retimeSelectedBtn) {
    retimeSelectedBtn.addEventListener('click', () => {
      if (selectedTripIndices.size > 0) {
        openRetimeModal(Array.from(selectedTripIndices).sort((a, b) => a - b));
      }
    });
  }

  // Batch Delete Action
  if (deleteSelectedBtn) {
    deleteSelectedBtn.addEventListener('click', () => {
      if (activeEditorIndex < 0 || selectedTripIndices.size === 0) return;
      const timetable = stagedTimetables[activeEditorIndex];
      timetable.content.trips = timetable.content.trips.filter(
        (_, idx) => !selectedTripIndices.has(idx)
      );
      selectedTripIndices.clear();
      renderMatrix();
      syncState();
    });
  }

  // Deselect Action
  if (deselectBtn) {
    deselectBtn.addEventListener('click', () => {
      selectedTripIndices.clear();
      renderMatrix();
    });
  }

  // =========================================================================
  // DUPLICATE & RETIME MODAL WORKFLOW
  // =========================================================================

  function openRetimeModal(tripIndices) {
    if (activeEditorIndex < 0 || !tripIndices || tripIndices.length === 0)
      return;
    targetRetimeIndices = tripIndices;
    const timetable = stagedTimetables[activeEditorIndex];
    if (retimeError) retimeError.classList.add('hidden');

    const isSingle = targetRetimeIndices.length === 1;
    if (retimeSingleOptions) {
      if (isSingle) {
        retimeSingleOptions.classList.remove('hidden');
        const targetTrip = timetable.content.trips[targetRetimeIndices[0]];
        const firstDep = getTripFirstDepartureMinutes(targetTrip);
        if (retimeStartTimeInput) {
          retimeStartTimeInput.value =
            firstDep !== null
              ? shiftTime(minutesToTime(firstDep), 60)
              : '09:00';
        }
      } else {
        retimeSingleOptions.classList.add('hidden');
      }
    }

    if (retimeMethodOffset) retimeMethodOffset.checked = true;
    updateRetimeMethodVisuals();

    if (retimeOffsetInput) retimeOffsetInput.value = '60';
    if (retimeCopyCountInput) retimeCopyCountInput.value = '1';
    updateRetimePreview();

    if (retimeModal && typeof retimeModal.showModal === 'function') {
      retimeModal.showModal();
    }
  }

  function updateRetimeMethodVisuals() {
    const isOffset = retimeMethodOffset ? retimeMethodOffset.checked : true;
    if (isOffset) {
      if (retimeMethodOffsetLbl) {
        retimeMethodOffsetLbl.className =
          'flex items-center justify-center p-2.5 rounded-xl border border-sky-500 bg-sky-50 dark:bg-sky-950/50 text-sky-700 dark:text-sky-300 text-xs font-bold cursor-pointer transition-all';
      }
      if (retimeMethodStartTimeLbl) {
        retimeMethodStartTimeLbl.className =
          'flex items-center justify-center p-2.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-500 dark:text-slate-400 text-xs font-bold cursor-pointer transition-all';
      }
      if (retimeStartTimeContainer)
        retimeStartTimeContainer.classList.add('hidden');
      if (retimeOffsetContainer)
        retimeOffsetContainer.classList.remove('hidden');
    } else {
      if (retimeMethodOffsetLbl) {
        retimeMethodOffsetLbl.className =
          'flex items-center justify-center p-2.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-500 dark:text-slate-400 text-xs font-bold cursor-pointer transition-all';
      }
      if (retimeMethodStartTimeLbl) {
        retimeMethodStartTimeLbl.className =
          'flex items-center justify-center p-2.5 rounded-xl border border-sky-500 bg-sky-50 dark:bg-sky-950/50 text-sky-700 dark:text-sky-300 text-xs font-bold cursor-pointer transition-all';
      }
      if (retimeStartTimeContainer)
        retimeStartTimeContainer.classList.remove('hidden');
      if (retimeOffsetContainer)
        retimeOffsetContainer.classList.add('hidden');
    }
    updateRetimePreview();
  }

  if (retimeMethodOffset) {
    retimeMethodOffset.addEventListener('change', updateRetimeMethodVisuals);
  }
  if (retimeMethodStartTime) {
    retimeMethodStartTime.addEventListener('change', updateRetimeMethodVisuals);
  }

  // Quick offset preset buttons
  const quickOffsetBtns = document.querySelectorAll('.quick-offset-btn');
  quickOffsetBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      const offset = parseInt(btn.getAttribute('data-offset'), 10);
      if (!isNaN(offset) && retimeOffsetInput) {
        retimeOffsetInput.value = offset;
        quickOffsetBtns.forEach((b) => {
          b.classList.remove(
            'bg-sky-100',
            'text-sky-800',
            'dark:bg-sky-950/80',
            'dark:text-sky-300'
          );
          b.classList.add(
            'bg-slate-100',
            'text-slate-700',
            'dark:bg-slate-800',
            'dark:text-slate-300'
          );
        });
        btn.classList.remove(
          'bg-slate-100',
          'text-slate-700',
          'dark:bg-slate-800',
          'dark:text-slate-300'
        );
        btn.classList.add(
          'bg-sky-100',
          'text-sky-800',
          'dark:bg-sky-950/80',
          'dark:text-sky-300'
        );
        updateRetimePreview();
      }
    });
  });

  function updateRetimePreview() {
    if (!retimePreviewText) return;
    const copies = parseInt(retimeCopyCountInput?.value || '1', 10);
    const count = targetRetimeIndices.length;
    const totalNew = (isNaN(copies) ? 1 : copies) * count;
    retimePreviewText.textContent = `Generates ${totalNew} duplicated trip ${
      totalNew === 1 ? 'column' : 'columns'
    }.`;
  }

  if (retimeCopyCountInput) {
    retimeCopyCountInput.addEventListener('input', updateRetimePreview);
  }
  if (retimeOffsetInput) {
    retimeOffsetInput.addEventListener('input', updateRetimePreview);
  }

  function closeRetimeModal() {
    if (retimeModal && typeof retimeModal.close === 'function') {
      retimeModal.close();
    }
  }

  if (closeRetimeBtn) closeRetimeBtn.addEventListener('click', closeRetimeModal);
  if (cancelRetimeBtn)
    cancelRetimeBtn.addEventListener('click', closeRetimeModal);

  // Confirm Duplication & Retime
  if (confirmRetimeBtn) {
    confirmRetimeBtn.addEventListener('click', () => {
      if (activeEditorIndex < 0 || targetRetimeIndices.length === 0) return;
      const timetable = stagedTimetables[activeEditorIndex];
      const isSingle = targetRetimeIndices.length === 1;
      const isOffset = retimeMethodOffset ? retimeMethodOffset.checked : true;
      const copies = Math.max(
        1,
        Math.min(parseInt(retimeCopyCountInput?.value || '1', 10) || 1, 20)
      );

      let offsetMinutes = parseInt(retimeOffsetInput?.value || '60', 10);
      if (isNaN(offsetMinutes) || offsetMinutes <= 0) offsetMinutes = 60;

      const newTrips = [];

      if (isSingle && !isOffset) {
        // Mode: Set specific new start time
        const newStartTimeStr = retimeStartTimeInput?.value?.trim();
        const newStartMins = timeToMinutes(newStartTimeStr);
        if (newStartMins === null) {
          if (retimeError) {
            retimeError.textContent =
              'Please provide a valid start time in HH:MM format.';
            retimeError.classList.remove('hidden');
          }
          return;
        }

        const sourceTrip = timetable.content.trips[targetRetimeIndices[0]];
        const origStartMins = getTripFirstDepartureMinutes(sourceTrip);
        const baseShift =
          origStartMins !== null ? newStartMins - origStartMins : 0;

        for (let c = 0; c < copies; c++) {
          const shiftDelta = baseShift + c * offsetMinutes;
          const clonedTimes = (sourceTrip.times || []).map((t) =>
            t ? shiftTime(t, shiftDelta) : ''
          );
          newTrips.push({
            id: `trip_${Date.now()}_${c}_${Math.random()
              .toString(16)
              .slice(2, 6)}`,
            times: clonedTimes,
          });
        }
      } else {
        // Mode: Shift by offset across selected trip columns
        for (let c = 1; c <= copies; c++) {
          targetRetimeIndices.forEach((tripIdx) => {
            const sourceTrip = timetable.content.trips[tripIdx];
            if (!sourceTrip) return;
            const shiftDelta = c * offsetMinutes;
            const clonedTimes = (sourceTrip.times || []).map((t) =>
              t ? shiftTime(t, shiftDelta) : ''
            );
            newTrips.push({
              id: `trip_${Date.now()}_${c}_${tripIdx}_${Math.random()
                .toString(16)
                .slice(2, 6)}`,
              times: clonedTimes,
            });
          });
        }
      }

      // Append new trips, sort chronologically, re-render, sync dirty state
      timetable.content.trips = sortTripsChronologically([
        ...timetable.content.trips,
        ...newTrips,
      ]);
      selectedTripIndices.clear();
      closeRetimeModal();
      renderMatrix();
      syncState();
    });
  }
});
