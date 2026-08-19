"""Database statistics and transit dataset background synchronisation views."""

from typing import Any
import io
import os
import sqlite3
import tempfile
from flask import abort, current_app, jsonify, render_template, send_file

from app.db import db, get_db_path, get_db_stats, init_db
from app.sync import request_sync
from app.sync.worker import SYNC_REGISTRY
from app.views.config import config_bp


@config_bp.route("/db/data", methods=["GET"])
def db_stats_data() -> Any:
    """Return database table statistics as JSON for Grid.js remote data loading."""
    stats = get_db_stats()
    tables = stats.get("tables", [])
    return jsonify({"data": tables, "total": len(tables)})


@config_bp.route("/db", methods=["GET"])
def db_stats() -> Any:
    """Display SQLite database storage metrics and table row counts."""
    stats = get_db_stats()
    return render_template(
        "config_db.html",
        stats=stats,
        active_tab="db",
    )


@config_bp.route("/db/download", methods=["GET"])
def download_db() -> Any:
    """Download the SQLite database file as an attachment."""
    if db.obj is None:
        init_db(current_app)

    db_path = get_db_path(current_app)

    # If the database is an active SqliteDatabase instance, checkpoint WAL log to disk
    try:
        if db.obj is not None and not db.obj.is_closed():
            db.obj.execute_sql("PRAGMA wal_checkpoint(PASSIVE)")
    except Exception:
        pass

    # Check if physical database file exists on disk
    if (
        db_path != ":memory:"
        and not db_path.startswith("file:")
        and os.path.exists(db_path)
        and os.path.isfile(db_path)
    ):
        return send_file(
            db_path,
            as_attachment=True,
            download_name="travel_assistant.db",
            mimetype="application/vnd.sqlite3",
        )

    # In-memory or URI database backup fallback
    try:
        if db.obj is not None and (
            db_path == ":memory:" or db_path.startswith("file:")
        ):
            temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            temp_db_path = temp_db.name
            temp_db.close()

            dest_conn = sqlite3.connect(temp_db_path)
            src_conn = db.obj.connection()
            src_conn.backup(dest_conn)
            dest_conn.close()

            with open(temp_db_path, "rb") as f:
                db_bytes = io.BytesIO(f.read())

            try:
                os.remove(temp_db_path)
            except OSError:
                pass

            return send_file(
                db_bytes,
                as_attachment=True,
                download_name="travel_assistant.db",
                mimetype="application/vnd.sqlite3",
            )
    except Exception as e:
        current_app.logger.error("Failed to backup SQLite database: %s", e)

    abort(404, description="Database file not found.")


@config_bp.route("/sync/data", methods=["GET"])
def background_sync_data() -> Any:
    """Return syncable transit dataset statistics as JSON for Grid.js remote data loading."""
    stats = get_db_stats()
    tables = stats.get("tables", [])
    return jsonify({"data": tables, "total": len(tables)})


@config_bp.route("/sync", methods=["GET"])
def background_sync() -> Any:
    """Display transit dataset background synchronisation status and controls."""
    return render_template(
        "config_sync.html",
        active_tab="sync",
    )


@config_bp.route("/db/sync/<table_name>", methods=["POST"], strict_slashes=False)
def sync_db_table(table_name: str) -> Any:
    """Queue an on-demand synchronisation request for a specific transit dataset."""
    norm_name = table_name.lower().strip()
    valid_names = [e.table_name for e in SYNC_REGISTRY]

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

    if norm_name not in valid_names:
        return (
            jsonify(
                {
                    "success": False,
                    "status": "error",
                    "message": (
                        f"Unknown table: '{norm_name}'. "
                        f"Valid tables are: {', '.join(valid_names)}."
                    ),
                }
            ),
            400,
        )

    request_sync(norm_name)
    return jsonify(
        {
            "success": True,
            "table": norm_name,
            "status": "queued",
            "message": (
                f"Synchronisation of '{norm_name}' has been queued "
                "and will run shortly."
            ),
        }
    )
