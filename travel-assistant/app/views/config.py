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

from app.db import SettingsRepository, TimetableRepository
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
    query = request.args.get("q", "").lower().strip()

    results: List[Dict[str, str]] = []
    for item in SAMPLE_TIMETABLE_DATA:
        if transport_type and item["transport_type"] != transport_type:
            continue
        if query:
            match_name = query in item["name"].lower()
            match_id = query in item["identifier"].lower()
            match_desc = query in item["description"].lower()
            if match_name or match_id or match_desc:
                results.append(item)
        else:
            results.append(item)

    return jsonify({"results": results, "total": len(results)})
