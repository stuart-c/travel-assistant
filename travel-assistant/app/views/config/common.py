"""Common utility functions and shared controllers for configuration views."""

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type
from flask import Blueprint, flash, redirect, render_template, request, url_for
from peewee import Model


def parse_json_form_changeset(form_key: str) -> Dict[str, List[Any]]:
    """Extract and deserialise a JSON changeset dictionary from form data.

    Expected payload format:
    {
        "added": [ ... ],
        "updated": [ ... ],
        "deleted": [ id1, id2, ... ]
    }

    Args:
        form_key: Name of the form field containing JSON payload.

    Returns:
        Dictionary with 'added', 'updated', and 'deleted' lists.

    Raises:
        ValueError: If JSON is invalid or payload structure is unsupported.
    """
    raw_val = request.form.get(form_key, "").strip()
    if not raw_val or raw_val == "{}":
        return {"added": [], "updated": [], "deleted": []}

    try:
        data = json.loads(raw_val)
    except Exception as e:
        raise ValueError(f"Invalid JSON payload in '{form_key}': {str(e)}")

    if isinstance(data, dict):
        if not any(k in data for k in ("added", "updated", "deleted")):
            raise ValueError(
                f"Form field '{form_key}' must contain 'added', 'updated', or 'deleted' lists"
            )
        added_raw = data.get("added", [])
        updated_raw = data.get("updated", [])
        deleted_raw = data.get("deleted", [])

        if not (
            isinstance(added_raw, list)
            and isinstance(updated_raw, list)
            and isinstance(deleted_raw, list)
        ):
            raise ValueError(
                f"Form field '{form_key}' must contain 'added', 'updated', and 'deleted' lists"
            )

        added = [item for item in added_raw if isinstance(item, dict)]
        updated = [item for item in updated_raw if isinstance(item, dict)]
        deleted = [
            item for item in deleted_raw if item is not None and str(item).strip() != ""
        ]
        return {"added": added, "updated": updated, "deleted": deleted}

    raise ValueError(
        f"Form field '{form_key}' must contain a JSON changeset dictionary."
    )


def apply_model_changeset(
    model_class: Type[Model],
    changeset: Dict[str, List[Any]],
    clean_item_func: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]],
    scope_filter: Optional[Any] = None,
) -> Dict[str, int]:
    """Atomically apply added, updated, and deleted changeset items to a database model.

    Args:
        model_class: Peewee model class to update.
        changeset: Dictionary with 'added', 'updated', and 'deleted' lists.
        clean_item_func: Callback to sanitize and validate each item dictionary.
        scope_filter: Optional Peewee boolean expression to constrain updates and deletes.

    Returns:
        Dictionary containing counts of 'added', 'updated', and 'deleted' records.
    """
    pk_field = model_class._meta.primary_key
    pk_name = pk_field.name

    stats = {"added": 0, "updated": 0, "deleted": 0}

    with model_class._meta.database.atomic():
        # 1. Process deletions
        deleted_ids = changeset.get("deleted", [])
        if deleted_ids:
            del_query = model_class.delete().where(pk_field.in_(deleted_ids))
            if scope_filter is not None:
                del_query = del_query.where(scope_filter)
            stats["deleted"] = del_query.execute()

        # 2. Process updates
        for raw_item in changeset.get("updated", []):
            cleaned = clean_item_func(raw_item)
            if cleaned is None:
                continue

            item_pk = cleaned.get(pk_name) or raw_item.get(pk_name)
            if item_pk is None:
                continue

            try:
                q = model_class.select().where(pk_field == item_pk)
                if scope_filter is not None:
                    q = q.where(scope_filter)
                instance = q.get()
            except model_class.DoesNotExist:
                # If target record is not found in scoped dataset, insert as new
                cleaned_copy = dict(cleaned)
                model_class.create(**cleaned_copy)
                stats["added"] += 1
                continue

            has_changed = False
            for k, v in cleaned.items():
                if k == pk_name:
                    continue
                if hasattr(instance, k):
                    old_v = getattr(instance, k)
                    if old_v != v:
                        setattr(instance, k, v)
                        has_changed = True

            if has_changed:
                instance.save()
                stats["updated"] += 1

        # 3. Process additions
        for raw_item in changeset.get("added", []):
            cleaned = clean_item_func(raw_item)
            if cleaned is None:
                continue

            cleaned_copy = dict(cleaned)
            if pk_name in cleaned_copy and cleaned_copy[pk_name] is None:
                del cleaned_copy[pk_name]

            model_class.create(**cleaned_copy)
            stats["added"] += 1

    return stats


