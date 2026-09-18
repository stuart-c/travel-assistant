/**
 * Timetables View Controller.
 * Manages Grid.js data table rendering, in-memory staged timetable schedules,
 * filtering, metadata modals, and delegates matrix grid editing to TimetableGridEditor.
 */
document.addEventListener('DOMContentLoaded', () => {
  try {
    const configEl =
      document.getElementById('timetables-config') ||
      document.getElementById('timetables-form');
    if (!configEl) return;

    const dataUrl =
      configEl.getAttribute('data-data-url') || '/config/timetables/data';
    const TRANSPORT_MODES =
      (window.TransitUI && window.TransitUI.TRANSPORT_MODES) || {};
    const escapeHtml =
      (window.TransitUI && window.TransitUI.escapeHtml) || ((s) => s || '');

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

      const stops = (Array.isArray(content.stops) ? content.stops : []).map(
        (s) =>
          typeof s === 'string'
            ? {
                id: s,
                name: s,
                type: (item.transport_type || 'bus').toLowerCase(),
                indicator: 'Stop',
                icon: 'place',
              }
            : s || {}
      );

      const trips = (Array.isArray(content.trips) ? content.trips : []).map(
        (trip, tIdx) => {
          let times = Array.isArray(trip.times) ? [...trip.times] : [];
          if (times.length === 0 && trip.time) times.push(trip.time);
          times = times.map((tm) => {
            if (typeof tm === 'object' && tm !== null) {
              const arr = tm.arr !== undefined ? tm.arr : tm.arrival || '';
              const dep = tm.dep !== undefined ? tm.dep : tm.departure || '';
              return arr || dep
                ? { arr: String(arr).trim(), dep: String(dep).trim() }
                : '';
            }
            return typeof tm === 'string' ? tm.trim() : '';
          });
          while (times.length < stops.length) times.push('');
          return {
            id:
              trip.id ||
              `trip-${tIdx + 1}-${Date.now().toString(16).slice(2, 6)}`,
            headsign: trip.headsign || '',
            toc: trip.toc || '',
            operator: trip.operator || '',
            times,
          };
        }
      );

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
        auto_added: Boolean(item.auto_added),
        content: { stops, trips },
      };
    }

    const changesetManager =
      window.TransitUI && window.TransitUI.createStagedChangesetManager
        ? window.TransitUI.createStagedChangesetManager('id')
        : new window.TransitUI.StagedChangesetManager('id');

    let currentPageItems = [];
    let currentEditIndex = -1;

    const emptyState = document.getElementById('grid-empty-state');
    const gridContainer = document.getElementById('timetables-grid-wrapper');
    const timetableModal = document.getElementById('timetable-modal');
    const openAddBtn = document.getElementById('open-add-modal-btn');
    const emptyAddBtn = document.getElementById('empty-add-btn');
    const closeModalBtn = document.getElementById('close-modal-btn');
    const cancelModalBtn = document.getElementById('cancel-modal-btn');
    const confirmBtn = document.getElementById('confirm-timetable-btn');
    const modalTitle = document.getElementById('modal-title');
    const modalIcon = document.getElementById('modal-icon');
    const modalNameInput = document.getElementById('modal_name');
    const modalTransportTypeSelect =
      document.getElementById('modal_transport_type');
    const modalStartDateInput = document.getElementById('modal_start_date');
    const modalEndDateInput = document.getElementById('modal_end_date');
    const modalError = document.getElementById('modal-validation-error');

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

    const modalDaySelector =
      window.DaySelector && window.DaySelector.bind
        ? window.DaySelector.bind({
            container: '#days-pill-container',
            selectAllBtn: '#days-select-all',
            selectWeekdaysBtn: '#days-select-weekdays',
            selectWeekendsBtn: '#days-select-weekends',
            clearAllBtn: '#days-clear-all',
          })
        : null;

    function setDayValues(values) {
      if (modalDaySelector) {
        modalDaySelector.setDays(values);
        return;
      }
      dayKeys.forEach((k) => {
        if (dayCheckboxes[k]) dayCheckboxes[k].checked = Boolean(values[k]);
      });
    }

    function renderDaysHtml(item) {
      const days = [
        ['M', item.monday, 'Monday'],
        ['T', item.tuesday, 'Tuesday'],
        ['W', item.wednesday, 'Wednesday'],
        ['T', item.thursday, 'Thursday'],
        ['F', item.friday, 'Friday'],
        ['S', item.saturday, 'Saturday'],
        ['S', item.sunday, 'Sunday'],
        ['BH', item.bank_holiday, 'Bank Holiday'],
      ];
      const badges = days
        .map(([lbl, active, title]) => {
          const cls = active
            ? 'bg-sky-100 text-sky-800 dark:bg-sky-950/80 dark:text-sky-300 font-bold'
            : 'bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-600 opacity-40';
          return `<span class="inline-flex items-center justify-center min-w-[20px] px-1 py-0.5 rounded text-[10px] ${cls}" title="${title}">${lbl}</span>`;
        })
        .join('');
      return `<div class="flex items-center gap-1 flex-nowrap whitespace-nowrap" style="white-space: nowrap !important; flex-wrap: nowrap !important;">${badges}</div>`;
    }

    function formatGridData(items) {
      return items.map((item, index) => {
        const mode =
          TRANSPORT_MODES[item.transport_type] ||
          TRANSPORT_MODES.bus || {
            label: 'Bus',
            icon: 'directions_bus',
            badgeClass: 'bg-sky-100 text-sky-800',
          };
        const startHtml = item.start_date
          ? `<span class="font-mono text-xs text-slate-700 dark:text-slate-300">${escapeHtml(
              item.start_date
            )}</span>`
          : `<span class="text-slate-400 text-xs">—</span>`;
        const endHtml = item.end_date
          ? `<span class="font-mono text-xs text-slate-700 dark:text-slate-300">${escapeHtml(
              item.end_date
            )}</span>`
          : `<span class="text-slate-400 text-xs">—</span>`;

        const sCount = item.content?.stops?.length || 0;
        const tCount = item.content?.trips?.length || 0;
        const summaryText = `${sCount} ${sCount === 1 ? 'stop' : 'stops'}, ${tCount} ${
          tCount === 1 ? 'trip' : 'trips'
        }`;
        const autoBadge = item.auto_added
          ? `<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300 ml-1.5"><span class="material-symbols-outlined text-[12px] leading-none">cloud_sync</span>Auto</span>`
          : '';

        const actionsHtml = item.auto_added
          ? `<div class="flex items-center gap-1.5 justify-end">
              <button type="button" class="edit-matrix-btn open-editor-btn inline-flex items-center justify-center w-7 h-7 rounded-lg bg-sky-50 text-sky-600 hover:bg-sky-100 hover:text-sky-700 dark:bg-sky-950/50 dark:text-sky-400 dark:hover:bg-sky-900/60 transition-colors cursor-pointer" data-index="${index}" title="View timetable grid and timings" aria-label="View timetable grid and timings">
                <span class="material-symbols-outlined text-[17px] leading-none">grid_on</span>
              </button>
              <span class="inline-flex items-center justify-center w-7 h-7 text-slate-300 dark:text-slate-600" title="Auto-synced timetable">
                <span class="material-symbols-outlined text-[17px] leading-none">lock</span>
              </span>
            </div>`
          : window.TransitUI && window.TransitUI.renderActionButtons
          ? window.TransitUI.renderActionButtons({
              index,
              showGrid: true,
              gridClass: 'edit-matrix-btn open-editor-btn',
              editClass: 'edit-timetable-btn edit-row-btn',
              deleteClass: 'delete-timetable-btn remove-row-btn',
              gridTitle: 'Edit timetable grid and timings',
              editTitle: 'Edit timetable metadata',
              deleteTitle: 'Delete timetable',
            })
          : `<div class="flex items-center gap-1.5 justify-end">
              <button type="button" class="edit-matrix-btn open-editor-btn w-7 h-7 rounded-lg bg-sky-50 text-sky-600 cursor-pointer" data-index="${index}">
                <span class="material-symbols-outlined text-[17px] leading-none">grid_on</span>
              </button>
              <button type="button" class="edit-timetable-btn edit-row-btn w-7 h-7 rounded-lg bg-slate-100 text-slate-600 cursor-pointer" data-index="${index}">
                <span class="material-symbols-outlined text-[17px] leading-none">edit</span>
              </button>
              <button type="button" class="delete-timetable-btn remove-row-btn w-7 h-7 rounded-lg bg-rose-50 text-rose-600 cursor-pointer" data-index="${index}">
                <span class="material-symbols-outlined text-[17px] leading-none">delete</span>
              </button>
            </div>`;

        return [
          gridjs.html(
            `<div class="flex items-center gap-2.5">
              <span class="material-symbols-outlined text-slate-500 dark:text-slate-400 text-xl">${mode.icon}</span>
              <div>
                <div class="flex items-center gap-1 font-semibold text-slate-900 dark:text-slate-100">
                  <span>${escapeHtml(item.name)}</span>${autoBadge}
                </div>
                <div class="text-xs text-slate-500 dark:text-slate-400">${summaryText}</div>
              </div>
            </div>`
          ),
          gridjs.html(
            `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold whitespace-nowrap ${mode.badgeClass}">
              <span class="material-symbols-outlined text-xs leading-none">${mode.icon}</span>${mode.label}
            </span>`
          ),
          gridjs.html(startHtml),
          gridjs.html(endHtml),
          gridjs.html(renderDaysHtml(item)),
          gridjs.html(actionsHtml),
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
    const columnSortMap = {
      0: 'name',
      1: 'transport_type',
      2: 'start_date',
      3: 'end_date',
    };

    function syncEmptyState(total) {
      const effective = Math.max(
        0,
        (Number(total) || 0) +
          changesetManager.added.length -
          changesetManager.deleted.size
      );
      if (gridContainer) gridContainer.classList.toggle('hidden', effective === 0);
      if (emptyState) emptyState.classList.toggle('hidden', effective > 0);
    }

    function syncDirtyState() {
      if (window.ConfigDirtyManager) {
        if (changesetManager.isDirty()) {
          window.ConfigDirtyManager.markDirty();
        } else {
          window.ConfigDirtyManager.clearDirty();
        }
      }
    }

    const grid = new gridjs.Grid({
      columns: columnsConfig,
      server: {
        url: dataUrl,
        then: (data) => {
          const rawItems = (Array.isArray(data.data) ? data.data : []).map(
            normaliseItem
          );
          currentPageItems = changesetManager.applyOverlay(rawItems);
          syncEmptyState(data.total);
          return formatGridData(currentPageItems);
        },
        total: (data) =>
          Math.max(
            0,
            (Number(data.total) || 0) +
              changesetManager.added.length -
              changesetManager.deleted.size
          ),
      },
      pagination: {
        enabled: true,
        limit: 8,
        summary: true,
        server: {
          url: (prev, page, limit) => {
            const u = new URL(prev, window.location.origin);
            u.searchParams.set('limit', limit);
            u.searchParams.set('offset', page * limit);
            return u.pathname + u.search;
          },
        },
      },
      sort: {
        multiColumn: false,
        server: {
          url: (prev, columns) => {
            const u = new URL(prev, window.location.origin);
            if (!columns || !columns.length) return u.pathname + u.search;
            const col = columns[0];
            const field = columnSortMap[col.index];
            if (field) {
              u.searchParams.set('sort_by', field);
              u.searchParams.set('order', col.direction === 1 ? 'asc' : 'desc');
            }
            return u.pathname + u.search;
          },
        },
      },
      search: { enabled: true, placeholder: 'Search timetables...' },
      language: {
        search: { placeholder: 'Search timetables...' },
        pagination: {
          previous: 'Previous',
          next: 'Next',
          showing: 'Showing',
          results: () => 'timetables',
        },
      },
    });

    if (gridContainer) grid.render(gridContainer);

    if (window.ConfigDirtyManager) {
      window.ConfigDirtyManager.registerDiscardHandler(() => {
        changesetManager.reset();
        closeEditor();
        syncDirtyState();
        grid.forceRender();
      });
    }

    if (window.ConfigSave) {
      window.ConfigSave.register({
        endpoint: dataUrl,
        getChangeset: () => changesetManager.getChangeset(),
        onSaveSuccess: () => {
          changesetManager.reset();
          syncDirtyState();
          grid.forceRender();
        },
      });
    }

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

    function showEditModal(index) {
      if (index < 0 || index >= currentPageItems.length) return;
      currentEditIndex = index;
      const item = currentPageItems[index];
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

    function openEditor(idx) {
      if (idx < 0 || idx >= currentPageItems.length) return;
      if (window.TimetableGridEditor) {
        window.TimetableGridEditor.open(currentPageItems[idx]);
      }
    }

    function closeEditor() {
      if (window.TimetableGridEditor) {
        window.TimetableGridEditor.close();
      }
    }

    function handleGridActionClick(e) {
      const openEditorBtn = e.target.closest(
        '.edit-matrix-btn, .open-editor-btn'
      );
      if (openEditorBtn) {
        const idx = parseInt(openEditorBtn.getAttribute('data-index'), 10);
        if (!isNaN(idx)) openEditor(idx);
        return;
      }

      const editBtn = e.target.closest('.edit-timetable-btn, .edit-row-btn');
      if (editBtn) {
        const idx = parseInt(editBtn.getAttribute('data-index'), 10);
        if (!isNaN(idx)) showEditModal(idx);
        return;
      }

      const removeBtn = e.target.closest(
        '.delete-timetable-btn, .remove-row-btn'
      );
      if (removeBtn) {
        const idx = parseInt(removeBtn.getAttribute('data-index'), 10);
        if (!isNaN(idx) && idx >= 0 && idx < currentPageItems.length) {
          const item = currentPageItems[idx];
          if (item && item.id !== undefined) {
            changesetManager.delete(item.id);
            syncDirtyState();
            grid.forceRender();
          }
        }
      }
    }

    document.addEventListener('click', handleGridActionClick);
    if (gridContainer) {
      gridContainer.addEventListener('click', handleGridActionClick);
    }

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

        if (
          currentEditIndex >= 0 &&
          currentEditIndex < currentPageItems.length
        ) {
          payloadItem.id = currentPageItems[currentEditIndex].id;
          payloadItem.content = currentPageItems[currentEditIndex].content;
          const norm = normaliseItem(payloadItem);
          changesetManager.update(norm.id, norm);
        } else {
          payloadItem.id = -1 * (changesetManager.added.length + 1);
          payloadItem.content = { stops: [], trips: [] };
          const norm = normaliseItem(payloadItem);
          changesetManager.add(norm);
        }

        syncDirtyState();
        syncEmptyState(1);
        grid.forceRender();
        closeModal();
      });
    }

    if (window.TimetableGridEditor) {
      window.TimetableGridEditor.init({
        onSave: (updatedItem) => {
          changesetManager.update(updatedItem.id, updatedItem);
          syncDirtyState();
        },
        onBack: () => {
          syncDirtyState();
          grid.forceRender();
        },
      });
    }

    window.__timetablesController = {
      openEditor,
      closeEditor,
      getStaged: () => currentPageItems,
    };
  } catch (err) {
    window.__timetablesError = err.stack || err.toString();
    console.error('Timetables DOMContentLoaded Error:', err);
  }
});
