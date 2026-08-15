"""Configuration views and REST API endpoints for Travel Assistant."""

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

from app.db import get_db_stats
from app.models import (
    BusRoute,
    BusStop,
    LocationTransfer,
    PlatformTransfer,
    Setting,
    Station,
    Timetable,
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


@config_bp.route("")
@config_bp.route("/")
def index() -> Any:
    """Redirect top-level /config to the default configuration page."""
    return redirect(url_for("config.credentials"))


@config_bp.route("/credentials", methods=["GET", "POST"])
def credentials() -> Any:
    """Manage API credentials and service tokens."""
    if request.method == "POST":
        payload: Dict[str, str] = {}
        for field in CREDENTIAL_FIELDS:
            value = request.form.get(field, "").strip()
            payload[field] = value

        Setting.bulk_set(payload, category="credentials")
        flash("API credentials saved successfully.", "success")
        return redirect(url_for("config.credentials"), code=303)

    stored = Setting.get_by_category("credentials")
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

    # Fall back to saved database credentials if fields are not present in payload
    stored = Setting.get_all_dict()
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

            with Timetable._meta.database.atomic():
                Timetable.delete().execute()
                if cleaned_items:
                    Timetable.insert_many(cleaned_items).execute()

            flash("Timetables saved successfully.", "success")
        except Exception as e:
            flash(f"Failed to save timetables: {str(e)}", "error")

        return redirect(url_for("config.timetables"), code=303)

    current_timetables = [t.to_dict() for t in Timetable.select()]
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

    stations_count = Station.select().count()
    stops_count = BusStop.select().count()
    routes_count = BusRoute.select().count()

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
            results = [
                {
                    "transport_type": "train",
                    "name": s.name,
                    "identifier": s.crs_code,
                    "crs_code": s.crs_code,
                    "description": f"National Rail Station - {s.crs_code}"
                    + (f" ({s.operator})" if s.operator else ""),
                }
                for s in Station.search(query, limit=limit)
            ]
    elif transport_type in ("bus_stop", "stop", "bus_stops", "stops"):
        is_cached = stops_count > 0
        if is_cached:
            results = [
                {
                    "transport_type": "bus",
                    "name": s.name + (f" ({s.indicator})" if s.indicator else ""),
                    "identifier": s.atco_code,
                    "atco_code": s.atco_code,
                    "description": "Bus Stop"
                    + (f", {s.locality}" if s.locality else "")
                    + f" - {s.atco_code}",
                }
                for s in BusStop.search(query, limit=limit)
            ]
    elif transport_type in ("bus_route", "route", "bus_routes", "routes", "bus"):
        is_cached = routes_count > 0
        if is_cached:
            results = [
                {
                    "transport_type": "bus",
                    "name": f"Route {r.route_number}"
                    + (
                        f" ({r.origin} - {r.destination})"
                        if r.origin and r.destination
                        else ""
                    ),
                    "identifier": r.route_number,
                    "route_number": r.route_number,
                    "description": r.description
                    or (
                        f"Operated by {r.operator_name}"
                        if r.operator_name
                        else "Bus route"
                    ),
                }
                for r in BusRoute.search(query, limit=limit)
            ]
    elif transport_type in ("status", "status_check"):
        is_cached = (stations_count > 0) or (stops_count > 0 and routes_count > 0)
        results = []
    else:
        # Generic search across cached stations and bus routes
        is_cached = (stations_count > 0) or (stops_count > 0) or (routes_count > 0)
        if is_cached:
            st_res = [
                {
                    "transport_type": "train",
                    "name": s.name,
                    "identifier": s.crs_code,
                    "crs_code": s.crs_code,
                    "description": f"National Rail Station - {s.crs_code}",
                }
                for s in Station.search(query, limit=limit)
            ]
            rt_res = [
                {
                    "transport_type": "bus",
                    "name": f"Route {r.route_number}",
                    "identifier": r.route_number,
                    "route_number": r.route_number,
                    "description": r.description or "Bus route",
                }
                for r in BusRoute.search(query, limit=limit)
            ]
            results = (st_res + rt_res)[:limit]

    return jsonify(
        {
            "results": results,
            "total": len(results),
            "is_cached": is_cached,
            "cache_counts": cache_counts,
            "type": transport_type,
        }
    )


@config_bp.route("/transfers", methods=["GET", "POST"])
def transfers() -> Any:
    """Manage inter-location walking links and station platform transfers."""
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

            with LocationTransfer._meta.database.atomic():
                LocationTransfer.delete().execute()
                PlatformTransfer.delete().execute()
                if cleaned_location_transfers:
                    LocationTransfer.insert_many(cleaned_location_transfers).execute()
                if cleaned_platform_transfers:
                    PlatformTransfer.insert_many(cleaned_platform_transfers).execute()

            flash("Transfers saved successfully.", "success")
        except Exception as e:
            flash(f"Failed to save transfers: {str(e)}", "error")

        return redirect(url_for("config.transfers"), code=303)

    location_transfers = [t.to_dict() for t in LocationTransfer.select()]
    platform_transfers = [t.to_dict() for t in PlatformTransfer.select()]

    return render_template(
        "config_transfers.html",
        location_transfers=location_transfers,
        platform_transfers=platform_transfers,
        active_tab="transfers",
    )


@config_bp.route("/transfers/search", methods=["GET"])
def search_transfers_locations() -> Any:
    """Search stations and bus stops for transfer configuration lookup."""
    target_type = request.args.get("type", "").lower().strip()
    query = request.args.get("q", "").lower().strip()

    results: List[Dict[str, str]] = []
    seen_keys = set()

    # Query local SQLite stations
    if not target_type or target_type == "station":
        try:
            st_list = (
                Station.search(query, limit=15)
                if query
                else list(Station.select().limit(10))
            )
            for st in st_list:
                key = f"station:{st.crs_code}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    op_suffix = f" ({st.operator})" if st.operator else ""
                    results.append(
                        {
                            "type": "station",
                            "id": st.crs_code,
                            "name": st.name,
                            "description": f"National Rail Station - {st.crs_code}{op_suffix}",
                            "indicator": "Platforms",
                        }
                    )
        except Exception:
            pass

    # Query local SQLite bus stops
    if not target_type or target_type == "bus_stop":
        try:
            stop_list = (
                BusStop.search(query, limit=15)
                if query
                else list(BusStop.select().limit(10))
            )
            for sp in stop_list:
                key = f"bus_stop:{sp.atco_code}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    loc_suffix = f", {sp.locality}" if sp.locality else ""
                    ind_text = f" ({sp.indicator})" if sp.indicator else ""
                    results.append(
                        {
                            "type": "bus_stop",
                            "id": sp.atco_code,
                            "name": f"{sp.name}{ind_text}",
                            "description": f"Bus Stop{loc_suffix} - {sp.atco_code}",
                            "indicator": sp.indicator or "Stop",
                        }
                    )
        except Exception:
            pass

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


@config_bp.route("/sync", methods=["GET"])
def background_sync() -> Any:
    """Display transit dataset background synchronisation status and controls."""
    stats = get_db_stats()
    return render_template(
        "config_sync.html",
        stats=stats,
        active_tab="sync",
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
