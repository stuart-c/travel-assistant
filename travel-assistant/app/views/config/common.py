"""Common utility functions and shared controllers for configuration views."""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type
from flask import Blueprint, jsonify, render_template, request
from peewee import Model


def parse_json_changeset(data: Any) -> Dict[str, List[Any]]:
    """Validate and extract changeset lists from a deserialised JSON dictionary.

    Expected payload format:
    {
        "added": [ ... ],
        "updated": [ ... ],
        "deleted": [ id1, id2, ... ]
    }

    Args:
        data: Deserialised JSON object.

    Returns:
        Dictionary with 'added', 'updated', and 'deleted' lists.

    Raises:
        ValueError: If payload structure is not a dictionary or invalid.
    """
    if not isinstance(data, dict):
        raise ValueError("Changeset payload must be a JSON dictionary.")

    if not any(k in data for k in ("added", "updated", "deleted")):
        raise ValueError(
            "Changeset must contain 'added', 'updated', or 'deleted' lists."
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
            "Changeset must contain 'added', 'updated', or 'deleted' lists."
        )

    added = [item for item in added_raw if isinstance(item, dict)]
    updated = [item for item in updated_raw if isinstance(item, dict)]
    deleted = [
        item for item in deleted_raw if item is not None and str(item).strip() != ""
    ]
    return {"added": added, "updated": updated, "deleted": deleted}


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
        clean_item_func: Callback to sanitise and validate each item dictionary.
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


@dataclass
class PageConfig:
    """Configuration descriptor for a standard config page and its data API.

    Attributes:
        route: URL path relative to the blueprint prefix, e.g. ``'/locations'``.
        endpoint: Blueprint endpoint name, e.g. ``'locations'``.
        template: Jinja2 template name, e.g. ``'config_locations.html'``.
        model_class: Peewee model class to read from and persist to.
        clean_item_func: Callback that validates and sanitises a single raw dict
            item, returning a cleaned dict or ``None`` to skip the item.
        entity_label: Human-readable label used in status messages, e.g. ``'Locations'``.
        get_template_context: Zero-argument callable returning keyword arguments
            for :func:`flask.render_template` on page GET requests. The ``active_tab``
            key is injected automatically.
        get_data_items: Optional zero-argument callable returning item dicts for
            the ``GET /data`` endpoint. If omitted, queries all records from ``model_class``.
        scope_filter: Optional Peewee boolean expression to constrain which
            records are updated or deleted (e.g. exclude auto-generated rows).
        post_save_hook: Optional callback invoked with changeset stats and changeset dicts
            after a successful save (e.g. to trigger background synchronisation).
    """

    route: str
    endpoint: str
    template: str
    model_class: Type[Model]
    clean_item_func: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]
    entity_label: str
    get_template_context: Callable[[], Dict[str, Any]] = field(default=dict)
    get_data_items: Optional[Callable[[], List[Dict[str, Any]]]] = field(default=None)
    scope_filter: Optional[Any] = field(default=None)
    post_save_hook: Optional[Callable[[Dict[str, int], Dict[str, List[Any]]], None]] = (
        field(default=None)
    )


def register_config_page(bp: Blueprint, cfg: PageConfig) -> None:
    """Register an HTML config page and its associated JSON data endpoint on a blueprint.

    Registers:
    - **GET {cfg.route}**: HTML page view (methods: ``['GET']``).
    - **GET {cfg.route}/data**: Returns ``{"data": [...], "total": count}`` for Grid.js.
    - **POST {cfg.route}/data**: Persists differential changeset JSON payload, runs
      optional post-save hook, and returns status JSON.

    Args:
        bp: The Flask :class:`~flask.Blueprint` to register the routes on.
        cfg: A :class:`PageConfig` instance describing the page.
    """

    def _page_view() -> Any:
        context = cfg.get_template_context()
        context["active_tab"] = cfg.endpoint
        return render_template(cfg.template, **context)

    _page_view.__name__ = cfg.endpoint
    bp.add_url_rule(
        cfg.route,
        endpoint=cfg.endpoint,
        view_func=_page_view,
        methods=["GET"],
    )

    def _data_view() -> Any:
        if request.method == "POST":
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return (
                    jsonify({"success": False, "message": "Invalid JSON body"}),
                    400,
                )

            try:
                changeset = parse_json_changeset(payload)
                stats = apply_model_changeset(
                    model_class=cfg.model_class,
                    changeset=changeset,
                    clean_item_func=cfg.clean_item_func,
                    scope_filter=cfg.scope_filter,
                )
                if cfg.post_save_hook is not None:
                    cfg.post_save_hook(stats, changeset)

                return jsonify(
                    {
                        "success": True,
                        "message": f"{cfg.entity_label} saved successfully.",
                        "stats": stats,
                    }
                )
            except Exception as e:
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": f"Failed to save {cfg.entity_label.lower()}: {str(e)}",
                        }
                    ),
                    400,
                )

        if cfg.get_data_items is not None:
            items = cfg.get_data_items()
            return jsonify({"data": items, "total": len(items)})

        query = cfg.model_class.select()

        total = query.count()

        sort_by = request.args.get("sort_by") or request.args.get("sort")
        order = (request.args.get("order") or request.args.get("dir") or "asc").lower()

        if sort_by:
            field_attr = getattr(cfg.model_class, sort_by, None)
            if (
                field_attr is not None
                and hasattr(field_attr, "asc")
                and hasattr(field_attr, "desc")
            ):
                if order == "desc":
                    query = query.order_by(field_attr.desc())
                else:
                    query = query.order_by(field_attr.asc())

        limit = request.args.get("limit", type=int)
        offset = request.args.get("offset", default=0, type=int)
        page = request.args.get("page", type=int)
        if page is not None and "offset" not in request.args and limit and limit > 0:
            offset = page * limit

        if limit is not None and limit > 0:
            query = query.offset(offset).limit(limit)

        items = [item.to_dict() for item in query]
        return jsonify({"data": items, "total": total})

    data_endpoint = f"{cfg.endpoint}_data"
    _data_view.__name__ = data_endpoint
    bp.add_url_rule(
        f"{cfg.route}/data",
        endpoint=data_endpoint,
        view_func=_data_view,
        methods=["GET", "POST"],
    )
