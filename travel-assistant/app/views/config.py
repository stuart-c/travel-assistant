import json
from typing import Any, Dict, List
from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from app.db import (
    BusRouteRepository,
    BusStopRepository,
    SettingsRepository,
    StationRepository,
    TimetableRepository,
    TransferRepository,
    get_db_stats,
)
from app.sync import sync_all, sync_table
from app.validators import validate_service_credentials

config_bp = Blueprint("config", __name__, url_prefix="/config")

CREDENTIAL_FIELDS = [
    "bus_api_key",
    "train_s3_bucket",
    "train_s3_access_key",
    "train_s3_secret_key",
    "train_s3_region",
    "train_live_api_key",
    "train_live_endpoint",
    "open_api_key",
    "open_api_base_url",
    "open_api_model",
]


# Stage 1 sample dataset for timetable search lookup
SAMPLE_TIMETABLE_DATA: List[Dict[str, str]] = [
    {
        "transport_type": "bus",
        "name": "Oxford Tube (London Victoria - Oxford)",
        "identifier": "OX-TUBE",
        "description": "Express coach service via Hillingdon and Lewknor",
    },
    {
        "transport_type": "bus",
        "name": "Route 1 (Blackbird Leys - Oxford City Centre)",
        "identifier": "OX-01",
        "description": "Oxford Bus Company frequent urban corridor",
    },
    {
        "transport_type": "bus",
        "name": "Route 5 (Blackbird Leys - Oxford Rail Station)",
        "identifier": "OX-05",
        "description": "High frequency rail station link",
    },
    {
        "transport_type": "bus",
        "name": "Route 7 (Woodstock - Kidlington - Oxford)",
        "identifier": "OX-07",
        "description": "Stagecoach Oxfordshire regional service",
    },
    {
        "transport_type": "bus",
        "name": "Route 10 (JR Hospital - Oxford City Centre)",
        "identifier": "OX-10",
        "description": "Key hospital transit link",
    },
    {
        "transport_type": "bus",
        "name": "Route X5 (Oxford - Bicester - Bedford - Cambridge)",
        "identifier": "STAGE-X5",
        "description": "Cross-county inter-city express",
    },
    {
        "transport_type": "bus",
        "name": "Route S1 (Carterton - Witney - Oxford)",
        "identifier": "STAGE-S1",
        "description": "West Oxfordshire main line connector",
    },
    {
        "transport_type": "bus",
        "name": "Route 24 (Hampstead Heath - Pimlico)",
        "identifier": "LON-024",
        "description": "Transport for London central electric bus route",
    },
    {
        "transport_type": "bus",
        "name": "Route 73 (Oxford Circus - Stoke Newington)",
        "identifier": "LON-073",
        "description": "TfL North-East London trunk route",
    },
    {
        "transport_type": "train",
        "name": "London Paddington (PAD) - Great Western Railway",
        "identifier": "PAD",
        "description": "Main western terminus with Elizabeth Line & Heathrow Express",
    },
    {
        "transport_type": "train",
        "name": "London Marylebone (MYB) - Chiltern Railways",
        "identifier": "MYB",
        "description": "Direct fast services to Oxford and Birmingham Moor St",
    },
    {
        "transport_type": "train",
        "name": "London Waterloo (WAT) - South Western Railway",
        "identifier": "WAT",
        "description": "Major southern mainline hub",
    },
    {
        "transport_type": "train",
        "name": "London King's Cross (KGX) - LNER / Great Northern",
        "identifier": "KGX",
        "description": "East Coast Main Line terminus to Yorkshire and Scotland",
    },
    {
        "transport_type": "train",
        "name": "London Euston (EUS) - Avanti West Coast",
        "identifier": "EUS",
        "description": "West Coast Main Line to West Midlands and North West",
    },
    {
        "transport_type": "train",
        "name": "London St Pancras Int (STP) - Thameslink / Eurostar",
        "identifier": "STP",
        "description": "Midland Main Line and international continental links",
    },
    {
        "transport_type": "train",
        "name": "Oxford (OXF) - GWR & Chiltern Railways",
        "identifier": "OXF",
        "description": "Central station connecting London, Birmingham, and Didcot",
    },
    {
        "transport_type": "train",
        "name": "Oxford Parkway (OXP) - Chiltern Railways",
        "identifier": "OXP",
        "description": "Park & ride station for London Marylebone services",
    },
    {
        "transport_type": "train",
        "name": "Reading (RDG) - Great Western Railway",
        "identifier": "RDG",
        "description": "High capacity interchange hub with Elizabeth line",
    },
    {
        "transport_type": "train",
        "name": "Didcot Parkway (DID) - Great Western Railway",
        "identifier": "DID",
        "description": "Thames Valley junction station",
    },
    {
        "transport_type": "train",
        "name": "Birmingham New Street (BHM) - CrossCountry / Avanti",
        "identifier": "BHM",
        "description": "Midlands interchange connecting North, South, East, and West",
    },
    {
        "transport_type": "train",
        "name": "Manchester Piccadilly (MAN) - TransPennine / Avanti",
        "identifier": "MAN",
        "description": "North West terminus and cross-regional gateway",
    },
    {
        "transport_type": "train",
        "name": "Bristol Temple Meads (BRI) - Great Western Railway",
        "identifier": "BRI",
        "description": "South West junction and main city hub",
    },
]


