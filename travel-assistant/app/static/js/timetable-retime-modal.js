/**
 * Timetable Retime & Duplicate Modal Component.
 * Manages interval retiming, multi-trip duplication, and start-time alignment.
 */
(function () {
  'use strict';

  let retimeModal = null;
  let retimeSingleOptions = null;
  let retimeMethodOffset = null;
  let retimeMethodStartTime = null;
  let retimeMethodOffsetLbl = null;
  let retimeMethodStartTimeLbl = null;
  let retimeStartTimeContainer = null;
  let retimeOffsetContainer = null;
  let retimeStartTimeInput = null;
  let retimeOffsetInput = null;
  let retimeCopyCountInput = null;
  let retimePreviewText = null;
  let retimeError = null;
  let closeRetimeBtn = null;
  let cancelRetimeBtn = null;
  let confirmRetimeBtn = null;

  let activeItem = null;
  let targetRetimeIndices = [];
  let onApplyCallback = null;

  function getUtils() {
    return window.TimetableTimeUtils;
  }

  function init() {
    retimeModal = document.getElementById('retime-modal');
    retimeSingleOptions = document.getElementById('retime-single-trip-options');
    retimeMethodOffset = document.getElementById('retime-method-offset');
    retimeMethodStartTime = document.getElementById('retime-method-starttime');
    retimeMethodOffsetLbl = document.getElementById('retime-method-offset-lbl');
    retimeMethodStartTimeLbl = document.getElementById(
      'retime-method-starttime-lbl'
    );
    retimeStartTimeContainer = document.getElementById(
      'retime-starttime-container'
    );
    retimeOffsetContainer = document.getElementById('retime-offset-container');
    retimeStartTimeInput = document.getElementById('retime_start_time');
    retimeOffsetInput = document.getElementById('retime_offset_minutes');
    retimeCopyCountInput = document.getElementById('retime_copy_count');
    retimePreviewText = document.getElementById('retime-preview-text');
    retimeError = document.getElementById('retime-validation-error');
    closeRetimeBtn = document.getElementById('close-retime-btn');
    cancelRetimeBtn = document.getElementById('cancel-retime-btn');
    confirmRetimeBtn = document.getElementById('confirm-retime-btn');

    if (retimeMethodOffset) {
      retimeMethodOffset.addEventListener('change', updateMethodVisuals);
    }
    if (retimeMethodStartTime) {
      retimeMethodStartTime.addEventListener('change', updateMethodVisuals);
    }

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
          updatePreview();
        }
      });
    });

    if (retimeCopyCountInput) {
      retimeCopyCountInput.addEventListener('input', updatePreview);
    }
    if (retimeOffsetInput) {
      retimeOffsetInput.addEventListener('input', updatePreview);
    }

    if (closeRetimeBtn) closeRetimeBtn.addEventListener('click', close);
    if (cancelRetimeBtn) cancelRetimeBtn.addEventListener('click', close);

    if (confirmRetimeBtn) {
      confirmRetimeBtn.addEventListener('click', handleConfirm);
    }
  }

  function updateMethodVisuals() {
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
      if (retimeOffsetContainer) retimeOffsetContainer.classList.add('hidden');
    }
    updatePreview();
  }

  function updatePreview() {
    if (!retimePreviewText) return;
    const copies = parseInt(retimeCopyCountInput?.value || '1', 10);
    const count = targetRetimeIndices.length;
    const totalNew = (isNaN(copies) ? 1 : copies) * count;
    retimePreviewText.textContent = `Generates ${totalNew} duplicated trip ${
      totalNew === 1 ? 'column' : 'columns'
    }.`;
  }

  function open(tripIndices, item, onApply) {
    if (!item || !tripIndices || tripIndices.length === 0) return;
    activeItem = item;
    targetRetimeIndices = tripIndices;
    onApplyCallback = onApply;

    if (retimeError) retimeError.classList.add('hidden');

    const utils = getUtils();
    const isSingle = targetRetimeIndices.length === 1;
    if (retimeSingleOptions) {
      if (isSingle) {
        retimeSingleOptions.classList.remove('hidden');
        const targetTrip = activeItem.content.trips[targetRetimeIndices[0]];
        const firstDep = utils.getTripFirstDepartureMinutes(targetTrip);
        if (retimeStartTimeInput) {
          retimeStartTimeInput.value =
            firstDep !== null
              ? utils.shiftTime(utils.minutesToTime(firstDep), 60)
              : '09:00';
        }
      } else {
        retimeSingleOptions.classList.add('hidden');
      }
    }

    if (retimeMethodOffset) retimeMethodOffset.checked = true;
    updateMethodVisuals();

    if (retimeOffsetInput) retimeOffsetInput.value = '60';
    if (retimeCopyCountInput) retimeCopyCountInput.value = '1';
    updatePreview();

    if (retimeModal && typeof retimeModal.showModal === 'function') {
      retimeModal.showModal();
    }
  }

  function close() {
    if (retimeModal && typeof retimeModal.close === 'function') {
      retimeModal.close();
    }
  }

  function handleConfirm() {
    if (!activeItem || targetRetimeIndices.length === 0) return;
    const utils = getUtils();
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
      const newStartTimeStr = retimeStartTimeInput?.value?.trim();
      const newStartMins = utils.timeToMinutes(newStartTimeStr);
      if (newStartMins === null) {
        if (retimeError) {
          retimeError.textContent =
            'Please provide a valid start time in HH:MM format.';
          retimeError.classList.remove('hidden');
        }
        return;
      }

      const sourceTrip = activeItem.content.trips[targetRetimeIndices[0]];
      const origStartMins = utils.getTripFirstDepartureMinutes(sourceTrip);
      const baseShift =
        origStartMins !== null ? newStartMins - origStartMins : 0;

      for (let c = 0; c < copies; c++) {
        const shiftDelta = baseShift + c * offsetMinutes;
        const clonedTimes = (sourceTrip.times || []).map((t) =>
          t ? utils.shiftTimeEntry(t, shiftDelta) : ''
        );
        newTrips.push({
          id: `trip_${Date.now()}_${c}_${Math.random()
            .toString(16)
            .slice(2, 6)}`,
          times: clonedTimes,
        });
      }
    } else {
      for (let c = 1; c <= copies; c++) {
        targetRetimeIndices.forEach((tripIdx) => {
          const sourceTrip = activeItem.content.trips[tripIdx];
          if (!sourceTrip) return;
          const shiftDelta = c * offsetMinutes;
          const clonedTimes = (sourceTrip.times || []).map((t) =>
            t ? utils.shiftTimeEntry(t, shiftDelta) : ''
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

    if (typeof onApplyCallback === 'function') {
      onApplyCallback(newTrips);
    }
    close();
  }

  window.TimetableRetimeModal = {
    init,
    open,
    close,
  };
})();
