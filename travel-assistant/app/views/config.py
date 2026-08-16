"""Configuration views and REST API endpoints for Travel Assistant."""

import datetime
import json
from typing import Any, Dict, List, Optional
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
    Journey,
    Location,
    LocationTransfer,
    PlatformTransfer,
    Setting,
    Stop,
    Timetable,
)
from app.sync import sync_table
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
    "google_maps_api_key",
    "google_maps_region",
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
    if not current_credentials.get("google_maps_region"):
        current_credentials["google_maps_region"] = "uk"

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
    """Manage configured timetable schedules and operating days."""
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
                name = str(entry.get("name", "")).strip()
                if not name:
                    continue

                start_date_val: Optional[datetime.date] = None
                start_date_raw = entry.get("start_date")
                if start_date_raw and str(start_date_raw).strip():
                    try:
                        start_date_val = datetime.date.fromisoformat(
                            str(start_date_raw).strip()
                        )
                    except ValueError:
                        raise ValueError(
                            f"Invalid start date format: {start_date_raw}. Expected YYYY-MM-DD."
                        )

                end_date_val: Optional[datetime.date] = None
                end_date_raw = entry.get("end_date")
                if end_date_raw and str(end_date_raw).strip():
                    try:
                        end_date_val = datetime.date.fromisoformat(
                            str(end_date_raw).strip()
                        )
                    except ValueError:
                        raise ValueError(
                            f"Invalid end date format: {end_date_raw}. Expected YYYY-MM-DD."
                        )

                if start_date_val and end_date_val and end_date_val < start_date_val:
                    raise ValueError(
                        f"End date ({end_date_val}) cannot be before "
                        f"start date ({start_date_val}) for timetable '{name}'."
                    )

                cleaned_items.append(
                    {
                        "name": name,
                        "start_date": start_date_val,
                        "end_date": end_date_val,
                        "monday": bool(entry.get("monday", True)),
                        "tuesday": bool(entry.get("tuesday", True)),
                        "wednesday": bool(entry.get("wednesday", True)),
                        "thursday": bool(entry.get("thursday", True)),
                        "friday": bool(entry.get("friday", True)),
                        "saturday": bool(entry.get("saturday", True)),
                        "sunday": bool(entry.get("sunday", True)),
                        "bank_holiday": bool(entry.get("bank_holiday", True)),
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

    stops_count = Stop.select().count()
    routes_count = BusRoute.select().count()
    cache_counts = {
        "stops": stops_count,
        "bus_routes": routes_count,
    }

    results: List[Dict[str, Any]] = []
    is_cached = True

    if transport_type in ("station", "train", "stations"):
        is_cached = stops_count > 0
        if is_cached:
            results = [
                {
                    "transport_type": "train",
                    "name": s.name,
                    "identifier": s.naptan_code or s.atco_code,
                    "crs_code": s.naptan_code or s.atco_code,
                    "description": f"National Rail Station - {s.naptan_code or s.atco_code}",
                }
                for s in Stop.search(query, stop_type="rail", limit=limit)
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
                for s in Stop.search(query, stop_type="bus", limit=limit)
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
        is_cached = (stops_count > 0) or (routes_count > 0)
        results = []
    else:
        # Generic search across cached stations and bus routes
        is_cached = (stops_count > 0) or (routes_count > 0)
        if is_cached:
            st_res = [
                {
                    "transport_type": "train",
                    "name": s.name,
                    "identifier": s.naptan_code or s.atco_code,
                    "crs_code": s.naptan_code or s.atco_code,
                    "description": f"National Rail Station - {s.naptan_code or s.atco_code}",
                }
                for s in Stop.search(query, stop_type="rail", limit=limit)
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


@config_bp.route("/locations", methods=["GET", "POST"])
def locations() -> Any:
    """Manage configured geographic locations."""
    if request.method == "POST":
        locations_raw = request.form.get("locations_json", "[]").strip()
        try:
            items = json.loads(locations_raw)
            if not isinstance(items, list):
                raise ValueError("Payload must be a list of location objects.")

            cleaned_items: List[Dict[str, Any]] = []
            for entry in items:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get("name", "")).strip()
                if not name:
                    continue

                try:
                    lat_val = entry.get("latitude")
                    lon_val = entry.get("longitude")
                    if lat_val is None or lon_val is None:
                        continue
                    lat = float(lat_val)
                    lon = float(lon_val)
                except (ValueError, TypeError):
                    continue

                if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                    continue

                cleaned_items.append(
                    {
                        "name": name,
                        "latitude": round(lat, 6),
                        "longitude": round(lon, 6),
                        "ha": bool(entry.get("ha", False)),
                    }
                )

            with Location._meta.database.atomic():
                # Preserve all existing Home Assistant synchronised records
                existing_ha_records = [
                    {
                        "name": loc.name,
                        "latitude": loc.latitude,
                        "longitude": loc.longitude,
                        "ha": True,
                    }
                    for loc in Location.select().where(
                        Location.ha == True  # noqa: E712
                    )
                ]

                # Extract only manual (ha=False) entries from submitted items
                manual_items = [
                    item for item in cleaned_items if not item.get("ha", False)
                ]

                Location.delete().execute()
                all_records = existing_ha_records + manual_items
                if all_records:
                    Location.insert_many(all_records).execute()

            flash("Locations saved successfully.", "success")
        except Exception as e:
            flash(f"Failed to save locations: {str(e)}", "error")

        return redirect(url_for("config.locations"), code=303)

    current_locations = [loc.to_dict() for loc in Location.select()]
    return render_template(
        "config_locations.html",
        locations=current_locations,
        active_tab="locations",
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
                Stop.search(query, stop_type="rail", limit=15)
                if query
                else list(Stop.select().where(Stop.stop_type == "rail").limit(10))
            )
            for st in st_list:
                st_code = st.naptan_code or st.atco_code
                key = f"station:{st_code}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    results.append(
                        {
                            "type": "station",
                            "id": st_code,
                            "name": st.name,
                            "description": f"National Rail Station - {st_code}",
                            "indicator": "Platforms",
                        }
                    )
        except Exception:
            pass

    # Query local SQLite bus stops
    if not target_type or target_type == "bus_stop":
        try:
            stop_list = (
                Stop.search(query, stop_type="bus", limit=15)
                if query
                else list(Stop.select().where(Stop.stop_type == "bus").limit(10))
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


@config_bp.route("/journeys", methods=["GET", "POST"])
def journeys() -> Any:
    """Manage configured travel journeys and multi-time-window schedules."""
    if request.method == "POST":
        journeys_raw = request.form.get("journeys_json", "[]").strip()
        try:
            items = json.loads(journeys_raw)
            if not isinstance(items, list):
                raise ValueError("Payload must be a list of journey objects.")

            cleaned_items: List[Dict[str, Any]] = []
            for entry in items:
                if not isinstance(entry, dict):
                    continue

                name = str(entry.get("name", "")).strip()
                from_type = str(entry.get("from_type", "station")).strip().lower()
                from_id = str(entry.get("from_id", "")).strip()
                from_name = str(entry.get("from_name", "")).strip()
                to_type = str(entry.get("to_type", "station")).strip().lower()
                to_id = str(entry.get("to_id", "")).strip()
                to_name = str(entry.get("to_name", "")).strip()

                if not name:
                    continue
                if not (from_id and from_name and to_id and to_name):
                    continue

                raw_time_settings = entry.get("time_settings", [])
                cleaned_time_settings: List[Dict[str, Any]] = []
                if isinstance(raw_time_settings, list):
                    for tw in raw_time_settings:
                        if not isinstance(tw, dict):
                            continue
                        days = tw.get("days", [])
                        if not isinstance(days, list):
                            days = []
                        valid_days = [
                            str(d).lower().strip()
                            for d in days
                            if str(d).lower().strip()
                            in (
                                "mon",
                                "tue",
                                "wed",
                                "thu",
                                "fri",
                                "sat",
                                "sun",
                                "bank_holiday",
                            )
                        ]
                        mode = str(tw.get("mode", "depart")).lower().strip()
                        if mode not in ("depart", "arrive"):
                            mode = "depart"
                        start_time = str(tw.get("start_time", "")).strip()
                        end_time = str(tw.get("end_time", "")).strip()

                        cleaned_time_settings.append(
                            {
                                "days": valid_days,
                                "mode": mode,
                                "start_time": start_time,
                                "end_time": end_time,
                            }
                        )

                cleaned_items.append(
                    {
                        "name": name,
                        "from_type": from_type or "station",
                        "from_id": from_id,
                        "from_name": from_name,
                        "to_type": to_type or "station",
                        "to_id": to_id,
                        "to_name": to_name,
                        "time_settings": json.dumps(cleaned_time_settings),
                    }
                )

            with Journey._meta.database.atomic():
                Journey.delete().execute()
                if cleaned_items:
                    Journey.insert_many(cleaned_items).execute()

            flash("Journeys saved successfully.", "success")
        except Exception as e:
            flash(f"Failed to save journeys: {str(e)}", "error")

        return redirect(url_for("config.journeys"), code=303)

    current_journeys = [j.to_dict() for j in Journey.select()]
    return render_template(
        "config_journeys.html",
        journeys=current_journeys,
        active_tab="journeys",
    )


@config_bp.route("/journeys/search", methods=["GET"])
def search_journey_locations() -> Any:
    """Search stations, bus stops, and custom/Home Assistant locations for journey configuration."""
    target_type = request.args.get("type", "").lower().strip()
    query = request.args.get("q", "").strip()
    limit_raw = request.args.get("limit", "15").strip()
    try:
        limit = max(1, min(int(limit_raw), 50))
    except ValueError:
        limit = 15

    results: List[Dict[str, Any]] = []
    seen_keys = set()

    # Query Rail Stations
    if not target_type or target_type in ("station", "train", "rail"):
        try:
            st_list = (
                Stop.search(query, stop_type="rail", limit=limit)
                if query
                else list(Stop.select().where(Stop.stop_type == "rail").limit(limit))
            )
            for st in st_list:
                st_code = st.naptan_code or st.atco_code
                key = f"station:{st_code}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    results.append(
                        {
                            "type": "station",
                            "id": st_code,
                            "name": st.name,
                            "description": f"National Rail Station - {st_code}",
                            "indicator": "Rail",
                            "icon": "train",
                        }
                    )
        except Exception:
            pass

    # Query Bus Stops
    if not target_type or target_type in ("bus_stop", "bus", "stop"):
        try:
            stop_list = (
                Stop.search(query, stop_type="bus", limit=limit)
                if query
                else list(Stop.select().where(Stop.stop_type == "bus").limit(limit))
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
                            "indicator": sp.indicator or "Bus Stop",
                            "icon": "directions_bus",
                        }
                    )
        except Exception:
            pass

    # Query Custom & Home Assistant Locations
    if not target_type or target_type in (
        "location",
        "ha_location",
        "custom_location",
        "ha",
        "custom",
    ):
        try:
            loc_list = (
                Location.search(query, limit=limit)
                if query
                else list(Location.select().limit(limit))
            )
            for loc in loc_list:
                is_ha = bool(getattr(loc, "ha", False))
                loc_type = "ha_location" if is_ha else "custom_location"
                if target_type and target_type not in ("location", loc_type):
                    continue

                key = f"{loc_type}:{loc.id}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    icon = "home" if is_ha else "pin_drop"
                    indicator = "Home Assistant" if is_ha else "Custom"
                    desc = (
                        f"{indicator} Location - "
                        f"({loc.latitude:.4f}, {loc.longitude:.4f})"
                    )
                    results.append(
                        {
                            "type": loc_type,
                            "id": str(loc.id),
                            "name": loc.name,
                            "description": desc,
                            "indicator": indicator,
                            "icon": icon,
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


@config_bp.route("/db/sync/<table_name>", methods=["POST"], strict_slashes=False)
def sync_db_table(table_name: str) -> Any:
    """Trigger on-demand synchronisation for a specific transit dataset."""
    norm_name = table_name.lower().strip()
    if not norm_name or norm_name == "all":
        return (
            jsonify(
                {
                    "success": False,
                    "status": "error",
                    "message": (
                        "Bulk dataset synchronisation is not supported. "
                        "Please synchronise individual tables."
                    ),
                }
            ),
            400,
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