def save_changeset_config(
    form_key: str,
    model_class: Type[Model],
    clean_item_func: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]],
    entity_label: str,
    redirect_endpoint: str,
    scope_filter: Optional[Any] = None,
    post_save_hook: Optional[Callable[[Dict[str, int]], None]] = None,
) -> Any:
    """Standardized handler for configuration changeset POST submissions.

    Extracts changeset JSON, validates and sanitises items, performs atomic differential updates,
    executes optional post-save hooks, sets flash feedback messages, and returns a 303 redirect.

    Args:
        form_key: Name of form field containing JSON changeset payload.
        model_class: Peewee model class to update.
        clean_item_func: Callback to sanitize and validate each item dictionary.
        entity_label: Human-readable entity name for flash messages (e.g. 'Journeys').
        redirect_endpoint: Endpoint for 303 redirect after POST.
        scope_filter: Optional Peewee filter expression to constrain managed records.
        post_save_hook: Optional callback invoked after successful persistence.

    Returns:
        Flask 303 Redirect response.
    """
    try:
        changeset = parse_json_form_changeset(form_key)
        stats = apply_model_changeset(
            model_class=model_class,
            changeset=changeset,
            clean_item_func=clean_item_func,
            scope_filter=scope_filter,
        )

        if post_save_hook is not None:
            post_save_hook(stats)

        flash(f"{entity_label} saved successfully.", "success")
    except Exception as e:
        flash(f"Failed to save {entity_label.lower()}: {str(e)}", "error")

    return redirect(url_for(redirect_endpoint), code=303)


@dataclass
class PageConfig:
    """Configuration descriptor for a standard GET+POST changeset config page.

    Attributes:
        route: URL path relative to the blueprint prefix, e.g. ``'/locations'``.
        endpoint: Blueprint endpoint name, e.g. ``'locations'``.
        template: Jinja2 template name, e.g. ``'config_locations.html'``.
        form_key: Name of the form field containing the JSON changeset payload.
        model_class: Peewee model class to read from and persist to.
        clean_item_func: Callback that validates and sanitises a single raw dict
            item, returning a cleaned dict or ``None`` to skip the item.
        entity_label: Human-readable label used in flash messages, e.g. ``'Locations'``.
        get_template_context: Zero-argument callable returning the keyword
            arguments to pass to :func:`flask.render_template` on GET requests.
            The ``active_tab`` key is injected automatically.
        scope_filter: Optional Peewee boolean expression to constrain which
            records are updated or deleted (e.g. exclude auto-generated rows).
        post_save_hook: Optional callback invoked with the changeset stats dict
            after a successful save (e.g. to trigger background synchronisation).
    """

    route: str
    endpoint: str
    template: str
    form_key: str
    model_class: Type[Model]
    clean_item_func: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]
    entity_label: str
    get_template_context: Callable[[], Dict[str, Any]]
    scope_filter: Optional[Any] = field(default=None)
    post_save_hook: Optional[Callable[[Dict[str, int]], None]] = field(default=None)


def register_html_page(bp: Blueprint, cfg: PageConfig) -> None:
    """Register a standard GET+POST changeset config page on a blueprint.

    Eliminates boilerplate by building a view function from a :class:`PageConfig`
    descriptor and registering it with :meth:`flask.Blueprint.add_url_rule`.

    On **POST** the view delegates to :func:`save_changeset_config`.
    On **GET** the view calls ``cfg.get_template_context()`` and passes the
    result (plus ``active_tab``) to :func:`flask.render_template`.

    Args:
        bp: The Flask :class:`~flask.Blueprint` to register the route on.
        cfg: A :class:`PageConfig` instance describing the page.
    """

    def _view() -> Any:
        if request.method == "POST":
            return save_changeset_config(
                form_key=cfg.form_key,
                model_class=cfg.model_class,
                clean_item_func=cfg.clean_item_func,
                entity_label=cfg.entity_label,
                redirect_endpoint=f"{bp.name}.{cfg.endpoint}",
                scope_filter=cfg.scope_filter,
                post_save_hook=cfg.post_save_hook,
            )
        context = cfg.get_template_context()
        context["active_tab"] = cfg.endpoint
        return render_template(cfg.template, **context)

    _view.__name__ = cfg.endpoint
    bp.add_url_rule(
        cfg.route,
        endpoint=cfg.endpoint,
        view_func=_view,
        methods=["GET", "POST"],
    )