@config_bp.route("")
@config_bp.route("/")
def index() -> Any:
    """Redirect top-level /config to the default configuration page."""
    return redirect(url_for("config.credentials"))


@config_bp.route("/credentials", methods=["GET", "POST"])
def credentials() -> Any:
    """Manage API credentials and service tokens."""
    repo = SettingsRepository()

    if request.method == "POST":
        payload: Dict[str, str] = {}
        for field in CREDENTIAL_FIELDS:
            value = request.form.get(field, "").strip()
            payload[field] = value

        repo.set_many(payload, category="credentials")
        flash("API credentials saved successfully.", "success")
        return redirect(url_for("config.credentials"), code=303)

    stored = repo.get_all(category="credentials")
    current_credentials = {field: stored.get(field, "") for field in CREDENTIAL_FIELDS}
    if not current_credentials.get("open_api_model"):
        current_credentials["open_api_model"] = "gpt-4o-mini"

    return render_template(
        "config_credentials.html",
        credentials=current_credentials,
        active_tab="credentials",
    )


@config_bp.route("/credentials/validate", methods=["POST"])
def validate_credentials() -> Any:
    """Validate a specific credential configuration asynchronously."""
    raw_payload = request.get_json(silent=True)
    if not isinstance(raw_payload, dict):
        raw_payload = request.form.to_dict()

    service = raw_payload.get("service", "").strip()
    if not service:
        return (
            jsonify(
                {
                    "valid": False,
                    "message": "Service name is required for validation.",
                }
            ),
            400,
        )

    # Fall back to saved repository credentials if fields are not present in payload
    repo = SettingsRepository()
    stored = repo.get_all(category="credentials")
    merged_payload = dict(stored)
    merged_payload.update(raw_payload)

    is_valid, message, extra_data = validate_service_credentials(
        service, merged_payload
    )
    status_code = 400 if message.startswith("Unknown service") else 200

    response_body = {
        "valid": is_valid,
        "message": message,
        "service": service,
    }
    if extra_data:
        response_body.update(extra_data)

    return (
        jsonify(response_body),
        status_code,
    )


@config_bp.route("/timetables", methods=["GET", "POST"])
def timetables() -> Any:
    """Manage bus and train timetable entries."""
    repo = TimetableRepository()

    if request.method == "POST":
        timetables_raw = request.form.get("timetables_json", "[]").strip()
        try:
            items = json.loads(timetables_raw)
            if not isinstance(items, list):
                raise ValueError("Payload must be a list of timetable objects.")

            cleaned_items: List[Dict[str, Any]] = []
            for entry in items:
                if not isinstance(entry, dict):
                    continue
                transport_type = str(entry.get("transport_type", "bus")).lower().strip()
                if transport_type not in ["bus", "train"]:
                    transport_type = "bus"
                name = str(entry.get("name", "")).strip()
                identifier = str(entry.get("identifier", "")).strip()
                status = str(entry.get("status", "active")).lower().strip()
                if status not in ["active", "inactive"]:
                    status = "active"

                if name and identifier:
                    cleaned_items.append(
                        {
                            "transport_type": transport_type,
                            "name": name,
                            "identifier": identifier,
                            "status": status,
                        }
                    )

            repo.replace_all(cleaned_items)
            flash("Timetables saved successfully.", "success")
        except Exception as e:
            flash(f"Failed to save timetables: {str(e)}", "error")

        return redirect(url_for("config.timetables"), code=303)

    current_timetables = repo.get_all()
    return render_template(
        "config_timetables.html",
        timetables=current_timetables,
        active_tab="timetables",
    )


