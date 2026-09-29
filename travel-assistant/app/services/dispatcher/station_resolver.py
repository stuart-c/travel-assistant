"""UK rail station code and TIPLOC to CRS resolution service."""

import json
import logging
import os
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_MAP_PATH = os.path.join(os.path.dirname(__file__), "tiploc_crs_map.json")
_TIPLOC_TO_CRS: Optional[Dict[str, str]] = None


def _get_tiploc_map() -> Dict[str, str]:
    """Lazy-load and cache the TIPLOC-to-CRS reference dictionary."""
    global _TIPLOC_TO_CRS
    if _TIPLOC_TO_CRS is not None:
        return _TIPLOC_TO_CRS

    if os.path.exists(_MAP_PATH):
        try:
            with open(_MAP_PATH, "r", encoding="utf-8") as f:
                _TIPLOC_TO_CRS = json.load(f)
                return _TIPLOC_TO_CRS
        except Exception as exc:
            logger.warning("Failed to load tiploc_crs_map.json: %s", exc)

    _TIPLOC_TO_CRS = {}
    return _TIPLOC_TO_CRS


def resolve_station_crs(stop_id: Optional[str]) -> Optional[str]:
    """Resolve a station identifier to a standard 3-letter National Rail CRS code.

    Handles namespaced IDs (e.g. 'atco:9100CAMBNTH', 'naptan:CMB', 'tiploc:CAMBNTH'),
    canonical NaPTAN rail ATCO codes ('9100CAMBNTH'), bare TIPLOC codes ('CAMBNTH'),
    and database lookups in the Stop table.

    Returns:
        3-letter uppercase CRS code (e.g. 'CMB', 'SVG', 'KGX') if resolved, or None.
    """
    if not stop_id:
        return None

    crs = str(stop_id).strip()

    # Strip known transit namespaces
    for prefix in ("atco:", "naptan:", "tiploc:"):
        if crs.lower().startswith(prefix):
            crs = crs[len(prefix) :].strip()

    # If already a valid 3-letter uppercase CRS code
    if len(crs) == 3 and crs.isalpha():
        return crs.upper()

    # If it is a NaPTAN rail ATCO code (starts with 9100)
    bare = crs[4:] if crs.startswith("9100") else crs
    if len(bare) == 3 and bare.isalpha():
        return bare.upper()

    # Check built-in TIPLOC -> CRS mapping
    mapping = _get_tiploc_map()
    bare_upper = bare.upper()
    if bare_upper in mapping:
        return mapping[bare_upper]

    crs_upper = crs.upper()
    if crs_upper in mapping:
        return mapping[crs_upper]

    # Check embedded alphabetic TIPLOC sequences in regional NaPTAN codes (e.g. 2100STEVNGE0 -> STEVNGE -> SVG)
    import re

    for match in re.finditer(r"[A-Za-z]{3,7}", crs):
        cand = match.group(0).upper()
        if cand in mapping:
            return mapping[cand]

    # Look up in Stop table if database is initialised
    try:
        from app.models.transit import Stop

        stop = (
            Stop.select()
            .where(
                (Stop.atco_code == crs)
                | (Stop.atco_code == f"9100{bare}")
                | (Stop.naptan_code == crs)
                | (Stop.naptan_code == bare)
            )
            .first()
        )
        if stop:
            if (
                stop.naptan_code
                and len(stop.naptan_code) == 3
                and stop.naptan_code.isalpha()
            ):
                return stop.naptan_code.upper()

            # Check embedded alphabetic TIPLOC sequence in stop.atco_code
            if stop.atco_code:
                for match in re.finditer(r"[A-Za-z]{3,7}", stop.atco_code):
                    cand = match.group(0).upper()
                    if cand in mapping:
                        return mapping[cand]

            # Check if stop is a synthetic Google stop with coordinates near a known rail stop
            if (
                str(stop.atco_code or "").startswith("google:")
                and stop.latitude is not None
                and stop.longitude is not None
            ):
                nearby_rail = (
                    Stop.select()
                    .where(Stop.stop_type == "rail")
                    .where(
                        (
                            Stop.latitude.between(
                                float(stop.latitude) - 0.005,
                                float(stop.latitude) + 0.005,
                            )
                        )
                        & (
                            Stop.longitude.between(
                                float(stop.longitude) - 0.008,
                                float(stop.longitude) + 0.008,
                            )
                        )
                    )
                    .first()
                )
                if nearby_rail and nearby_rail.atco_code != stop.atco_code:
                    resolved = resolve_station_crs(nearby_rail.atco_code)
                    if resolved:
                        return resolved

            # Station name matching against TIPLOC mapping
            if stop.name:
                name_clean = re.sub(
                    r"(?i)\b(railway|rail|station|stn|tram|metro)\b", "", stop.name
                ).strip()
                name_slug = re.sub(r"[^A-Za-z]+", "", name_clean).upper()
                if name_slug in mapping:
                    return mapping[name_slug]
                words = re.findall(r"[A-Za-z]{3,7}", name_clean)
                for w in words:
                    w_upper = w.upper()
                    if w_upper in mapping:
                        return mapping[w_upper]
    except Exception:
        pass

    return None
