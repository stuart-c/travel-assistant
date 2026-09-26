"""Transfer validation and loop prevention rules for the RAPTOR engine."""

from __future__ import annotations

from typing import Any, Dict

from app.services.planner.raptor.models import _ParsedTrip
from app.services.planner.transfers import extract_route_base_name, normalise_id


def _is_invalid_transfer(
    tr: _ParsedTrip,
    boarding_stop_norm: str,
    round_idx: int,
    leg_pointer: Dict[int, Dict[str, Any]],
) -> bool:
    """Check if transferring to trip tr from boarding_stop_norm represents an invalid turnaround or same-line loop."""
    if round_idx <= 1:
        return False

    curr_stop = boarding_stop_norm
    r = round_idx - 1
    while r >= 0 and curr_stop:
        p = leg_pointer[r].get(curr_stop)
        if not p:
            r -= 1
            continue
        p_mode = p.get("mode")
        if p_mode in ("bus", "rail", "metro", "tram", "ferry"):
            # Check same base route name (e.g. Bus 37X -> Bus 37X or SB1 -> SB1)
            prev_line = p.get("line")
            if prev_line and tr.line_name:
                b1 = extract_route_base_name(prev_line)
                b2 = extract_route_base_name(tr.line_name)
                if b1 and b2 and b1 == b2:
                    return True
            # Check spatial reversal (boarding a trip to return to the previous boarding stop)
            prev_from = normalise_id(p.get("from_stop") or "")
            if prev_from and prev_from in [normalise_id(s) for s in tr.stops]:
                try:
                    b_idx = tr.stop_indices.get(boarding_stop_norm, -1)
                    prev_from_idx = -1
                    for idx_s, st in enumerate(tr.stops):
                        if normalise_id(st) == prev_from:
                            prev_from_idx = idx_s
                            break
                    if prev_from_idx > b_idx >= 0:
                        return True
                except Exception:
                    pass
            break
        elif p_mode == "interchange":
            curr_stop = normalise_id(p.get("from_stop") or "")
            r -= 1
        else:
            break
    return False