@config_bp.route("/timetables/search", methods=["GET"])
def search_timetables() -> Any:
    """Search and lookup timetable feeds, stations, and bus routes."""
    transport_type = request.args.get("type", "").lower().strip()
    query = request.args.get("q", "").strip()
    limit_raw = request.args.get("limit", "25").strip()
    try:
        limit = max(1, min(int(limit_raw), 100))
    except ValueError:
        limit = 25

    station_repo = StationRepository()
    stop_repo = BusStopRepository()
    route_repo = BusRouteRepository()

    stations_count = station_repo.count()
    stops_count = stop_repo.count()
    routes_count = route_repo.count()

    cache_counts = {
        "stations": stations_count,
        "bus_stops": stops_count,
        "bus_routes": routes_count,
    }

    results: List[Dict[str, Any]] = []
    is_cached = True

    if transport_type in ("station", "train", "stations"):
        is_cached = stations_count > 0
        if is_cached:
            results = station_repo.search(query, limit=limit)
    elif transport_type in ("bus_stop", "stop", "bus_stops", "stops"):
        is_cached = stops_count > 0
        if is_cached:
            results = stop_repo.search(query, limit=limit)
    elif transport_type in ("bus_route", "route", "bus_routes", "routes", "bus"):
        is_cached = routes_count > 0
        if is_cached:
            results = route_repo.search(query, limit=limit)
    elif transport_type in ("status", "status_check"):
        is_cached = (stations_count > 0) or (stops_count > 0 and routes_count > 0)
        results = []
    else:
        # Generic / fallback search
        is_cached = (stations_count > 0) or (stops_count > 0) or (routes_count > 0)
        if is_cached:
            st_res = station_repo.search(query, limit=limit)
            rt_res = route_repo.search(query, limit=limit)
            results = st_res + rt_res

    # Fallback to SAMPLE_TIMETABLE_DATA if not cached from database
    if not is_cached and transport_type not in ("status", "status_check"):
        target_mode = (
            "train"
            if transport_type in ("station", "train", "stations")
            else (
                "bus"
                if transport_type
                in (
                    "bus_stop",
                    "stop",
                    "bus_stops",
                    "stops",
                    "bus_route",
                    "route",
                    "bus_routes",
                    "routes",
                    "bus",
                )
                else ""
            )
        )
        for item in SAMPLE_TIMETABLE_DATA:
            if target_mode and item["transport_type"] != target_mode:
                continue
            if query:
                match_name = query.lower() in item["name"].lower()
                match_id = query.lower() in item["identifier"].lower()
                match_desc = query.lower() in item["description"].lower()
                if match_name or match_id or match_desc:
                    results.append(item)
            else:
                results.append(item)

    return jsonify(
        {
            "results": results,
            "total": len(results),
            "is_cached": is_cached,
            "cache_counts": cache_counts,
            "type": transport_type,
        }
    )


SAMPLE_LOCATION_SEARCH_DATA: List[Dict[str, str]] = [
    {
        "type": "station",
        "id": "OXF",
        "name": "Oxford Rail Station",
        "description": "National Rail Station (OXF)",
        "indicator": "Platforms 1-4",
    },
    {
        "type": "station",
        "id": "PAD",
        "name": "London Paddington",
        "description": "National Rail & Elizabeth Line Terminus (PAD)",
        "indicator": "Platforms 1-14",
    },
    {
        "type": "station",
        "id": "MYB",
        "name": "London Marylebone",
        "description": "Chiltern Railways Mainline Terminus (MYB)",
        "indicator": "Platforms 1-6",
    },
    {
        "type": "station",
        "id": "BHM",
        "name": "Birmingham New Street",
        "description": "Major Midlands Interchange (BHM)",
        "indicator": "Platforms 1-12",
    },
    {
        "type": "station",
        "id": "RDG",
        "name": "Reading Rail Station",
        "description": "Thames Valley Interchange (RDG)",
        "indicator": "Platforms 1-15",
    },
    {
        "type": "bus_stop",
        "id": "340000001",
        "name": "Oxford Frideswide Square (Stop R1)",
        "description": "Frideswide Square / Rail Station Forecourt",
        "indicator": "Stop R1",
    },
    {
        "type": "bus_stop",
        "id": "340000002",
        "name": "Oxford Gloucester Green Bus Station",
        "description": "Gloucester Green Coach & Bus Terminal",
        "indicator": "Bays 1-8",
    },
    {
        "type": "bus_stop",
        "id": "340000003",
        "name": "Oxford High Street (Stop T1)",
        "description": "City Centre Interchange Corridor",
        "indicator": "Stop T1",
    },
    {
        "type": "bus_stop",
        "id": "490000001",
        "name": "London Victoria Coach Station",
        "description": "Buckingham Palace Road Terminal",
        "indicator": "Gates 1-20",
    },
]


