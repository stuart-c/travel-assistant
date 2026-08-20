"""Common utility functions and task runners for transit synchronisation routines."""

import logging
import time
from typing import Any, Callable, Dict, Optional
from flask import Flask
import requests

from app.datasources.exceptions import (
    DataSourceAuthError,
    DataSourceConfigError,
    DataSourceConnectionError,
    DataSourceError,
    DataSourceRateLimitError,
)
from app.db import db, init_db
from app.models.transit import SyncMetadata

logger = logging.getLogger(__name__)


def ensure_db_initialised(app: Optional[Flask] = None) -> None:
    """Ensure Peewee DatabaseProxy has been initialised."""
    if db.obj is None:
        init_db(app)


def run_sync_task(
    table_name: str,
    sync_operation: Callable[[], int],
    client_check: Optional[Callable[[], Optional[str]]] = None,
    success_message_factory: Optional[Callable[[int], str]] = None,
    provider_name: Optional[str] = None,
    connection_error_template: Optional[str] = None,
    app: Optional[Flask] = None,
) -> Dict[str, Any]:
    """Execute a dataset synchronisation routine with standardised telemetry and error handling.

    Args:
        table_name: Canonical name of the registered synchronisation table.
        sync_operation: Zero-argument callable performing the fetch and database upsert,
            returning the total count of synchronised records.
        client_check: Optional callable that returns an error message string if credentials
            or prerequisites are missing, or None if valid.
        success_message_factory: Optional callable taking record count and
            returning a success message string.

        provider_name: Optional label for the provider (e.g. 'BODS', 'AWS S3').
        connection_error_template: Optional format string for connection errors with '{error}'.
        app: Optional Flask application context.

    Returns:
        Dictionary conforming to standard sync telemetry response:
        {"table": str, "status": str, "records": int, "message": str, "duration_seconds": float}
    """
    ensure_db_initialised(app)
    start_time = time.time()

    with db.connection_context():
        if client_check is not None:
            skip_message = client_check()
            if skip_message:
                SyncMetadata.record_skipped(table_name, skip_message)
                return {
                    "table": table_name,
                    "status": "skipped_no_credentials",
                    "records": 0,
                    "message": skip_message,
                    "duration_seconds": 0.0,
                }

        SyncMetadata.record_start(table_name)

        try:
            records_count = sync_operation()
            duration = round(time.time() - start_time, 2)
            SyncMetadata.record_success(table_name, records_count, duration)
            if success_message_factory is not None:
                msg = success_message_factory(records_count)
            else:
                msg = (
                    f"Successfully synchronised {records_count} "
                    f"record(s) for '{table_name}'."
                )

            return {
                "table": table_name,
                "status": "success",
                "records": records_count,
                "message": msg,
                "duration_seconds": duration,
            }

        except (DataSourceAuthError, DataSourceConfigError) as exc:
            duration = round(time.time() - start_time, 2)
            err_msg = str(exc)
            SyncMetadata.record_error(table_name, err_msg, duration)
            return {
                "table": table_name,
                "status": "error",
                "records": 0,
                "message": err_msg,
                "duration_seconds": duration,
            }

        except DataSourceRateLimitError as exc:
            duration = round(time.time() - start_time, 2)
            if connection_error_template:
                err_msg = connection_error_template.format(error=str(exc))
            else:
                err_msg = f"Rate limit exceeded: {str(exc)}"
            SyncMetadata.record_error(table_name, err_msg, duration)
            return {
                "table": table_name,
                "status": "error",
                "records": 0,
                "message": err_msg,
                "duration_seconds": duration,
            }

        except (
            DataSourceConnectionError,
            requests.exceptions.RequestException,
        ) as exc:
            duration = round(time.time() - start_time, 2)
            if connection_error_template:
                err_msg = connection_error_template.format(error=str(exc))
            elif provider_name:
                err_msg = (
                    f"Network or API error while contacting {provider_name}: "
                    f"{str(exc)}"
                )
            else:
                err_msg = (
                    f"Network or connection error while contacting {table_name}: "
                    f"{str(exc)}"
                )
            SyncMetadata.record_error(table_name, err_msg, duration)
            return {
                "table": table_name,
                "status": "error",
                "records": 0,
                "message": err_msg,
                "duration_seconds": duration,
            }

        except DataSourceError as exc:
            duration = round(time.time() - start_time, 2)
            if connection_error_template:
                err_msg = connection_error_template.format(error=str(exc))
            else:
                err_msg = str(exc)
            SyncMetadata.record_error(table_name, err_msg, duration)
            return {
                "table": table_name,
                "status": "error",
                "records": 0,
                "message": err_msg,
                "duration_seconds": duration,
            }

        except Exception as exc:
            duration = round(time.time() - start_time, 2)
            err_msg = (
                f"Unexpected error during {table_name} synchronisation: " f"{str(exc)}"
            )
            SyncMetadata.record_error(table_name, err_msg, duration)
            return {
                "table": table_name,
                "status": "error",
                "records": 0,
                "message": err_msg,
                "duration_seconds": duration,
            }
