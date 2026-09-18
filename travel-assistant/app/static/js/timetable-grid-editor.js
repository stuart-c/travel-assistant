/**
 * Timetable Grid Editor Component.
 * Full-width matrix spreadsheet editor for stops, trips, and timings.
 */
(function () {
  'use strict';

  let editorView = null;
  let listView = null;
  let editorBreadcrumbName = null;
  let editorTitle = null;
  let editorModeIcon = null;
  let editorModeText = null;
  let editorModeBadge = null;
  let editorBackBtn = null;
  let editorBackLink = null;
  let matrixMount = null;
  let validationBanner = null;

  let addTripBtn = null;
  let clearTripsBtn = null;
  let selectionBar = null;
  let selectionCountText = null;
  let retimeSelectedBtn = null;
  let deleteSelectedBtn = null;
  let deselectBtn = null;

  let matrixStopAutocomplete = null;
  let activeEditorItem = null;
  const selectedTripIndices = new Set();
  let onSaveCallback = null;
  let onBackCallback = null;

  function getUtils() {
    return window.TimetableTimeUtils;
  }

  function getEscapeHtml() {
    return (
      (window.TransitUI && window.TransitUI.escapeHtml) ||
      function (str) {
        if (!str) return '';
        return String(str)
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;');
      }
    );
  }

  function getTransportModes() {
    return (
      (window.TransitUI && window.TransitUI.TRANSPORT_MODES) || {
        bus: {
          label: 'Bus',
          icon: 'directions_bus',
          badgeClass:
            'bg-sky-100 text-sky-800 dark:bg-sky-950/80 dark:text-sky-300 dark:ring-1 dark:ring-sky-500/30',
        },
        rail: {
          label: 'Train',
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
      }
    );
  }

  function init(options) {
    onSaveCallback = options?.onSave || null;
    onBackCallback = options?.onBack || null;

    editorView = document.getElementById('timetable-editor-view');
    listView = document.getElementById('timetables-list-view');
    editorBreadcrumbName = document.getElementById('editor-breadcrumb-name');
    editorTitle = document.getElementById('editor-title');
    editorModeIcon = document.getElementById('editor-mode-icon');
    editorModeText = document.getElementById('editor-mode-text');
    editorModeBadge = document.getElementById('editor-mode-badge');
    editorBackBtn = document.getElementById('editor-back-btn');
    editorBackLink = document.getElementById('editor-back-link');
    matrixMount = document.getElementById('timetable-matrix-mount');
    validationBanner = document.getElementById('grid-validation-banner');

    addTripBtn = document.getElementById('editor-add-trip-btn');
    clearTripsBtn = document.getElementById('editor-clear-trips-btn');
    selectionBar = document.getElementById('editor-selection-bar');
    selectionCountText = document.getElementById('selection-count-text');
    retimeSelectedBtn = document.getElementById('editor-retime-selected-btn');
    deleteSelectedBtn = document.getElementById('editor-delete-selected-btn');
    deselectBtn = document.getElementById('editor-deselect-btn');

    if (editorBackBtn) editorBackBtn.addEventListener('click', close);
    if (editorBackLink) editorBackLink.addEventListener('click', close);

    if (addTripBtn) {
      addTripBtn.addEventListener('click', () => {
        if (!activeEditorItem) return;
        const stopsCount = (activeEditorItem.content.stops || []).length;
        activeEditorItem.content.trips = activeEditorItem.content.trips || [];
        activeEditorItem.content.trips.push({
          id: `trip_${Date.now()}_${Math.random().toString(16).slice(2, 6)}`,
          times: new Array(stopsCount).fill(''),
        });
        renderMatrix();
        syncState();
      });
    }

    if (clearTripsBtn) {
      clearTripsBtn.addEventListener('click', () => {
        if (!activeEditorItem) return;
        activeEditorItem.content.trips = [];
        selectedTripIndices.clear();
        renderMatrix();
        syncState();
      });
    }

    if (retimeSelectedBtn) {
      retimeSelectedBtn.addEventListener('click', () => {
        if (selectedTripIndices.size > 0) {
          triggerRetimeModal(
            Array.from(selectedTripIndices).sort((a, b) => a - b)
          );
        }
      });
    }

    if (deleteSelectedBtn) {
      deleteSelectedBtn.addEventListener('click', () => {
        if (!activeEditorItem || selectedTripIndices.size === 0) return;
        activeEditorItem.content.trips = activeEditorItem.content.trips.filter(
          (_, idx) => !selectedTripIndices.has(idx)
        );
        selectedTripIndices.clear();
        renderMatrix();
        syncState();
      });
    }

    if (deselectBtn) {
      deselectBtn.addEventListener('click', () => {
        selectedTripIndices.clear();
        renderMatrix();
      });
    }

    setupStopSearchAutocomplete();
    if (window.TimetableRetimeModal) {
      window.TimetableRetimeModal.init();
    }
  }

  function triggerRetimeModal(tripIndices) {
    if (!window.TimetableRetimeModal || !activeEditorItem) return;
    window.TimetableRetimeModal.open(
      tripIndices,
      activeEditorItem,
      (newTrips) => {
        const utils = getUtils();
        activeEditorItem.content.trips = utils.sortTripsChronologically([
          ...activeEditorItem.content.trips,
          ...newTrips,
        ]);
        selectedTripIndices.clear();
        renderMatrix();
        syncState();
      }
    );
  }

  function open(item) {
    try {
      if (!item) return;
      activeEditorItem = item;
      selectedTripIndices.clear();

      if (matrixStopAutocomplete) {
        matrixStopAutocomplete.clear();
        matrixStopAutocomplete.resetFilter(item.transport_type || 'bus');
      }
      const modes = getTransportModes();
      const mode = modes[item.transport_type] || modes.bus;
      const escapeHtml = getEscapeHtml();

      if (editorBreadcrumbName) editorBreadcrumbName.textContent = item.name;
      if (editorTitle) {
        if (item.auto_added) {
          editorTitle.innerHTML = `${escapeHtml(
            item.name
          )} <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300 ml-2"><span class="material-symbols-outlined text-sm leading-none">cloud_sync</span>Auto-Synced (Read-Only)</span>`;
        } else {
          editorTitle.textContent = `${item.name}`;
        }
      }
      if (editorModeIcon) editorModeIcon.textContent = mode.icon;
      if (editorModeText) editorModeText.textContent = mode.label;
      if (editorModeBadge) {
        editorModeBadge.className = `inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold ${mode.badgeClass}`;
      }

      const stopSearchContainer = document
        .getElementById('matrix-stop-search-input')
        ?.closest('.relative');
      if (item.auto_added) {
        if (addTripBtn) addTripBtn.classList.add('hidden');
        if (clearTripsBtn) clearTripsBtn.classList.add('hidden');
        if (stopSearchContainer) stopSearchContainer.classList.add('hidden');
      } else {
        if (addTripBtn) addTripBtn.classList.remove('hidden');
        if (clearTripsBtn) clearTripsBtn.classList.remove('hidden');
        if (stopSearchContainer) stopSearchContainer.classList.remove('hidden');
      }

      if (listView) listView.classList.add('hidden');
      if (editorView) editorView.classList.remove('hidden');
      renderMatrix();
    } catch (err) {
      console.error('Error in TimetableGridEditor.open:', err);
    }
  }

  function close() {
    activeEditorItem = null;
    selectedTripIndices.clear();
    if (matrixStopAutocomplete) {
      matrixStopAutocomplete.clear();
    }
    if (editorView) editorView.classList.add('hidden');
    if (listView) listView.classList.remove('hidden');
    if (typeof onBackCallback === 'function') {
      onBackCallback();
    }
  }

  function syncState() {
    if (typeof onSaveCallback === 'function' && activeEditorItem) {
      onSaveCallback(activeEditorItem);
    }
  }

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

  function renderHeaderCell(trip, tIdx, isErr, isAuto, escapeHtml, utils) {
    const isSelected = selectedTripIndices.has(tIdx);
    const firstDep = utils.getTripFirstDepartureMinutes(trip);
    const firstDepStr =
      firstDep !== null ? utils.minutesToTime(firstDep) : `Trip ${tIdx + 1}`;
    const tocBadge = trip.toc
      ? `<span class="text-[10px] px-1.5 py-0.5 rounded font-mono font-bold bg-indigo-50 text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300" title="Operator: ${escapeHtml(
          trip.operator || trip.toc
        )}">${escapeHtml(trip.toc)}</span>`
      : '';

    const tripActionBtns = isAuto
      ? ''
      : `<div class="flex items-center gap-0.5">
          <button type="button" class="trip-retime-btn p-1 text-slate-400 hover:text-sky-600 dark:hover:text-sky-400 cursor-pointer rounded" data-trip-index="${tIdx}" title="Duplicate &amp; retime this trip">
            <span class="material-symbols-outlined text-sm leading-none">content_copy</span>
          </button>
          <button type="button" class="trip-delete-btn p-1 text-slate-400 hover:text-rose-600 dark:hover:text-rose-400 cursor-pointer rounded" data-trip-index="${tIdx}" title="Delete this trip column">
            <span class="material-symbols-outlined text-sm leading-none">delete</span>
          </button>
        </div>`;

    const selectCheckbox = isAuto
      ? '<span class="w-4"></span>'
      : `<input type="checkbox" class="trip-select-cb rounded border-slate-300 text-sky-600 focus:ring-sky-500 dark:border-slate-700 dark:bg-slate-800 cursor-pointer" data-trip-index="${tIdx}" ${
          isSelected ? 'checked' : ''
        } title="Select trip for duplicate/delete">`;

    const errBadgeCls = isErr
      ? 'bg-rose-100 text-rose-800 dark:bg-rose-950/80 dark:text-rose-300 ring-1 ring-rose-500/50'
      : 'bg-slate-200/80 text-slate-800 dark:bg-slate-700 dark:text-slate-200';

    return `
      <th class="min-w-[120px] p-2.5 text-center border-r border-slate-200 dark:border-slate-800 ${
        isSelected ? 'bg-sky-50 dark:bg-sky-950/40' : ''
      }">
        <div class="flex flex-col items-center gap-1.5">
          <div class="flex items-center justify-between w-full px-1">
            ${selectCheckbox}
            ${tripActionBtns}
          </div>
          <div class="flex items-center gap-1">
            <div class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-mono font-bold ${errBadgeCls}">
              ${firstDepStr}
            </div>
            ${tocBadge}
          </div>
        </div>
      </th>`;
  }

  function renderTimeCell(val, sIdx, tIdx, isErr, isSelected, isAuto, escapeHtml, utils) {
    const isDual = utils.isDualTiming(val);
    let cellContent = '';

    if (isDual) {
      const arrVal = typeof val === 'object' && val ? val.arr || '' : '';
      const depVal = typeof val === 'object' && val ? val.dep || '' : '';
      const inputCls = `${
        isAuto ? 'cursor-default opacity-85' : 'cursor-pointer'
      } ${
        isErr
          ? 'border-rose-500 bg-rose-50 dark:bg-rose-950/50 text-rose-700 dark:text-rose-300 ring-1 ring-rose-500/30'
          : 'border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:border-sky-500 focus:ring-2 focus:ring-sky-500/20'
      }`;

      cellContent = `
        <div class="inline-flex flex-col gap-1 items-center">
          <div class="flex items-center gap-1">
            <span class="text-[9px] font-bold tracking-wider px-1 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 font-mono select-none" title="Arrival Time">ARR</span>
            <input type="time" ${isAuto ? 'readonly' : ''} class="matrix-time-input matrix-time-arr w-20 px-1.5 py-0.5 text-xs font-mono rounded border text-center transition-colors ${inputCls}" data-stop-index="${sIdx}" data-trip-index="${tIdx}" data-mode="dual" data-field="arr" value="${escapeHtml(arrVal)}" title="Arrival time. Double-click to collapse.">
          </div>
          <div class="flex items-center gap-1">
            <span class="text-[9px] font-bold tracking-wider px-1 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 font-mono select-none" title="Departure Time">DEP</span>
            <input type="time" ${isAuto ? 'readonly' : ''} class="matrix-time-input matrix-time-dep w-20 px-1.5 py-0.5 text-xs font-mono rounded border text-center transition-colors ${inputCls}" data-stop-index="${sIdx}" data-trip-index="${tIdx}" data-mode="dual" data-field="dep" value="${escapeHtml(depVal)}" title="Departure time. Double-click to collapse.">
          </div>
        </div>`;
    } else {
      const singleVal = typeof val === 'string' ? val : '';
      const inputCls = `${
        isAuto ? 'cursor-default opacity-85' : 'cursor-pointer'
      } ${
        isErr
          ? 'border-rose-500 bg-rose-50 dark:bg-rose-950/50 text-rose-700 dark:text-rose-300 ring-2 ring-rose-500/30'
          : 'border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:border-sky-500 focus:ring-2 focus:ring-sky-500/20'
      }`;

      cellContent = `
        <input type="time" ${isAuto ? 'readonly' : ''} class="matrix-time-input w-24 px-2 py-1 text-xs font-mono rounded-lg border text-center transition-colors ${inputCls}" data-stop-index="${sIdx}" data-trip-index="${tIdx}" data-mode="single" value="${escapeHtml(singleVal)}" title="Scheduled departure time. Double-click to split into Arrival & Departure.">`;
    }

    return `
      <td class="p-1.5 text-center border-r border-slate-200 dark:border-slate-800 ${
        isSelected ? 'bg-sky-50/40 dark:bg-sky-950/20' : ''
      }">
        ${cellContent}
      </td>`;
  }

  function renderMatrix() {
    if (!activeEditorItem || !matrixMount) return;

    const timetable = activeEditorItem;
    const stops = timetable.content.stops || [];
    let trips = timetable.content.trips || [];
    const escapeHtml = getEscapeHtml();
    const utils = getUtils();

    trips.forEach((t) => {
      if (!Array.isArray(t.times)) t.times = [];
      while (t.times.length < stops.length) t.times.push('');
    });

    let hasAnySequenceError = false;
    const tripErrors = trips.map((t) => {
      const errs = utils.validateTripColumn(t, stops.length);
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
    const isAuto = Boolean(activeEditorItem?.auto_added);

    let tableHtml = `
      <table class="w-full text-left border-collapse border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden bg-white dark:bg-slate-900">
        <thead>
          <tr class="bg-slate-50 dark:bg-slate-800/60 border-b border-slate-200 dark:border-slate-800">
            <th class="sticky left-0 z-20 bg-slate-100 dark:bg-slate-800 min-w-[280px] max-w-[320px] p-3 text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300 border-r border-slate-200 dark:border-slate-700 shadow-sm">
              <div class="flex items-center justify-between">
                <span>Stops &amp; Places (${stops.length})</span>
                <span class="text-[11px] font-normal text-slate-500 dark:text-slate-400">Sequence</span>
              </div>
            </th>
    `;

    if (trips.length === 0) {
      tableHtml += `
            <th class="p-6 text-center text-xs font-semibold text-slate-400 dark:text-slate-500 italic">
              No trip columns configured. Click "Add Trip Column" above.
            </th>`;
    } else {
      trips.forEach((trip, tIdx) => {
        const isErr = tripErrors[tIdx].size > 0;
        tableHtml += renderHeaderCell(trip, tIdx, isErr, isAuto, escapeHtml, utils);
      });
    }

    tableHtml += `
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-200 dark:divide-slate-800">
    `;

    if (stops.length === 0) {
      tableHtml += `
          <tr>
            <td colspan="${Math.max(1, trips.length) + 1}" class="p-8 text-center text-slate-500 dark:text-slate-400">
              <span class="material-symbols-outlined text-3xl text-slate-400 dark:text-slate-500 mb-1">signpost</span>
              <p class="text-sm font-semibold">No stops configured for this timetable</p>
              <p class="text-xs text-slate-400 mt-0.5">Use the search box below to add stops matching this timetable type, custom locations, or Home Assistant zones.</p>
            </td>
          </tr>`;
    } else {
      stops.forEach((stop, sIdx) => {
        const icon = stop.icon || 'place';
        const indicator = stop.indicator || stop.type || 'Stop';

        const stopActionBtns = isAuto
          ? ''
          : `<div class="flex items-center gap-0.5 flex-shrink-0">
              <button type="button" class="stop-move-up-btn p-1 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed" data-stop-index="${sIdx}" ${sIdx === 0 ? 'disabled' : ''} title="Move stop up">
                <span class="material-symbols-outlined text-sm leading-none">arrow_upward</span>
              </button>
              <button type="button" class="stop-move-down-btn p-1 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed" data-stop-index="${sIdx}" ${sIdx === stops.length - 1 ? 'disabled' : ''} title="Move stop down">
                <span class="material-symbols-outlined text-sm leading-none">arrow_downward</span>
              </button>
              <button type="button" class="stop-delete-btn p-1 text-slate-400 hover:text-rose-600 dark:hover:text-rose-400 cursor-pointer rounded" data-stop-index="${sIdx}" title="Remove stop">
                <span class="material-symbols-outlined text-sm leading-none">close</span>
              </button>
            </div>`;

        tableHtml += `
          <tr class="hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition-colors">
            <td class="sticky left-0 z-10 bg-white dark:bg-slate-900 p-2.5 border-r border-slate-200 dark:border-slate-800 shadow-sm">
              <div class="flex items-center justify-between gap-2">
                <div class="flex items-center gap-2 min-w-0">
                  <span class="material-symbols-outlined text-slate-400 text-base flex-shrink-0">${icon}</span>
                  <div class="min-w-0">
                    <div class="text-xs font-semibold text-slate-900 dark:text-slate-100 truncate" title="${escapeHtml(stop.name)}">
                      ${escapeHtml(stop.name)}
                    </div>
                    <div class="text-[10px] text-slate-400 dark:text-slate-500 truncate">
                      ${escapeHtml(indicator)}
                    </div>
                  </div>
                </div>
                ${stopActionBtns}
              </div>
            </td>`;

        trips.forEach((trip, tIdx) => {
          const val = trip.times[sIdx] || '';
          const isErr = tripErrors[tIdx].has(sIdx);
          const isSelected = selectedTripIndices.has(tIdx);
          tableHtml += renderTimeCell(val, sIdx, tIdx, isErr, isSelected, isAuto, escapeHtml, utils);
        });

        tableHtml += `</tr>`;
      });
    }

    tableHtml += `
        </tbody>
      </table>`;

    matrixMount.innerHTML = tableHtml;
    attachMatrixEventListeners();
  }

  function attachMatrixEventListeners() {
    if (!activeEditorItem) return;
    const timetable = activeEditorItem;
    if (timetable.auto_added) return;
    const utils = getUtils();

    const timeInputs = matrixMount.querySelectorAll('.matrix-time-input');
    timeInputs.forEach((input) => {
      input.addEventListener('dblclick', (e) => {
        const sIdx = parseInt(e.target.getAttribute('data-stop-index'), 10);
        const tIdx = parseInt(e.target.getAttribute('data-trip-index'), 10);
        const mode = e.target.getAttribute('data-mode');

        if (
          !isNaN(sIdx) &&
          !isNaN(tIdx) &&
          timetable.content.trips[tIdx] &&
          Array.isArray(timetable.content.trips[tIdx].times)
        ) {
          if (mode === 'single') {
            const currentVal = e.target.value.trim();
            timetable.content.trips[tIdx].times[sIdx] = {
              arr: currentVal,
              dep: currentVal,
            };
          } else if (mode === 'dual') {
            const currentEntry = timetable.content.trips[tIdx].times[sIdx];
            let collapsedTime = '';
            if (utils.isDualTiming(currentEntry)) {
              collapsedTime = currentEntry.dep || currentEntry.arr || '';
            } else if (typeof currentEntry === 'string') {
              collapsedTime = currentEntry;
            }
            timetable.content.trips[tIdx].times[sIdx] = collapsedTime;
          }

          renderMatrix();
          syncState();

          setTimeout(() => {
            const targetInput = matrixMount.querySelector(
              `.matrix-time-input[data-stop-index="${sIdx}"][data-trip-index="${tIdx}"]`
            );
            if (targetInput) targetInput.focus();
          }, 0);
        }
      });

      input.addEventListener('change', (e) => {
        const sIdx = parseInt(e.target.getAttribute('data-stop-index'), 10);
        const tIdx = parseInt(e.target.getAttribute('data-trip-index'), 10);
        const mode = e.target.getAttribute('data-mode');

        if (
          !isNaN(sIdx) &&
          !isNaN(tIdx) &&
          timetable.content.trips[tIdx] &&
          Array.isArray(timetable.content.trips[tIdx].times)
        ) {
          const newVal = e.target.value.trim();
          if (mode === 'single') {
            timetable.content.trips[tIdx].times[sIdx] = newVal;
          } else if (mode === 'dual') {
            const field = e.target.getAttribute('data-field');
            let entry = timetable.content.trips[tIdx].times[sIdx];
            if (!utils.isDualTiming(entry)) {
              entry = { arr: '', dep: '' };
            } else {
              entry = { ...entry };
            }
            entry[field] = newVal;

            if (!entry.arr && !entry.dep) {
              timetable.content.trips[tIdx].times[sIdx] = '';
            } else {
              timetable.content.trips[tIdx].times[sIdx] = entry;
            }
          }

          timetable.content.trips = utils.sortTripsChronologically(
            timetable.content.trips
          );
          renderMatrix();
          syncState();
        }
      });
    });

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

    const moveUpBtns = matrixMount.querySelectorAll('.stop-move-up-btn');
    moveUpBtns.forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const sIdx = parseInt(
          e.target.closest('button').getAttribute('data-stop-index'),
          10
        );
        if (!isNaN(sIdx) && sIdx > 0) {
          const tempStop = timetable.content.stops[sIdx];
          timetable.content.stops[sIdx] = timetable.content.stops[sIdx - 1];
          timetable.content.stops[sIdx - 1] = tempStop;

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

    const moveDownBtns = matrixMount.querySelectorAll('.stop-move-down-btn');
    moveDownBtns.forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const sIdx = parseInt(
          e.target.closest('button').getAttribute('data-stop-index'),
          10
        );
        if (!isNaN(sIdx) && sIdx < timetable.content.stops.length - 1) {
          const tempStop = timetable.content.stops[sIdx];
          timetable.content.stops[sIdx] = timetable.content.stops[sIdx + 1];
          timetable.content.stops[sIdx + 1] = tempStop;

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

    const tripRetimeBtns = matrixMount.querySelectorAll('.trip-retime-btn');
    tripRetimeBtns.forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const tIdx = parseInt(
          e.target.closest('button').getAttribute('data-trip-index'),
          10
        );
        if (!isNaN(tIdx)) {
          triggerRetimeModal([tIdx]);
        }
      });
    });

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
  }

  function setupStopSearchAutocomplete() {
    const searchInput = document.getElementById('matrix-stop-search-input');
    const resultsContainer = document.getElementById(
      'matrix-stop-search-results'
    );
    if (!searchInput || !resultsContainer) return;

    matrixStopAutocomplete = window.PlaceAutocomplete
      ? window.PlaceAutocomplete.create({
          inputEl: searchInput,
          suggestionsEl: resultsContainer,
          defaultFilter: 'bus',
          onSelect: (place) => {
            addStopToTimetable(place);
            if (matrixStopAutocomplete) {
              matrixStopAutocomplete.clear();
            }
          },
        })
      : null;
  }

  function addStopToTimetable(place) {
    if (!activeEditorItem) return;
    const timetable = activeEditorItem;
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

    timetable.content.trips.forEach((trip) => {
      if (!Array.isArray(trip.times)) trip.times = [];
      trip.times.push('');
    });

    renderMatrix();
    syncState();
  }

  window.TimetableGridEditor = {
    init,
    open,
    close,
    renderMatrix,
  };
})();