@config_bp.route("/transfers", methods=["GET", "POST"])
def transfers() -> Any:
    """Manage inter-location walking links and station platform transfers."""
    repo = TransferRepository()

    if request.method == "POST":
        loc_raw = request.form.get("location_transfers_json", "[]").strip()
        plat_raw = request.form.get("platform_transfers_json", "[]").strip()

        try:
            loc_items = json.loads(loc_raw)
            plat_items = json.loads(plat_raw)

            if not isinstance(loc_items, list) or not isinstance(plat_items, list):
                raise ValueError(
                    "Payload must contain valid location and platform transfer lists."
                )

            cleaned_location_transfers: List[Dict[str, Any]] = []
            for entry in loc_items:
                if not isinstance(entry, dict):
                    continue
                from_type = str(entry.get("from_type", "station")).lower().strip()
                if from_type not in ["station", "bus_stop"]:
                    from_type = "station"
                from_id = str(entry.get("from_id", "")).strip()
                from_name = str(entry.get("from_name", "")).strip()

                to_type = str(entry.get("to_type", "bus_stop")).lower().strip()
                if to_type not in ["station", "bus_stop"]:
                    to_type = "bus_stop"
                to_id = str(entry.get("to_id", "")).strip()
                to_name = str(entry.get("to_name", "")).strip()

                try:
                    transfer_time = max(1, int(entry.get("transfer_time_minutes", 5)))
                except (ValueError, TypeError):
                    transfer_time = 5

                bidirectional = bool(entry.get("bidirectional", True))
                step_free = bool(entry.get("step_free", False))
                notes = str(entry.get("notes", "")).strip()

                if from_id and to_id and from_name and to_name:
                    cleaned_location_transfers.append(
                        {
                            "from_type": from_type,
                            "from_id": from_id,
                            "from_name": from_name,
                            "to_type": to_type,
                            "to_id": to_id,
                            "to_name": to_name,
                            "transfer_time_minutes": transfer_time,
                            "bidirectional": bidirectional,
                            "step_free": step_free,
                            "notes": notes,
                        }
                    )

            cleaned_platform_transfers: List[Dict[str, Any]] = []
            for entry in plat_items:
                if not isinstance(entry, dict):
                    continue
                loc_type = str(entry.get("location_type", "station")).lower().strip()
                if loc_type not in ["station", "bus_stop"]:
                    loc_type = "station"
                location_id = str(entry.get("location_id", "")).strip()
                location_name = str(entry.get("location_name", "")).strip()
                from_platform = str(entry.get("from_platform", "")).strip()
                to_platform = str(entry.get("to_platform", "")).strip()

                try:
                    transfer_time = max(1, int(entry.get("transfer_time_minutes", 2)))
                except (ValueError, TypeError):
                    transfer_time = 2

                bidirectional = bool(entry.get("bidirectional", True))
                step_free = bool(entry.get("step_free", False))
                notes = str(entry.get("notes", "")).strip()

                if location_id and location_name and from_platform and to_platform:
                    cleaned_platform_transfers.append(
                        {
                            "location_type": loc_type,
                            "location_id": location_id,
                            "location_name": location_name,
                            "from_platform": from_platform,
                            "to_platform": to_platform,
                            "transfer_time_minutes": transfer_time,
                            "bidirectional": bidirectional,
                            "step_free": step_free,
                            "notes": notes,
                        }
                    )

            repo.replace_all(cleaned_location_transfers, cleaned_platform_transfers)
            flash("Transfers saved successfully.", "success")
        except Exception as e:
            flash(f"Failed to save transfers: {str(e)}", "error")

        return redirect(url_for("config.transfers"), code=303)

    transfers_data = repo.get_all()
    return render_template(
        "config_transfers.html",
        location_transfers=transfers_data["location_transfers"],
        platform_transfers=transfers_data["platform_transfers"],
        active_tab="transfers",
    )


