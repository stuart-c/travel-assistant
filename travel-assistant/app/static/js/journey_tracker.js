/**
 * Journey Live Tracking Controller.
 * 
 * Manages real-time telemetry polling, Stuart's live GPS beacon,
 * interactive Leaflet corridor mapping, and journey stage progression.
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
  const journeyLegsContainer = document.getElementById('journey-legs-container');

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

    // 4. Stepper Legs
    if (journeyLegsContainer && j.legs) {
      renderLegsContainer(j.legs, j.is_active);
    }
  }

  function renderLegsContainer(legs, isActive) {
    if (!journeyLegsContainer) return;
    if (!legs || legs.length === 0) {
      journeyLegsContainer.innerHTML = `
        <div class="p-6 text-center text-sm text-slate-500 dark:text-slate-400 rounded-xl bg-slate-50 dark:bg-slate-800/40">
          No active itinerary stages discovered for the selected journey.
        </div>
      `;
      return;
    }

    const html = legs
      .map((leg) => {
        const isCurrent = leg.is_current && isActive;
        const isCompleted = leg.is_completed;

        let cardClass =
          'border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-800/40';
        if (isCurrent) {
          cardClass =
            'border-sky-500 bg-sky-50/40 dark:border-sky-500/80 dark:bg-sky-950/30 ring-2 ring-sky-500/20';
        } else if (isCompleted) {
          cardClass =
            'border-slate-200/60 bg-slate-50/60 dark:border-slate-800 dark:bg-slate-900/40 opacity-75';
        }

        let modeIcon = 'directions_transit';
        let modeBg = 'bg-sky-100 text-sky-800 dark:bg-sky-950/80 dark:text-sky-300';
        if (leg.mode === 'walk') {
          modeIcon = 'directions_walk';
          modeBg = 'bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-300';
        } else if (leg.mode === 'rail') {
          modeIcon = 'train';
          modeBg = 'bg-indigo-100 text-indigo-800 dark:bg-indigo-950/80 dark:text-indigo-300';
        } else if (leg.mode === 'bus') {
          modeIcon = 'directions_bus';
          modeBg = 'bg-sky-100 text-sky-800 dark:bg-sky-950/80 dark:text-sky-300';
        }

        const modeTitle =
          leg.mode === 'walk'
            ? `Walk (${leg.duration_minutes}m)`
            : `${leg.line || leg.mode.toUpperCase()}${leg.operator ? ` <span class="font-normal text-xs text-slate-500">(${escapeHtml(leg.operator)})</span>` : ''}`;

        let statusBadge = '';
        if (isCurrent) {
          statusBadge = `
            <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold bg-sky-600 text-white shadow-xs">
              <span class="material-symbols-outlined text-[13px]">person</span>
              <span>Stuart is here</span>
            </span>
          `;
        } else if (isCompleted) {
          statusBadge = `
            <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
              <span class="material-symbols-outlined text-[13px]">check</span>
              <span>Completed</span>
            </span>
          `;
        }

        const platformHtml = leg.origin.platform
          ? `
          <div class="px-2.5 py-1 rounded-lg bg-indigo-50 border border-indigo-200/80 dark:bg-indigo-950/60 dark:border-indigo-800/80 text-xs font-semibold text-indigo-700 dark:text-indigo-300">
            Plat ${escapeHtml(leg.origin.platform)}
          </div>
        `
          : '';

        return `
          <div class="p-4 rounded-xl border transition-all duration-200 ${cardClass}" id="leg-card-${leg.leg_index}">
            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div class="flex items-start sm:items-center gap-3">
                <div class="w-10 h-10 rounded-xl flex items-center justify-center shrink-0 ${modeBg}">
                  <span class="material-symbols-outlined text-xl">${modeIcon}</span>
                </div>
                <div>
                  <div class="flex items-center gap-2 flex-wrap">
                    <span class="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                      Stage ${leg.leg_index + 1}
                    </span>
                    <span class="text-sm font-bold text-slate-900 dark:text-white">
                      ${modeTitle}
                    </span>
                    ${statusBadge}
                  </div>
                  <div class="text-xs text-slate-600 dark:text-slate-300 mt-1 flex items-center gap-1.5 flex-wrap">
                    <span class="font-medium text-slate-800 dark:text-slate-200">${escapeHtml(leg.origin.name)}</span>
                    <span>&rarr;</span>
                    <span class="font-medium text-slate-800 dark:text-slate-200">${escapeHtml(leg.destination.name)}</span>
                  </div>
                </div>
              </div>
              <div class="flex items-center gap-3 self-end sm:self-auto shrink-0">
                ${platformHtml}
                <div class="text-right">
                  <div class="text-sm font-mono font-bold text-slate-900 dark:text-white">
                    ${escapeHtml(leg.dep_time)} &rarr; ${escapeHtml(leg.arr_time)}
                  </div>
                  <div class="text-[11px] text-slate-500 dark:text-slate-400">
                    ${leg.duration_minutes} mins
                  </div>
                </div>
              </div>
            </div>
          </div>
        `;
      })
      .join('');

    journeyLegsContainer.innerHTML = html;
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

  // Event Listeners
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
