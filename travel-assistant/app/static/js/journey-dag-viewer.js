/**
 * Journey DAG Corridor Viewer Component.
 * Manages vis-network interactive topological DAG diagram rendering for journey routes,
 * node hierarchy levels, mode styling, edge tooltips, and dark mode adaptation.
 */
(function () {
  'use strict';

  let currentNetwork = null;
  let activeJourneyItem = null;
  let activeRoutesData = null;
  let dagContainer = null;
  let routesSummaryText = null;
  let routesEmptyState = null;
  let routesFitBtn = null;

  const escapeHtml =
    (window.TransitUI && window.TransitUI.escapeHtml) ||
    ((str) => (str ? String(str) : ''));

  const MODE_CONFIG = {
    walk: {
      colour: '#64748b',
      label: 'Walk',
      dashes: [4, 4],
      icon: 'directions_walk',
    },
    bus: {
      colour: '#d97706',
      label: 'Bus',
      dashes: false,
      icon: 'directions_bus',
    },
    rail: {
      colour: '#4f46e5',
      label: 'Train',
      dashes: false,
      icon: 'train',
    },
    train: {
      colour: '#4f46e5',
      label: 'Train',
      dashes: false,
      icon: 'train',
    },
    metro: {
      colour: '#059669',
      label: 'Metro',
      dashes: false,
      icon: 'subway',
    },
    tram: {
      colour: '#ea580c',
      label: 'Tram',
      dashes: false,
      icon: 'tram',
    },
    ferry: {
      colour: '#0891b2',
      label: 'Ferry',
      dashes: false,
      icon: 'directions_boat',
    },
    air: {
      colour: '#9333ea',
      label: 'Flight',
      dashes: false,
      icon: 'flight',
    },
    interchange: {
      colour: '#64748b',
      label: 'Interchange',
      dashes: [2, 2],
      icon: 'swap_horiz',
    },
    platform_transfer: {
      colour: '#64748b',
      label: 'Transfer',
      dashes: [2, 2],
      icon: 'transfer_within_a_station',
    },
    custom: {
      colour: '#0284c7',
      label: 'Transit',
      dashes: false,
      icon: 'pin_drop',
    },
  };

  function getModeConfig(mode, legType) {
    const key = String(mode || legType || 'custom').toLowerCase();
    return MODE_CONFIG[key] || MODE_CONFIG.custom;
  }

  function isDarkMode() {
    return (
      document.documentElement.classList.contains('dark') ||
      (window.matchMedia &&
        window.matchMedia('(prefers-color-scheme: dark)').matches)
    );
  }

  function getStopNodeId(id, name) {
    const normId = (id || '')
      .replace(/^(atco|naptan|crs|tiploc|ha|custom):/i, '')
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '');
    if (normId) return `stop_${normId}`;

    const normName = (name || '')
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '');
    if (normName) return `stop_${normName}`;

    return 'stop_unknown';
  }

  function getStopIcon(type, name) {
    const t = String(type || '').toLowerCase();
    const n = String(name || '').toLowerCase();
    if (t === 'bus' || n.includes('bus')) return '🚌';
    if (
      t === 'rail' ||
      t === 'train' ||
      n.includes('rail') ||
      n.includes('train')
    )
      return '🚆';
    if (
      t === 'metro' ||
      t === 'subway' ||
      n.includes('underground') ||
      n.includes('tube') ||
      n.includes('metro')
    )
      return '🚇';
    if (t === 'tram' || n.includes('tram')) return '🚋';
    if (t === 'ferry' || n.includes('ferry') || n.includes('pier')) return '⛴️';
    if (t === 'air' || t === 'flight' || n.includes('airport')) return '✈️';
    if (n.includes('station')) return '🚆';
    return '🚏';
  }

  function createEdgeTooltip(leg, linesSet, operatorsSet, minDuration) {
    const modeCfg = getModeConfig(leg.transport_mode, leg.leg_type);
    const modeName = leg.transport_mode
      ? leg.transport_mode.charAt(0).toUpperCase() + leg.transport_mode.slice(1)
      : leg.leg_type === 'walk'
      ? 'Walking'
      : 'Transit';

    const linesList =
      linesSet && linesSet.size > 0
        ? Array.from(linesSet).filter(Boolean)
        : leg.line_name
        ? [leg.line_name]
        : [];
    const lineHeading =
      linesList.length > 0 ? `${modeName} ${linesList.join(', ')}` : modeName;

    const parts = [
      `<div style="font-weight: 700; margin-bottom: 4px; color: ${
        modeCfg.colour
      }; font-size: 13px;">${escapeHtml(lineHeading)}</div>`,
    ];

    const opsList =
      operatorsSet && operatorsSet.size > 0
        ? Array.from(operatorsSet).filter(Boolean)
        : leg.operator_name
        ? [leg.operator_name]
        : [];
    if (opsList.length > 0) {
      parts.push(
        `<div style="margin-bottom: 2px;"><strong>Operator${
          opsList.length > 1 ? 's' : ''
        }:</strong> ${escapeHtml(opsList.join(', '))}</div>`
      );
    }

    const dur =
      minDuration !== undefined && minDuration !== null
        ? minDuration
        : leg.duration_minutes;
    if (dur !== undefined && dur !== null) {
      parts.push(
        `<div style="margin-bottom: 2px;"><strong>Duration:</strong> ~${dur} min${
          dur === 1 ? '' : 's'
        }</div>`
      );
    }
    if (leg.distance_m) {
      const distKm = (leg.distance_m / 1000).toFixed(1);
      const distStr =
        leg.distance_m >= 1000 ? `${distKm} km` : `${leg.distance_m} m`;
      parts.push(
        `<div style="margin-bottom: 2px;"><strong>Distance:</strong> ${distStr}</div>`
      );
    }
    if (leg.stops_count) {
      parts.push(
        `<div style="margin-bottom: 2px;"><strong>Stops:</strong> ${leg.stops_count} intermediate</div>`
      );
    }
    parts.push(
      `<div style="margin-top: 6px; padding-top: 4px; border-top: 1px dashed rgba(148, 163, 184, 0.4); font-size: 11px; opacity: 0.85;">${escapeHtml(
        leg.from_name || 'Start'
      )} &rarr; ${escapeHtml(leg.to_name || 'End')}</div>`
    );

    const tooltipEl = document.createElement('div');
    tooltipEl.innerHTML = parts.join('');
    return tooltipEl;
  }

  function init(options) {
    dagContainer =
      options?.container ||
      document.getElementById('journey-routes-dag-container');
    routesSummaryText =
      options?.summaryText ||
      document.getElementById('journey-routes-summary-text');
    routesEmptyState =
      options?.emptyState ||
      document.getElementById('journey-routes-empty-state');
    routesFitBtn =
      options?.fitBtn || document.getElementById('journey-routes-fit-btn');

    if (routesFitBtn) {
      routesFitBtn.addEventListener('click', () => {
        fit({
          animation: {
            duration: 350,
            easingFunction: 'easeInOutQuad',
          },
        });
      });
    }

    const themeObserver = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        if (
          mutation.attributeName === 'class' &&
          activeRoutesData &&
          activeJourneyItem
        ) {
          render(activeRoutesData, activeJourneyItem);
        }
      });
    });
    themeObserver.observe(document.documentElement, { attributes: true });
  }

  function render(routesData, item) {
    destroy();
    if (!dagContainer) return;

    activeJourneyItem = item;
    activeRoutesData = routesData;

    let routes = [];
    if (typeof routesData === 'string') {
      try {
        routes = JSON.parse(routesData);
      } catch (e) {
        routes = [];
      }
    } else if (Array.isArray(routesData)) {
      routes = routesData;
    } else if (routesData && typeof routesData === 'object') {
      routes = [routesData];
    }

    if (!routes || routes.length === 0) {
      if (routesEmptyState) routesEmptyState.classList.remove('hidden');
      if (routesSummaryText) {
        routesSummaryText.textContent =
          'No calculated routes available for this journey.';
      }
      return;
    }

    if (routesEmptyState) routesEmptyState.classList.add('hidden');
    if (routesSummaryText) {
      const count = routes.length;
      routesSummaryText.textContent = `${count} topological route corridor${
        count === 1 ? '' : 's'
      } discovered connecting origin to destination.`;
    }

    const dark = isDarkMode();
    const originName = (item && item.from_name) || 'Origin';
    const destName = (item && item.to_name) || 'Destination';
    const originId = (item && item.from_id) || '';
    const destId = (item && item.to_id) || '';

    const normOriginId = (originId || '')
      .replace(/^(ha|custom|naptan|atco|crs|tiploc):/i, '')
      .trim()
      .toLowerCase();
    const normDestId = (destId || '')
      .replace(/^(ha|custom|naptan|atco|crs|tiploc):/i, '')
      .trim()
      .toLowerCase();
    const normOriginName = (originName || '').trim().toLowerCase();
    const normDestName = (destName || '').trim().toLowerCase();

    function isOriginEndpoint(id, name, isFirstLeg) {
      if (isFirstLeg) return true;
      const nName = (name || '').trim().toLowerCase();
      const nId = (id || '')
        .replace(/^(ha|custom|naptan|atco|crs|tiploc):/i, '')
        .trim()
        .toLowerCase();
      return (
        (normOriginName && nName === normOriginName) ||
        (normOriginId && nId === normOriginId)
      );
    }

    function isDestEndpoint(id, name, isLastLeg) {
      if (isLastLeg) return true;
      const nName = (name || '').trim().toLowerCase();
      const nId = (id || '')
        .replace(/^(ha|custom|naptan|atco|crs|tiploc):/i, '')
        .trim()
        .toLowerCase();
      return (
        (normDestName && nName === normDestName) ||
        (normDestId && nId === normDestId)
      );
    }

    const stopMetadataMap = new Map();
    const rawDirectedEdges = [];

    routes.forEach((route) => {
      if (!route || !Array.isArray(route.legs) || route.legs.length === 0)
        return;
      const legs = route.legs;

      legs.forEach((leg, index) => {
        const isFirstLeg = index === 0;
        const isLastLeg = index === legs.length - 1;

        let fromNodeId;
        if (isOriginEndpoint(leg.from_id, leg.from_name, isFirstLeg)) {
          fromNodeId = 'NODE_ORIGIN';
        } else {
          fromNodeId = getStopNodeId(leg.from_id, leg.from_name);
          if (!stopMetadataMap.has(fromNodeId)) {
            stopMetadataMap.set(fromNodeId, {
              name: leg.from_name || 'Stop',
              type: leg.from_type,
              id: leg.from_id,
            });
          }
        }

        let toNodeId;
        if (isDestEndpoint(leg.to_id, leg.to_name, isLastLeg)) {
          toNodeId = 'NODE_DESTINATION';
        } else {
          toNodeId = getStopNodeId(leg.to_id, leg.to_name);
          if (!stopMetadataMap.has(toNodeId)) {
            stopMetadataMap.set(toNodeId, {
              name: leg.to_name || 'Stop',
              type: leg.to_type,
              id: leg.to_id,
            });
          }
        }

        if (fromNodeId !== toNodeId) {
          rawDirectedEdges.push({
            from: fromNodeId,
            to: toNodeId,
            leg: leg,
          });
        }
      });
    });

    if (rawDirectedEdges.length === 0) {
      if (routesEmptyState) routesEmptyState.classList.remove('hidden');
      return;
    }

    const nodeLevels = new Map();
    nodeLevels.set('NODE_ORIGIN', 0);
    const allNodeIds = Array.from(
      new Set(['NODE_ORIGIN', 'NODE_DESTINATION', ...stopMetadataMap.keys()])
    );
    allNodeIds.forEach((id) => {
      if (id !== 'NODE_ORIGIN') nodeLevels.set(id, 1);
    });

    let changed = true;
    let iterations = 0;
    const maxIterations = Math.max(15, allNodeIds.length * 2);

    while (changed && iterations < maxIterations) {
      changed = false;
      iterations++;
      rawDirectedEdges.forEach(({ from, to }) => {
        if (to === 'NODE_ORIGIN') return;
        const fromLevel = nodeLevels.get(from) ?? 0;
        const toLevel = nodeLevels.get(to) ?? 1;
        if (toLevel < fromLevel + 1) {
          nodeLevels.set(to, fromLevel + 1);
          changed = true;
        }
      });
    }

    const usedLevels = Array.from(
      new Set(
        Array.from(stopMetadataMap.keys())
          .map((id) => nodeLevels.get(id))
          .filter((l) => l !== undefined && l > 0)
      )
    ).sort((a, b) => a - b);

    const levelCompactor = new Map();
    usedLevels.forEach((lvl, idx) => {
      levelCompactor.set(lvl, idx + 1);
    });

    stopMetadataMap.forEach((_, nodeId) => {
      const oldLvl = nodeLevels.get(nodeId);
      if (oldLvl !== undefined && levelCompactor.has(oldLvl)) {
        nodeLevels.set(nodeId, levelCompactor.get(oldLvl));
      }
    });

    const maxIntermediateLevel = usedLevels.length;
    const destLevel = maxIntermediateLevel + 1;
    nodeLevels.set('NODE_DESTINATION', destLevel);

    const nodesMap = new Map();
    nodesMap.set('NODE_ORIGIN', {
      id: 'NODE_ORIGIN',
      level: 0,
      label: `🚩 ${originName}\n(Start)`,
      title: `Origin: ${originName}${originId ? ` (${originId})` : ''}`,
      shape: 'box',
      margin: { top: 10, bottom: 10, left: 14, right: 14 },
      shapeProperties: { borderRadius: 10 },
      color: {
        background: dark ? '#064e3b' : '#ecfdf5',
        border: dark ? '#34d399' : '#10b981',
        highlight: {
          background: dark ? '#065f46' : '#d1fae5',
          border: '#10b981',
        },
        hover: {
          background: dark ? '#065f46' : '#d1fae5',
          border: '#10b981',
        },
      },
      font: {
        color: dark ? '#ecfdf5' : '#065f46',
        bold: { color: dark ? '#ffffff' : '#064e3b' },
        size: 13,
        face: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      },
      borderWidth: 2,
      shadow: {
        enabled: true,
        color: dark ? 'rgba(0,0,0,0.5)' : 'rgba(16,185,129,0.15)',
        size: 6,
        x: 0,
        y: 2,
      },
    });

    stopMetadataMap.forEach((meta, nodeId) => {
      const stopLevel = nodeLevels.get(nodeId) || 1;
      const icon = getStopIcon(meta.type, meta.name);
      nodesMap.set(nodeId, {
        id: nodeId,
        level: stopLevel,
        label: `${icon} ${meta.name}`,
        title: `Stop: ${meta.name}${meta.type ? ` (${meta.type})` : ''}${
          meta.id ? ` [${meta.id}]` : ''
        }`,
        shape: 'box',
        margin: { top: 8, bottom: 8, left: 12, right: 12 },
        shapeProperties: { borderRadius: 8 },
        color: {
          background: dark ? '#1e293b' : '#f8fafc',
          border: dark ? '#475569' : '#cbd5e1',
          highlight: {
            background: dark ? '#334155' : '#e2e8f0',
            border: dark ? '#94a3b8' : '#64748b',
          },
          hover: {
            background: dark ? '#334155' : '#e2e8f0',
            border: dark ? '#94a3b8' : '#64748b',
          },
        },
        font: {
          color: dark ? '#f1f5f9' : '#1e293b',
          size: 12,
          face: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        },
        borderWidth: 1.5,
        shadow: {
          enabled: true,
          color: dark ? 'rgba(0,0,0,0.4)' : 'rgba(0,0,0,0.06)',
          size: 4,
          x: 0,
          y: 1,
        },
      });
    });

    nodesMap.set('NODE_DESTINATION', {
      id: 'NODE_DESTINATION',
      level: destLevel,
      label: `🏁 ${destName}\n(End)`,
      title: `Destination: ${destName}${destId ? ` (${destId})` : ''}`,
      shape: 'box',
      margin: { top: 10, bottom: 10, left: 14, right: 14 },
      shapeProperties: { borderRadius: 10 },
      color: {
        background: dark ? '#4c0519' : '#fff1f2',
        border: dark ? '#fb7185' : '#f43f5e',
        highlight: {
          background: dark ? '#881337' : '#ffe4e6',
          border: '#f43f5e',
        },
        hover: {
          background: dark ? '#881337' : '#ffe4e6',
          border: '#f43f5e',
        },
      },
      font: {
        color: dark ? '#ffe4e6' : '#881337',
        bold: { color: dark ? '#ffffff' : '#4c0519' },
        size: 13,
        face: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      },
      borderWidth: 2,
      shadow: {
        enabled: true,
        color: dark ? 'rgba(0,0,0,0.5)' : 'rgba(244,63,94,0.15)',
        size: 6,
        x: 0,
        y: 2,
      },
    });

    const edgesMap = new Map();
    rawDirectedEdges.forEach(({ from, to, leg }) => {
      const fromLevel = nodeLevels.get(from) ?? 0;
      const toLevel = nodeLevels.get(to) ?? destLevel;
      if (toLevel <= fromLevel) return;

      const edgeKey = `${from}->${to}`;
      if (edgesMap.has(edgeKey)) {
        const existing = edgesMap.get(edgeKey);
        if (leg.line_name) existing.lines.add(leg.line_name);
        if (leg.operator_name) existing.operators.add(leg.operator_name);
        if (
          leg.duration_minutes &&
          (!existing.minDuration || leg.duration_minutes < existing.minDuration)
        ) {
          existing.minDuration = leg.duration_minutes;
        }
        if (existing.leg.leg_type === 'walk' && leg.leg_type !== 'walk') {
          existing.leg = leg;
          existing.modeCfg = getModeConfig(leg.transport_mode, leg.leg_type);
        }
      } else {
        const modeCfg = getModeConfig(leg.transport_mode, leg.leg_type);
        const lines = new Set();
        if (leg.line_name) lines.add(leg.line_name);
        const operators = new Set();
        if (leg.operator_name) operators.add(leg.operator_name);

        edgesMap.set(edgeKey, {
          id: `edge_${from}_${to}`,
          from: from,
          to: to,
          fromLevel: fromLevel,
          toLevel: toLevel,
          leg: leg,
          lines: lines,
          operators: operators,
          minDuration: leg.duration_minutes || null,
          modeCfg: modeCfg,
        });
      }
    });

    const edgesList = Array.from(edgesMap.values()).map((e) => {
      const levelDiff = e.toLevel - e.fromLevel;
      const roundness = levelDiff > 1 ? 0.45 : 0.3;

      return {
        id: e.id,
        from: e.from,
        to: e.to,
        arrows: {
          to: {
            enabled: true,
            scaleFactor: 0.85,
          },
        },
        width: 2.5,
        color: {
          color: e.modeCfg.colour,
          highlight: e.modeCfg.colour,
          hover: e.modeCfg.colour,
          opacity: 0.9,
        },
        dashes: e.modeCfg.dashes,
        title: createEdgeTooltip(e.leg, e.lines, e.operators, e.minDuration),
        smooth: {
          type: 'cubicBezier',
          forceDirection: 'vertical',
          roundness: roundness,
        },
      };
    });

    if (typeof vis === 'undefined' || !vis.Network) {
      console.warn('vis-network library not loaded.');
      return;
    }

    const networkData = {
      nodes: new vis.DataSet(Array.from(nodesMap.values())),
      edges: new vis.DataSet(edgesList),
    };

    const networkOptions = {
      layout: {
        hierarchical: {
          enabled: true,
          direction: 'UD',
          sortMethod: 'directed',
          levelSeparation: 110,
          nodeSpacing: 220,
          treeSpacing: 260,
          blockShifting: true,
          edgeMinimization: true,
          parentCentralization: true,
          shakeTowards: 'roots',
        },
      },
      physics: {
        enabled: false,
      },
      interaction: {
        hover: true,
        hoverConnectedEdges: true,
        selectConnectedEdges: true,
        tooltipDelay: 80,
        zoomView: true,
        dragView: true,
        dragNodes: true,
      },
    };

    currentNetwork = new vis.Network(dagContainer, networkData, networkOptions);
    currentNetwork.once('afterDrawing', () => {
      if (currentNetwork) currentNetwork.fit();
    });
  }

  function fit(options) {
    if (currentNetwork) {
      currentNetwork.fit(options);
    }
  }

  function destroy() {
    if (currentNetwork) {
      currentNetwork.destroy();
      currentNetwork = null;
    }
    activeJourneyItem = null;
    activeRoutesData = null;
  }

  window.JourneyDagViewer = {
    init,
    render,
    fit,
    destroy,
  };
})();
