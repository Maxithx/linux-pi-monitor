from __future__ import annotations

import json
import time
from functools import wraps
from typing import Any, Dict

from flask import Response, jsonify, request

from . import terminal_bp
from . import commands_store

MAX_TITLE = 64
MAX_COMMAND = 2048
MAX_DESCRIPTION = 512

_RATE_BUCKETS: Dict[str, list] = {}


def _rate_limited(action: str, limit: int = 10, window: int = 5):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            ident = f"{action}:{request.remote_addr or 'anon'}"
            now = time.time()
            bucket = _RATE_BUCKETS.setdefault(ident, [])
            bucket[:] = [ts for ts in bucket if now - ts < window]
            if len(bucket) >= limit:
                return jsonify({"ok": False, "error": "Too many requests, slow down."}), 429
            bucket.append(now)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def _clean_name(value: Any, field: str = "name") -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{field.capitalize()} is required")
    if len(text) > MAX_TITLE:
        raise ValueError(f"{field.capitalize()} must be at most {MAX_TITLE} characters")
    return text


def _clean_command(value: Any) -> str:
    if value is None:
        raise ValueError("Command is required")
    text = str(value).replace("\r", "").strip()
    if not text:
        raise ValueError("Command is required")
    if len(text) > MAX_COMMAND:
        raise ValueError("Command is too long")
    if text.count("\n") > 20:
        raise ValueError("Command contains too many lines")
    return text


def _clean_description(value: Any) -> str:
    text = (value or "").strip()
    if len(text) > MAX_DESCRIPTION:
        raise ValueError("Description is too long")
    return text


@terminal_bp.get("/terminal/collections")
def list_collections():
    data = commands_store.snapshot()
    return jsonify({"ok": True, "data": data})


@terminal_bp.post("/terminal/collections")
@_rate_limited("collections:create")
def create_collection():
    body = request.get_json(silent=True) or {}
    try:
        name = _clean_name(body.get("name"))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    result = commands_store.create_collection(name, icon=body.get("icon"))
    return jsonify({"ok": True, "collection": result["collection"], "profile_id": result["profile_id"]})


@terminal_bp.patch("/terminal/collections/<col_id>")
@_rate_limited("collections:update")
def update_collection(col_id: str):
    body = request.get_json(silent=True) or {}
    try:
        name = _clean_name(body.get("name"))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    result = commands_store.rename_collection(col_id, name, icon=body.get("icon"))
    if not result:
        return jsonify({"ok": False, "error": "Collection not found"}), 404
    return jsonify({"ok": True, "collection": result["collection"], "profile_id": result["profile_id"]})


@terminal_bp.delete("/terminal/collections/<col_id>")
@_rate_limited("collections:delete")
def delete_collection(col_id: str):
    ok, payload = commands_store.delete_collection(col_id)
    if not ok:
        if payload and "error" in payload:
            return jsonify({"ok": False, "error": payload["error"]}), 400
        return jsonify({"ok": False, "error": "Collection not found"}), 404
    return jsonify({"ok": True, "profile_id": payload["profile_id"], "moved_to": payload["moved_to"]})


@terminal_bp.post("/terminal/collections/reorder")
@_rate_limited("collections:reorder")
def reorder_collections():
    body = request.get_json(silent=True) or {}
    order = body.get("order")
    if not isinstance(order, list):
        return jsonify({"ok": False, "error": "order must be a list"}), 400
    result = commands_store.reorder_collections([str(x) for x in order if isinstance(x, str) or isinstance(x, int)])
    return jsonify({"ok": True, "profile_id": result["profile_id"]})


@terminal_bp.post("/terminal/commands")
@_rate_limited("commands:create")
def create_command():
    body = request.get_json(silent=True) or {}
    try:
        title = _clean_name(body.get("title"), field="title")
        command = _clean_command(body.get("command"))
        description = _clean_description(body.get("description"))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    payload = {
        "group_id": body.get("group_id"),
        "title": title,
        "command": command,
        "description": description,
        "requires_sudo": bool(body.get("requires_sudo")),
    }
    result = commands_store.create_command(payload)
    return jsonify({"ok": True, "command": result["command"], "profile_id": result["profile_id"]})


@terminal_bp.patch("/terminal/commands/<cmd_id>")
@_rate_limited("commands:update")
def update_command(cmd_id: str):
    body = request.get_json(silent=True) or {}
    payload: Dict[str, Any] = {}
    if "title" in body:
        try:
            payload["title"] = _clean_name(body.get("title"), field="title")
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
    if "command" in body:
        try:
            payload["command"] = _clean_command(body.get("command"))
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
    if "description" in body:
        try:
            payload["description"] = _clean_description(body.get("description"))
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
    if "group_id" in body:
        payload["group_id"] = body.get("group_id")
    if "requires_sudo" in body:
        payload["requires_sudo"] = bool(body.get("requires_sudo"))

    result = commands_store.update_command(cmd_id, payload)
    if not result:
        return jsonify({"ok": False, "error": "Command not found"}), 404
    return jsonify({"ok": True, "command": result["command"], "profile_id": result["profile_id"]})


@terminal_bp.delete("/terminal/commands/<cmd_id>")
@_rate_limited("commands:delete")
def delete_command(cmd_id: str):
    if not commands_store.delete_command(cmd_id):
        return jsonify({"ok": False, "error": "Command not found"}), 404
    return jsonify({"ok": True})


@terminal_bp.post("/terminal/commands/reorder")
@_rate_limited("commands:reorder")
def reorder_commands():
    body = request.get_json(silent=True) or {}
    group_id = (body.get("group_id") or "").strip()
    order = body.get("order")
    if not group_id:
        return jsonify({"ok": False, "error": "group_id required"}), 400
    if not isinstance(order, list):
        return jsonify({"ok": False, "error": "order must be a list"}), 400
    result = commands_store.reorder_commands(group_id, [str(x) for x in order if isinstance(x, str)])
    return jsonify({"ok": True, "profile_id": result["profile_id"]})


@terminal_bp.get("/terminal/collections/export")
def export_collections():
    payload = commands_store.export_payload()
    json_blob = json.dumps(payload, indent=2)
    filename = f"terminal-commands-{payload.get('profile_id', 'profile')}.json"
    response = Response(json_blob, mimetype="application/json")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@terminal_bp.post("/terminal/collections/import")
@_rate_limited("collections:import", limit=4, window=30)
def import_collections():
    if "file" in request.files:
        raw = request.files["file"].read()
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return jsonify({"ok": False, "error": "Invalid JSON file"}), 400
    else:
        payload = request.get_json(silent=True) or {}
    try:
        result = commands_store.import_payload(payload)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "profile_id": result["profile_id"], "summary": result})

