"""Database statistics and transit dataset background synchronisation views."""

from typing import Any
from flask import jsonify, render_template

from app.db import get_db_stats
from app.sync import sync_table
from app.views.config import config_bp


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
