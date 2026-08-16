/**
 * Timetables View Controller.
 * Manages Grid.js data table rendering, in-memory staged timetable schedules,
 * add/edit modal workflows, date validation, and day selection helpers.
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

  // Sanitise initial items into standard schema format
  function normaliseItem(item) {
    return {
      id: item.id || null,
      name: item.name || '',
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
    };
  }

  // In-memory staged state
  let stagedTimetables = (initialRaw || []).map(normaliseItem);
  const initialSnapshot = JSON.stringify(stagedTimetables);
  let currentEditIndex = -1;

  const hiddenInput = document.getElementById('timetables_json');
  const emptyState = document.getElementById('grid-empty-state');
  const gridContainer = document.getElementById('timetables-grid-wrapper');

  // Modal elements
  const timetableModal = document.getElementById('timetable-modal');
  const openAddBtn = document.getElementById('open-add-modal-btn');
  const emptyAddBtn = document.getElementById('empty-add-btn');
  const closeModalBtn = document.getElementById('close-modal-btn');
  const cancelModalBtn = document.getElementById('cancel-modal-btn');
  const confirmBtn = document.getElementById('confirm-timetable-btn');
  const modalTitle = document.getElementById('modal-title');
  const modalIcon = document.getElementById('modal-icon');
  const modalNameInput = document.getElementById('modal_name');
  const modalStartDateInput = document.getElementById('modal_start_date');
  const modalEndDateInput = document.getElementById('modal_end_date');
  const modalError = document.getElementById('modal-validation-error');

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

    return `<div class="flex items-center gap-1 flex-wrap">${badges}</div>`;
  }

  // Format data rows for Grid.js
  function formatGridData(items) {
    return items.map((item, index) => {
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

      return [
        gridjs.html(
          `<span class="font-semibold text-slate-900 dark:text-slate-100">${escapeHtml(
            item.name
          )}</span>`
        ),
        gridjs.html(startDateHtml),
        gridjs.html(endDateHtml),
        gridjs.html(renderDaysHtml(item)),
        gridjs.html(`
          <div class="flex items-center gap-1.5">
            <button 
              type="button" 
              class="edit-row-btn inline-flex items-center justify-center w-7 h-7 rounded-lg bg-sky-50 text-sky-600 hover:bg-sky-100 hover:text-sky-700 dark:bg-sky-950/50 dark:text-sky-400 dark:hover:bg-sky-900/60 transition-colors cursor-pointer"
              data-index="${index}"
              title="Edit timetable"
              aria-label="Edit timetable"
            >
              <span class="material-symbols-outlined text-[17px] leading-none">edit</span>
            </button>
            <button 
              type="button" 
              class="remove-row-btn inline-flex items-center justify-center w-7 h-7 rounded-lg bg-rose-50 text-rose-600 hover:bg-rose-100 hover:text-rose-700 dark:bg-rose-950/50 dark:text-rose-400 dark:hover:bg-rose-900/60 transition-colors cursor-pointer"
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

  // Initialise Grid.js instance
  const grid = new gridjs.Grid({
    columns: [
      { name: 'Timetable Name', width: 'auto' },
      { name: 'Start Date', width: '130px' },
      { name: 'End Date', width: '130px' },
      { name: 'Applicable Days', width: '220px', sort: false },
      { name: 'Actions', width: '80px', sort: false },
    ],
    data: formatGridData(stagedTimetables),
    search: {
      placeholder: 'Search timetables...',
    },
    sort: true,
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

    // Update empty state vs grid visibility
    if (stagedTimetables.length === 0) {
      gridContainer.classList.add('hidden');
      emptyState.classList.remove('hidden');
    } else {
      gridContainer.classList.remove('hidden');
      emptyState.classList.add('hidden');
    }

    // Re-render Grid.js
    grid
      .updateConfig({
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

  // Open Edit Timetable Modal
  function showEditModal(index) {
    if (index < 0 || index >= stagedTimetables.length) return;
    currentEditIndex = index;
    const item = stagedTimetables[index];

    if (modalTitle) modalTitle.textContent = 'Edit Timetable';
    if (modalIcon) modalIcon.textContent = 'edit_calendar';
    if (confirmBtn) confirmBtn.textContent = 'Update Timetable';
    if (modalError) modalError.classList.add('hidden');

    if (modalNameInput) modalNameInput.value = item.name || '';
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

  // Delegate Edit and Remove row actions
  document.addEventListener('click', (e) => {
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

  // Confirm adding / updating timetable entry
  if (confirmBtn) {
    confirmBtn.addEventListener('click', () => {
      const name = modalNameInput ? modalNameInput.value.trim() : '';
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
        start_date: start_date || null,
        end_date: end_date || null,
        ...days,
      };

      if (currentEditIndex >= 0 && currentEditIndex < stagedTimetables.length) {
        // Retain original ID if present
        payloadItem.id = stagedTimetables[currentEditIndex].id;
        stagedTimetables[currentEditIndex] = payloadItem;
      } else {
        stagedTimetables.push(payloadItem);
      }

      syncState();
      closeModal();
    });
  }
});
