/**
 * Journey Live Tracking Controller.
 * 
 * Manages real-time telemetry polling, Stuart's live location beacon,
 * abstract vertical schematic corridor diagrams (TfL / Rail style),
 * and view toggling with geographic mapping.
 */

document.addEventListener('DOMContentLoaded', () => {
  const root = document.getElementById('journey-tracker-root');
  if (!root) return;

  const ingressPath = document.body.dataset.ingressPath || '';
  const initialDataEl = document.getElementById('initial-tracking-data');
  let trackingData = null;

  if (initialDataEl && initialDataEl.textContent.trim()) {
    try {
      trackingData = JSON.parse(initialDataEl.textContent);
    } catch (err) {
      console.error('Could not parse initial tracking data:', err);
    }
  }

  // DOM element references
  const journeySelect = document.getElementById('journey-select');
  const btnRefresh = document.getElementById('btn-refresh-telemetry');
  const refreshIcon = document.getElementById('refresh-icon');
  const liveIndicatorBadge = document.getElementById('live-indicator-badge');
  const badgeStatusText = document.getElementById('badge-status-text');

  // View Switcher Buttons
  const btnViewSchematic = document.getElementById('btn-view-schematic');
  const btnViewMap = document.getElementById('btn-view-map');
  const schematicViewWrapper = document.getElementById('schematic-view-wrapper');
  const geographicMapWrapper = document.getElementById('geographic-map-wrapper');
  const schematicContainer = document.getElementById('schematic-diagram-container');

  // Hero elements
  const journeyOverviewSub = document.getElementById('journey-overview-sub');
  const journeyTerminals = document.getElementById('journey-terminals');
  const heroStageTitle = document.getElementById('hero-stage-title');
  const heroStageIcon = document.getElementById('hero-stage-icon');
  const heroStageLabel = document.getElementById('hero-stage-label');
  const heroDepTime = document.getElementById('hero-dep-time');
  const heroArrTime = document.getElementById('hero-arr-time');
  const heroNextStepText = document.getElementById('hero-next-step-text');
  const heroMessageText = document.getElementById('hero-message-text');

  // Telemetry elements
  const telemetryPersonState = document.getElementById('telemetry-person-state');
  const telemetryPersonCoords = document.getElementById('telemetry-person-coords');
  const telemetryDistNext = document.getElementById('telemetry-dist-next');
  const telemetryDistDest = document.getElementById('telemetry-dist-dest');
  const telemetryPlatform = document.getElementById('telemetry-platform');
  const telemetryLiveStatus = document.getElementById('telemetry-live-status');
  const telemetryLastUpdated = document.getElementById('telemetry-last-updated');

  // Map state
  let map = null;
  let waypointsLayer = null;
  let routePolyline = null;
  let stuartMarker = null;

  const DEFAULT_CENTRE = [51.5074, -0.1278]; // London
  const DEFAULT_ZOOM = 13;

  function initMap() {
    const mapEl = document.getElementById('journey-map');
    if (!mapEl || typeof L === 'undefined') return;

    map = L.map('journey-map', {
      zoomControl: true,
      attributionControl: true,
    }).setView(DEFAULT_CENTRE, DEFAULT_ZOOM);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map);

    waypointsLayer = L.featureGroup().addTo(map);

    if (trackingData && trackingData.selected_journey) {
      renderJourneyMap(trackingData);
    }
  }

  function createWaypointIcon(type) {
    let bgColour = '#6366f1'; // Indigo for stop
    let iconName = 'pin_drop';

    if (type === 'origin') {
      bgColour = '#10b981'; // Green
      iconName = 'home';
    } else if (type === 'destination') {
      bgColour = '#f43f5e'; // Rose
      iconName = 'flag';
    } else if (type === 'interchange') {
      bgColour = '#8b5cf6'; // Purple
      iconName = 'transfer_within_a_station';
    }

    return L.divIcon({
      className: 'custom-waypoint-marker',
      html: `
        <div class="waypoint-pin" style="background-color: ${bgColour};">
          <span class="material-symbols-outlined" style="font-size: 16px;">${iconName}</span>
        </div>
      `,
      iconSize: [28, 28],
      iconAnchor: [14, 14],
      popupAnchor: [0, -14],
    });
  }

  function createStuartIcon() {
    return L.divIcon({
      className: 'custom-stuart-beacon',
      html: `
        <div class="stuart-beacon-wrapper">
          <div class="stuart-beacon-ping"></div>
          <div class="stuart-beacon-core">
            <span class="material-symbols-outlined" style="font-size: 13px;">person</span>
          </div>
        </div>
      `,
      iconSize: [36, 36],
      iconAnchor: [18, 18],
      popupAnchor: [0, -18],
    });
  }

  function renderJourneyMap(data) {
    if (!map || !data) return;

    waypointsLayer.clearLayers();
    if (routePolyline) {
      map.removeLayer(routePolyline);
      routePolyline = null;
    }

    const j = data.selected_journey;
    const person = data.person;
    const allLatLngs = [];

    // 1. Draw route polyline and waypoint markers
    if (j && j.waypoints && j.waypoints.length > 0) {
      const polylineCoords = [];

      j.waypoints.forEach((wp) => {
        if (wp.lat != null && wp.lon != null) {
          const latLng = [wp.lat, wp.lon];
          polylineCoords.push(latLng);
          allLatLngs.push(latLng);

          const icon = createWaypointIcon(wp.type);
          const marker = L.marker(latLng, { icon }).addTo(waypointsLayer);
          marker.bindPopup(`
            <div class="p-1">
              <strong class="text-sm font-semibold">${wp.name || 'Waypoint'}</strong>
              <div class="text-xs text-slate-500">${wp.description || ''}</div>
            </div>
          `);
        }
      });

      if (polylineCoords.length > 1) {
        routePolyline = L.polyline(polylineCoords, {
          color: '#0284c7',
          weight: 4,
          opacity: 0.8,
          smoothFactor: 1,
        }).addTo(map);
      }
    }

    // 2. Render Stuart's Live Position Marker
    if (person && person.latitude != null && person.longitude != null) {
      const stuartLatLng = [person.latitude, person.longitude];
      allLatLngs.push(stuartLatLng);

      const stuartIcon = createStuartIcon();

      if (!stuartMarker) {
        stuartMarker = L.marker(stuartLatLng, {
          icon: stuartIcon,
          zIndexOffset: 1000,
        }).addTo(map);
      } else {
        stuartMarker.setLatLng(stuartLatLng);
      }

      const distNextText =
        person.distance_to_next_stop_m != null
          ? `${Math.round(person.distance_to_next_stop_m)}m to next stop`
          : '';

      stuartMarker.bindPopup(`
        <div class="p-1 min-w-[140px]">
          <div class="flex items-center gap-1.5 font-bold text-sm text-sky-700">
            <span class="material-symbols-outlined text-sm">person_pin</span>
            <span>Stuart's Real-time Position</span>
          </div>
          <div class="text-xs text-slate-600 mt-1">State: <strong>${person.state || 'Active'}</strong></div>
          ${distNextText ? `<div class="text-xs text-slate-500 mt-0.5">${distNextText}</div>` : ''}
          <div class="text-[10px] text-slate-400 mt-1">Updated: ${person.updated_at || 'Just now'}</div>
        </div>
      `);
    } else if (stuartMarker) {
      map.removeLayer(stuartMarker);
      stuartMarker = null;
    }

    // Fit map bounds to enclose all waypoints and Stuart
    if (allLatLngs.length > 0) {
      const bounds = L.latLngBounds(allLatLngs);
      map.fitBounds(bounds, {
        padding: [40, 40],
        maxZoom: 15,
      });
    }
  }

  function renderSchematicDiagram(data) {
    if (!schematicContainer || !data) return;
    const j = data.selected_journey;
    const person = data.person;

    if (!j || !j.schematic || !j.schematic.stages || j.schematic.stages.length === 0) {
      schematicContainer.innerHTML = `
        <div class="p-8 text-center text-sm text-slate-500 dark:text-slate-400">
          No active itinerary stages discovered for the selected journey.
        </div>
      `;
      return;
    }

    const stages = j.schematic.stages;
    const finalNode = j.schematic.final_node;
    const isActive = j.is_active;

    let html = '';

    stages.forEach((stage) => {
      const isFirst = stage.stage_index === 0;
      const isCurrent = stage.leg.is_current && isActive;
      const isCompleted = stage.leg.is_completed;

      // Node disc
      let nodeCircleHtml = '';
      if (isFirst) {
        nodeCircleHtml = `
          <div class="w-6 h-6 sm:w-7 sm:h-7 rounded-full border-4 border-emerald-500 bg-white dark:bg-slate-900 flex items-center justify-center z-10 shadow-xs">
            <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
          </div>
        `;
      } else {
        nodeCircleHtml = `<div class="schematic-station-interchange z-10"></div>`;
      }

      // Connecting vertical line styling
      let spineClass = 'schematic-spine-solid-slate';
      if (stage.line_style === 'dashed') {
        spineClass = 'schematic-spine-dashed-amber';
      } else if (stage.line_colour === 'indigo') {
        spineClass = 'schematic-spine-solid-indigo';
      } else if (stage.line_colour === 'rose') {
        spineClass = 'schematic-spine-solid-rose';
      } else if (stage.line_colour === 'sky') {
        spineClass = 'schematic-spine-solid-sky';
      } else if (stage.line_colour === 'emerald') {
        spineClass = 'schematic-spine-solid-emerald';
      }

      // Platform tag
      let platPill = '';
      if (stage.from_node.platform) {
        platPill = `
          <span class="px-2 py-0.5 rounded-md text-[11px] font-bold bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300">
            Plat ${escapeHtml(stage.from_node.platform)}
          </span>
        `;
      }

      // Stuart at node indicator
      let stuartNodeBeacon = '';
      if (stage.from_node.is_stuart_here) {
        stuartNodeBeacon = `
          <span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold bg-sky-600 text-white shadow-xs">
            <span class="material-symbols-outlined text-[14px]">person</span>
            <span>Stuart is here</span>
          </span>
        `;
      }

      // Interchange change banner
      let interchangeBanner = '';
      if (!isFirst) {
        const platNotice = stage.from_node.platform
          ? `<span class="font-semibold text-indigo-600 dark:text-indigo-400">Platform ${escapeHtml(stage.from_node.platform)}</span>`
          : '';
        interchangeBanner = `
          <div class="my-2 p-2.5 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-200/80 dark:border-slate-700/80 flex items-center justify-between gap-3 text-xs">
            <div class="flex items-center gap-2">
              <span class="material-symbols-outlined text-sm text-sky-600 dark:text-sky-400">sync_alt</span>
              <span class="font-semibold text-slate-800 dark:text-slate-200">
                Change here: Board ${escapeHtml(stage.leg.line || stage.leg.mode)}
              </span>
            </div>
            ${platNotice}
          </div>
        `;
      }

      // Card styling
      let legCardClass = 'border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-800/40';
      if (isCurrent) {
        legCardClass = 'border-sky-500 bg-sky-50/50 dark:border-sky-500/80 dark:bg-sky-950/30 ring-2 ring-sky-500/20';
      } else if (isCompleted) {
        legCardClass = 'border-slate-200/70 bg-slate-50/70 dark:border-slate-800 dark:bg-slate-900/40 opacity-80';
      }

      let modeIcon = 'directions_transit';
      let modeBg = 'bg-sky-100 text-sky-800 dark:bg-sky-950/80 dark:text-sky-300';
      if (stage.leg.mode === 'walk') {
        modeIcon = 'directions_walk';
        modeBg = 'bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-300';
      } else if (stage.leg.mode === 'rail') {
        modeIcon = 'train';
        modeBg = 'bg-indigo-100 text-indigo-800 dark:bg-indigo-950/80 dark:text-indigo-300';
      } else if (stage.leg.mode === 'bus') {
        modeIcon = 'directions_bus';
        modeBg = 'bg-rose-100 text-rose-800 dark:bg-rose-950/80 dark:text-rose-300';
      }

      const modeTitle =
        stage.leg.mode === 'walk'
          ? `Walk ${stage.leg.duration_minutes} mins`
          : `${escapeHtml(stage.leg.line || stage.leg.mode.toUpperCase())}${stage.leg.operator ? ` <span class="font-normal text-xs text-slate-500">(${escapeHtml(stage.leg.operator)})</span>` : ''}`;

      let completedBadge = '';
      if (isCompleted) {
        completedBadge = `
          <span class="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
            <span class="material-symbols-outlined text-[12px]">check</span>
            <span>Completed</span>
          </span>
        `;
      }

      // Stuart on-leg beacon banner
      let stuartLegBanner = '';
      if (stage.is_stuart_on_leg) {
        let nextStopSnippet = '';
        if (person && person.distance_to_next_stop_m != null) {
          const distStr =
            person.distance_to_next_stop_m >= 1000
              ? `${(person.distance_to_next_stop_m / 1000.0).toFixed(1)} km`
              : `${Math.round(person.distance_to_next_stop_m)}m`;
          nextStopSnippet = `<span class="text-sky-700 dark:text-sky-300 font-medium">Next stop: ${distStr}</span>`;
        }

        stuartLegBanner = `
          <div class="mt-3 p-3 rounded-lg bg-sky-500/10 border border-sky-500/30 flex items-center justify-between gap-3 text-xs">
            <div class="flex items-center gap-2">
              <span class="relative flex h-2.5 w-2.5">
                <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75"></span>
                <span class="relative inline-flex rounded-full h-2.5 w-2.5 bg-sky-500"></span>
              </span>
              <strong class="text-sky-900 dark:text-sky-200">
                ${escapeHtml(stage.stuart_status_text || 'Stuart in transit')}
              </strong>
            </div>
            ${nextStopSnippet}
          </div>
        `;
      }

      html += `
        <div class="relative flex items-start gap-4 sm:gap-6">
          <div class="flex flex-col items-center shrink-0 w-8 sm:w-10">
            ${nodeCircleHtml}
            <div class="w-1.5 flex-1 min-h-[90px] sm:min-h-[110px] my-1 ${spineClass}"></div>
          </div>

          <div class="flex-1 pb-8 min-w-0">
            <div class="flex items-center justify-between gap-2 flex-wrap mb-1">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-sm sm:text-base font-bold text-slate-900 dark:text-white">
                  ${escapeHtml(stage.from_node.name)}
                </span>
                ${platPill}
                ${stuartNodeBeacon}
              </div>
              <span class="text-xs font-mono font-bold text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded-md">
                ${escapeHtml(stage.from_node.time)}
              </span>
            </div>

            ${interchangeBanner}

            <div class="mt-3 p-4 rounded-xl border transition-all duration-200 ${legCardClass}">
              <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div class="flex items-start sm:items-center gap-3">
                  <div class="w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${modeBg}">
                    <span class="material-symbols-outlined text-lg">${modeIcon}</span>
                  </div>
                  <div>
                    <div class="flex items-center gap-2 flex-wrap">
                      <span class="text-sm font-bold text-slate-900 dark:text-white">
                        ${modeTitle}
                      </span>
                      ${completedBadge}
                    </div>
                    <div class="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                      Ride for ${stage.leg.duration_minutes} mins to ${escapeHtml(stage.to_node.name)}
                    </div>
                  </div>
                </div>

                <div class="text-right self-end sm:self-auto shrink-0">
                  <div class="text-xs font-mono font-semibold text-slate-700 dark:text-slate-300">
                    ${escapeHtml(stage.leg.dep_time)} &rarr; ${escapeHtml(stage.leg.arr_time)}
                  </div>
                </div>
              </div>

              ${stuartLegBanner}
            </div>
          </div>
        </div>
      `;
    });

    // Final Terminal Node
    let stuartArrivedBeacon = '';
    if (finalNode && finalNode.is_stuart_here) {
      stuartArrivedBeacon = `
        <span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold bg-emerald-600 text-white shadow-xs">
          <span class="material-symbols-outlined text-[14px]">check_circle</span>
          <span>Stuart has arrived</span>
        </span>
      `;
    }

    html += `
      <div class="relative flex items-start gap-4 sm:gap-6">
        <div class="flex flex-col items-center shrink-0 w-8 sm:w-10">
          <div class="w-6 h-6 sm:w-7 sm:h-7 rounded-full border-4 border-rose-500 bg-white dark:bg-slate-900 flex items-center justify-center z-10 shadow-xs">
            <span class="w-2 h-2 rounded-full bg-rose-500"></span>
          </div>
        </div>

        <div class="flex-1 min-w-0 pt-0.5">
          <div class="flex items-center justify-between gap-2 flex-wrap">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="text-sm sm:text-base font-bold text-slate-900 dark:text-white">
                ${escapeHtml(finalNode ? finalNode.name : '')}
              </span>
              <span class="px-2 py-0.5 rounded-md text-[11px] font-semibold bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300">
                Final Destination
              </span>
              ${stuartArrivedBeacon}
            </div>
            <span class="text-xs font-mono font-bold text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded-md">
              ${escapeHtml(finalNode ? finalNode.time : '')}
            </span>
          </div>
        </div>
      </div>
    `;

    schematicContainer.innerHTML = html;
  }

  function updateDomTelemetry(data) {
    if (!data) return;
    const j = data.selected_journey;
    const person = data.person;

    // 1. Badge indicator
    if (liveIndicatorBadge && badgeStatusText) {
      if (j && j.is_active) {
        liveIndicatorBadge.innerHTML = `
          <span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300 dark:ring-1 dark:ring-emerald-500/30">
            <span class="relative flex h-2 w-2">
              <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
            <span id="badge-status-text">Active Journey</span>
          </span>
        `;
      } else {
        liveIndicatorBadge.innerHTML = `
          <span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300">
            <span class="h-2 w-2 rounded-full bg-slate-400"></span>
            <span id="badge-status-text">Scheduled</span>
          </span>
        `;
      }
    }

    if (!j) return;

    // 2. Hero titles
    if (journeyOverviewSub) journeyOverviewSub.textContent = j.name || 'Journey';
    if (journeyTerminals)
      journeyTerminals.innerHTML = `${escapeHtml(j.from_name)} &rarr; ${escapeHtml(j.to_name)}`;

    if (heroStageLabel && j.status) heroStageLabel.textContent = j.status.label || 'Overview';
    if (heroStageIcon && j.status && j.status.icon) heroStageIcon.textContent = j.status.icon;

    if (heroDepTime) heroDepTime.textContent = j.departure_time || '--:--';
    if (heroArrTime) heroArrTime.textContent = j.arrival_time || '--:--';

    if (heroNextStepText && j.status)
      heroNextStepText.textContent = j.status.next_step || 'Follow scheduled route.';
    if (heroMessageText && j.status) heroMessageText.textContent = j.status.message || '';

    // 3. Telemetry chips
    if (telemetryPersonState && person) {
      telemetryPersonState.textContent =
        (person.state ? person.state.charAt(0).toUpperCase() + person.state.slice(1) : 'Unknown');
    }
    if (telemetryPersonCoords && person) {
      if (person.latitude != null && person.longitude != null) {
        telemetryPersonCoords.textContent = `${person.latitude.toFixed(4)}, ${person.longitude.toFixed(4)}`;
      } else {
        telemetryPersonCoords.textContent = 'GPS awaiting signal';
      }
    }

    if (telemetryDistNext && person) {
      if (person.distance_to_next_stop_m != null) {
        if (person.distance_to_next_stop_m >= 1000) {
          telemetryDistNext.textContent = `${(person.distance_to_next_stop_m / 1000.0).toFixed(1)} km`;
        } else {
          telemetryDistNext.textContent = `${Math.round(person.distance_to_next_stop_m)} metres`;
        }
      } else {
        telemetryDistNext.textContent = 'Calculating...';
      }
    }

    if (telemetryDistDest && person) {
      if (person.distance_to_destination_m != null) {
        telemetryDistDest.textContent = `Dest: ${(person.distance_to_destination_m / 1000.0).toFixed(1)} km`;
      } else {
        telemetryDistDest.textContent = 'Dest distance N/A';
      }
    }

    if (telemetryPlatform) {
      if (j.platform) {
        telemetryPlatform.innerHTML = `
          <span>Platform ${escapeHtml(j.platform)}</span>
          <span class="inline-flex px-1.5 py-0.2 rounded text-[10px] font-bold bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300">Live</span>
        `;
      } else {
        telemetryPlatform.innerHTML = `<span class="text-slate-500 dark:text-slate-400">Unannounced</span>`;
      }
    }

    if (telemetryLiveStatus) {
      telemetryLiveStatus.textContent = j.live_status || 'On schedule';
    }

    if (telemetryLastUpdated && person) {
      telemetryLastUpdated.textContent = `Updated: ${person.updated_at || 'Just now'}`;
    }

    // 4. Update the abstract vertical schematic diagram
    renderSchematicDiagram(data);
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  async function fetchLiveTelemetry(manualTrigger = false) {
    if (manualTrigger && refreshIcon) {
      refreshIcon.classList.add('animate-spin');
    }

    const selectedId = journeySelect ? journeySelect.value : '';
    const queryParam = selectedId ? `?journey_id=${encodeURIComponent(selectedId)}` : '';
    const url = `${ingressPath}/api/journey/live${queryParam}`;

    try {
      const response = await fetch(url, {
        headers: {
          Accept: 'application/json',
          'Cache-Control': 'no-cache',
        },
      });

      if (!response.ok) {
        throw new Error(`HTTP error ${response.status}`);
      }

      const freshData = await response.json();
      trackingData = freshData;

      updateDomTelemetry(freshData);
      renderJourneyMap(freshData);
    } catch (err) {
      console.warn('Live journey telemetry polling skipped:', err);
    } finally {
      if (manualTrigger && refreshIcon) {
        setTimeout(() => refreshIcon.classList.remove('animate-spin'), 600);
      }
    }
  }

  // View Switcher Event Handlers
  if (btnViewSchematic && btnViewMap) {
    btnViewSchematic.addEventListener('click', () => {
      schematicViewWrapper.classList.remove('hidden');
      schematicViewWrapper.classList.add('block');
      geographicMapWrapper.classList.add('hidden');

      btnViewSchematic.className =
        'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-xs transition-all cursor-pointer';
      btnViewSchematic.setAttribute('aria-selected', 'true');

      btnViewMap.className =
        'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition-all cursor-pointer';
      btnViewMap.setAttribute('aria-selected', 'false');
    });

    btnViewMap.addEventListener('click', () => {
      schematicViewWrapper.classList.add('hidden');
      schematicViewWrapper.classList.remove('block');
      geographicMapWrapper.classList.remove('hidden');

      btnViewMap.className =
        'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-xs transition-all cursor-pointer';
      btnViewMap.setAttribute('aria-selected', 'true');

      btnViewSchematic.className =
        'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition-all cursor-pointer';
      btnViewSchematic.setAttribute('aria-selected', 'false');

      if (map) {
        setTimeout(() => {
          map.invalidateSize();
          if (trackingData) {
            renderJourneyMap(trackingData);
          }
        }, 100);
      }
    });
  }

  // Journey Selection Handler
  if (journeySelect) {
    journeySelect.addEventListener('change', () => {
      const newId = journeySelect.value;
      if (history.pushState) {
        const newUrl = `${window.location.protocol}//${window.location.host}${window.location.pathname}?journey_id=${encodeURIComponent(newId)}`;
        window.history.pushState({ path: newUrl }, '', newUrl);
      }
      fetchLiveTelemetry(true);
    });
  }

  if (btnRefresh) {
    btnRefresh.addEventListener('click', () => {
      fetchLiveTelemetry(true);
    });
  }

  // Initialise
  initMap();

  // Auto-polling interval: 10 seconds
  const POLLING_INTERVAL_MS = 10000;
  const timer = setInterval(() => {
    fetchLiveTelemetry(false);
  }, POLLING_INTERVAL_MS);

  window.addEventListener('beforeunload', () => {
    clearInterval(timer);
  });
});
