"""Contiguous transit leg compression and RouteTemplate assembly."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx

from app.services.planner.models import RouteLeg, RouteTemplate
from app.services.planner.route_finder.helpers import is_valid_leg_sequence

logger = logging.getLogger(__name__)


def assemble_route_templates(
    G: nx.MultiDiGraph,
    paths: List[List[Tuple[str, str, Any]]],
    active_days: List[str],
    max_stages: int = 10,
) -> List[RouteTemplate]:
    """Compress contiguous transit edges and construct RouteTemplate candidates.

    Args:
        G: Complete multi-modal transit graph.
        paths: Candidate edge sequences.
        active_days: Active operational days list.
        max_stages: Maximum modal stages permitted.

    Returns:
        List of unpruned RouteTemplate instances.
    """
    candidate_templates: List[RouteTemplate] = []
    corridor_idx = 1

    for edge_seq in paths:
        compressed_legs: List[RouteLeg] = []
        stage_idx = 1
        step_idx = 1
        total_duration = 0
        current_transit_leg: Optional[Dict[str, Any]] = None

        for u, v, k in edge_seq:
            edge_attr = G.edges[u, v, k]
            leg_type = edge_attr.get("leg_type", "walk")
            dur = edge_attr.get("duration", 1)
            total_duration += dur

            if leg_type == "transit":
                tt_id = edge_attr.get("timetable_id")
                line_name = edge_attr.get("line_name")
                op_name = edge_attr.get("operator_name")
                mode = edge_attr.get("transport_mode", "bus")

                is_same_service = (
                    current_transit_leg is not None
                    and current_transit_leg.get("transport_mode") == mode
                    and current_transit_leg.get("timetable_id") == tt_id
                    and (
                        line_name is None
                        or current_transit_leg.get("line_name") == line_name
                    )
                )

                if is_same_service:
                    current_transit_leg["to_type"] = G.nodes[v].get("node_type", "bus")
                    current_transit_leg["to_id"] = G.nodes[v].get("id", "")
                    current_transit_leg["to_name"] = edge_attr.get("to_name", "")
                    current_transit_leg["duration_minutes"] += dur
                    current_transit_leg["stops_count"] += 1
                else:
                    if current_transit_leg is not None:
                        compressed_legs.append(RouteLeg(**current_transit_leg))
                        stage_idx += 1
                        step_idx += 1

                    current_transit_leg = {
                        "stage_index": stage_idx,
                        "step_index": step_idx,
                        "leg_type": "transit",
                        "from_type": G.nodes[u].get("node_type", "bus"),
                        "from_id": G.nodes[u].get("id", ""),
                        "from_name": edge_attr.get("from_name", ""),
                        "to_type": G.nodes[v].get("node_type", "bus"),
                        "to_id": G.nodes[v].get("id", ""),
                        "to_name": edge_attr.get("to_name", ""),
                        "duration_minutes": dur,
                        "distance_m": None,
                        "transport_mode": mode,
                        "line_name": line_name,
                        "operator_name": op_name,
                        "stops_count": 1,
                        "timetable_id": tt_id,
                    }
            else:
                if current_transit_leg is not None:
                    compressed_legs.append(RouteLeg(**current_transit_leg))
                    current_transit_leg = None
                    stage_idx += 1
                    step_idx += 1

                compressed_legs.append(
                    RouteLeg(
                        stage_index=stage_idx,
                        step_index=step_idx,
                        leg_type=leg_type,
                        from_type=G.nodes[u].get("node_type", "walk"),
                        from_id=G.nodes[u].get("id", ""),
                        from_name=edge_attr.get("from_name", ""),
                        to_type=G.nodes[v].get("node_type", "walk"),
                        to_id=G.nodes[v].get("id", ""),
                        to_name=edge_attr.get("to_name", ""),
                        duration_minutes=dur,
                        distance_m=edge_attr.get("distance_m"),
                        transport_mode=edge_attr.get("transport_mode", "walk"),
                        line_name=edge_attr.get("line_name"),
                        operator_name=edge_attr.get("operator_name"),
                        stops_count=edge_attr.get("stops_count", 1),
                        timetable_id=edge_attr.get("timetable_id"),
                    )
                )
                stage_idx += 1
                step_idx += 1

        if current_transit_leg is not None:
            compressed_legs.append(RouteLeg(**current_transit_leg))

        if stage_idx > max_stages + 2:
            logger.debug(
                "Rejected candidate path due to stage_idx %d > %d",
                stage_idx,
                max_stages + 2,
            )
            continue

        if not is_valid_leg_sequence(compressed_legs):
            logger.debug(
                "Rejected candidate path due to is_valid_leg_sequence: %s",
                [(leg.leg_type, leg.transport_mode) for leg in compressed_legs],
            )
            continue

        transit_legs_count = sum(
            1 for leg in compressed_legs if leg.leg_type == "transit"
        )
        transfers_count = max(0, transit_legs_count - 1)

        transit_modes = [
            leg.transport_mode
            for leg in compressed_legs
            if leg.leg_type == "transit" and leg.transport_mode
        ]
        primary_mode = transit_modes[0] if transit_modes else "walk"

        summary_parts = []
        for leg in compressed_legs:
            if leg.leg_type == "transit":
                summary_parts.append(
                    f"{leg.transport_mode.capitalize()} {leg.line_name or ''}".strip()
                )
            elif leg.leg_type == "walk":
                summary_parts.append(f"Walk ({leg.duration_minutes}m)")
            elif leg.leg_type in ("interchange", "platform_transfer"):
                summary_parts.append(f"Transfer ({leg.duration_minutes}m)")

        summary_text = " → ".join(summary_parts)
        name = f"Via {summary_parts[1]}" if len(summary_parts) > 1 else "Direct Walk"

        candidate_templates.append(
            RouteTemplate(
                corridor_id=f"corridor_{corridor_idx}",
                name=name,
                summary_text=summary_text,
                primary_mode=primary_mode,
                total_duration_est_minutes=total_duration,
                transfer_count=transfers_count,
                stages_count=len(compressed_legs),
                active_days=active_days,
                legs=compressed_legs,
            )
        )
        corridor_idx += 1

    return candidate_templates