@config_bp.route("/transfers/search", methods=["GET"])
def search_transfers_locations() -> Any:
    """Search stations and bus stops for transfer configuration lookup."""
    target_type = request.args.get("type", "").lower().strip()
    query = request.args.get("q", "").lower().strip()

    results: List[Dict[str, str]] = []
    seen_keys = set()

    # Query local SQLite stations database
    if not target_type or target_type == "station":
        station_repo = StationRepository()
        try:
            cursor = station_repo.conn.cursor()
            if query:
                cursor.execute(
                    """
                    SELECT crs_code, name, operator
                    FROM stations
                    WHERE LOWER(name) LIKE ? OR LOWER(crs_code) LIKE ?
                    ORDER BY name ASC
                    LIMIT 15
                    """,
                    (f"%{query}%", f"%{query}%"),
                )
            else:
                cursor.execute("""
                    SELECT crs_code, name, operator
                    FROM stations
                    ORDER BY name ASC
                    LIMIT 10
                    """)
            for row in cursor.fetchall():
                key = f"station:{row['crs_code']}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    op_suffix = f" ({row['operator']})" if row["operator"] else ""
                    results.append(
                        {
                            "type": "station",
                            "id": row["crs_code"],
                            "name": row["name"],
                            "description": f"National Rail Station - {row['crs_code']}{op_suffix}",
                            "indicator": "Platforms",
                        }
                    )
        except Exception:
            pass

    # Query local SQLite bus stops database
    if not target_type or target_type == "bus_stop":
        bus_stop_repo = BusStopRepository()
        try:
            cursor = bus_stop_repo.conn.cursor()
            if query:
                cursor.execute(
                    """
                    SELECT atco_code, name, indicator, locality
                    FROM bus_stops
                    WHERE LOWER(name) LIKE ? OR LOWER(atco_code) LIKE ? OR LOWER(locality) LIKE ?
                    ORDER BY name ASC
                    LIMIT 15
                    """,
                    (f"%{query}%", f"%{query}%", f"%{query}%"),
                )
            else:
                cursor.execute("""
                    SELECT atco_code, name, indicator, locality
                    FROM bus_stops
                    ORDER BY name ASC
                    LIMIT 10
                    """)
            for row in cursor.fetchall():
                key = f"bus_stop:{row['atco_code']}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    loc_suffix = f", {row['locality']}" if row["locality"] else ""
                    ind_text = f" ({row['indicator']})" if row["indicator"] else ""
                    results.append(
                        {
                            "type": "bus_stop",
                            "id": row["atco_code"],
                            "name": f"{row['name']}{ind_text}",
                            "description": f"Bus Stop{loc_suffix} - {row['atco_code']}",
                            "indicator": row["indicator"] or "Stop",
                        }
                    )
        except Exception:
            pass

    # Supplement with sample data if query matches or result count is low
    for item in SAMPLE_LOCATION_SEARCH_DATA:
        if target_type and item["type"] != target_type:
            continue
        key = f"{item['type']}:{item['id']}"
        if key in seen_keys:
            continue

        if query:
            match_name = query in item["name"].lower()
            match_id = query in item["id"].lower()
            match_desc = query in item["description"].lower()
            if match_name or match_id or match_desc:
                results.append(item)
                seen_keys.add(key)
        elif len(results) < 10:
            results.append(item)
            seen_keys.add(key)

    return jsonify({"results": results, "total": len(results)})


@config_bp.route("/db", methods=["GET"])
def db_stats() -> Any:
    """Display SQLite database storage metrics and table row counts."""
    stats = get_db_stats()
    return render_template(
        "config_db.html",
        stats=stats,
        active_tab="db",
    )


@config_bp.route("/db/sync", methods=["POST"], strict_slashes=False)
@config_bp.route("/db/sync/<table_name>", methods=["POST"], strict_slashes=False)
def sync_db_table(table_name: str = "all") -> Any:
    """Trigger on-demand synchronisation for a specific transit dataset or all datasets."""
    norm_name = table_name.lower().strip()
    if norm_name in ("all", ""):
        result = sync_all(force=True)
        stats = get_db_stats()
        return jsonify(
            {
                "success": result.get("success", False),
                "table": "all",
                "total_records": result.get("total_records", 0),
                "tables": result.get("tables", {}),
                "stats": stats,
            }
        )

    result = sync_table(norm_name, force=True)
    status_code = 200 if result.get("status") != "error" else 400
    stats = get_db_stats()
    return (
        jsonify(
            {
                "success": result.get("status")
                in ("success", "skipped_no_credentials"),
                "table": norm_name,
                "status": result.get("status"),
                "records": result.get("records", 0),
                "message": result.get("message", ""),
                "duration_seconds": result.get("duration_seconds", 0.0),
                "stats": stats,
            }
        ),
        status_code,
    )
