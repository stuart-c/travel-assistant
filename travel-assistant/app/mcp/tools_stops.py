"""MCP tools for searching transit stops and querying live departure boards."""

import logging
from typing import Any, Dict, List, Optional

from app.models.transit import Stop
from app.mcp.registry import register_tool

logger = logging.getLogger(__name__)


@register_tool(
    name="stops_search",
    domain="stops",
    description="Search for UK rail stations or bus stops by name, CRS code, or NaPTAN/ATCO code.",
    is_mutating=False,
)
def stops_search(
    query: str,
    stop_type: Optional[str] = None,
    limit: int = 15,
) -> List[Dict[str, Any]]:
    """Search for stops matching query string with optional type filtering."""
    q_str = f"%{query.strip()}%"
    stmt = Stop.select().where(
        (Stop.name**q_str) | (Stop.atco_code**q_str) | (Stop.naptan_code**q_str)
    )
    if stop_type:
        stmt = stmt.where(Stop.stop_type == stop_type.strip().lower())

    results = []
    for s in stmt.limit(max(1, min(100, int(limit)))):
        results.append(
            {
                "id": s.id,
                "name": s.name,
                "stop_type": s.stop_type,
                "atco_code": s.atco_code,
                "naptan_code": s.naptan_code,
                "indicator": s.indicator,
                "locality": s.locality,
                "latitude": s.latitude,
                "longitude": s.longitude,
            }
        )
    return results


@register_tool(
    name="stops_get_live_departures",
    domain="stops",
    description="Query live train departure boards from National Rail Darwin LDBWS by 3-letter CRS code.",
    is_mutating=False,
)
def stops_get_live_departures(
    station_crs: str,
    num_rows: int = 10,
) -> Dict[str, Any]:
    """Query live departure board for a rail station."""
    crs = station_crs.strip().upper()
    try:
        from app.datasources.train_live import TrainLiveClient

        source = TrainLiveClient.from_settings()
        board = source.get_departure_board(crs, num_rows=num_rows)
        return {"crs": crs, "board": board}
    except Exception as err:
        logger.warning("Could not fetch live departures for %s: %s", crs, err)
        return {
            "crs": crs,
            "error": f"Failed to retrieve live departures: {str(err)}",
        }
