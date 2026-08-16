"""Common utility functions and shared controllers for configuration views."""

import json
from typing import Any, Callable, Dict, List, Optional, Type
from flask import flash, redirect, request, url_for
from peewee import Model


def parse_json_form_list(form_key: str) -> List[Dict[str, Any]]:
    """Extract and deserialize a JSON list from form data.

    Args:
        form_key: Name of the form field containing JSON payload.

    Returns:
        List of deserialized dictionary items.

    Raises:
        ValueError: If JSON is invalid or payload is not a list.
    """
    raw_val = request.form.get(form_key, "[]").strip()
    items = json.loads(raw_val)
    if not isinstance(items, list):
        raise ValueError(f"Form field '{form_key}' must contain a JSON list.")
    return [item for item in items if isinstance(item, dict)]


def save_bulk_config(
    form_key: str,
    model_class: Type[Model],
    clean_item_func: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]],
    entity_label: str,
    redirect_endpoint: str,
    custom_save_fn: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
) -> Any:
    """Standardized handler for bulk configuration JSON POST submissions.

    Extracts JSON payload, validates and sanitises items, performs atomic database replacement,
    sets flash feedback messages, and returns a 303 redirect.

    Args:
        form_key: Name of form field containing JSON data.
        model_class: Peewee model class to update.
        clean_item_func: Callback to sanitize and validate each item dictionary.
        entity_label: Human-readable entity name for flash messages (e.g. 'Journeys').
        redirect_endpoint: Endpoint for 303 redirect after POST.
        custom_save_fn: Optional custom database persist callback.

    Returns:
        Flask 303 Redirect response.
    """
    try:
        raw_items = parse_json_form_list(form_key)
        cleaned_items: List[Dict[str, Any]] = []

        for entry in raw_items:
            cleaned = clean_item_func(entry)
            if cleaned is not None:
                cleaned_items.append(cleaned)

        if custom_save_fn is not None:
            custom_save_fn(cleaned_items)
        else:
            with model_class._meta.database.atomic():
                model_class.delete().execute()
                if cleaned_items:
                    model_class.insert_many(cleaned_items).execute()

        flash(f"{entity_label} saved successfully.", "success")
    except Exception as e:
        flash(f"Failed to save {entity_label.lower()}: {str(e)}", "error")

    return redirect(url_for(redirect_endpoint), code=303)
