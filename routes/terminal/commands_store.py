from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, List, Tuple

from flask import current_app

from routes.settings import profiles_data

DEFAULT_COLLECTION_NAMES = (
    "System",
    "Network",
    "Disk",
    "Security/UFW",
    "Docker",
    "Glances",
    "Uncategorized",
)


def _store_path() -> str:
    path = current_app.config.get("TERMINAL_COMMANDS_PATH")
    if not path:
        raise RuntimeError("TERMINAL_COMMANDS_PATH is not configured")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _ensure_store() -> Dict[str, Any]:
    path = _store_path()
    if not os.path.exists(path):
        data = {"version": 1, "profiles": {}}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        return data
    with open(path, "r", encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError:
            fh.seek(0)
            raw = fh.read()
            raise RuntimeError(f"Corrupted terminal command store: {path}\n{raw[:200]}")


def _write_store(data: Dict[str, Any]) -> None:
    path = _store_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _ensure_section(data: Dict[str, Any], profile_id: str) -> Dict[str, Any]:
    profiles = data.setdefault("profiles", {})
    section = profiles.setdefault(profile_id, {})
    section.setdefault("collections", [])
    section.setdefault("commands", [])
    section.setdefault("meta", {})
    return section


def _ensure_seed_collections(section: Dict[str, Any]) -> bool:
    if section["collections"]:
        # Always guarantee an Uncategorized bucket exists
        if not any(c.get("name", "").strip().lower() == "uncategorized" for c in section["collections"]):
            section["collections"].append(_collection_obj("Uncategorized", _next_sort(section["collections"])))
            return True
        return False

    sort = 1000
    for name in DEFAULT_COLLECTION_NAMES:
        section["collections"].append(_collection_obj(name, sort))
        sort += 1000
    section["meta"]["seeded_at"] = int(time.time())
    return True


def _collection_obj(name: str, sort_order: int) -> Dict[str, Any]:
    return {
        "id": _new_id("col"),
        "name": name,
        "icon": None,
        "sort_order": sort_order,
        "created_at": int(time.time()),
    }


def _command_obj(
    group_id: str,
    title: str,
    command: str,
    description: str = "",
    requires_sudo: bool = False,
    sort_order: int = 0,
) -> Dict[str, Any]:
    now = int(time.time())
    return {
        "id": _new_id("cmd"),
        "group_id": group_id,
        "title": title,
        "command": command,
        "description": description,
        "requires_sudo": requires_sudo,
        "sort_order": sort_order,
        "created_at": now,
        "updated_at": now,
    }


def _next_sort(items: List[Dict[str, Any]]) -> int:
    return (max((item.get("sort_order") or 0) for item in items) if items else 0) + 1000


def _active_profile_id() -> str:
    data = profiles_data._ensure_store()
    pid = data.get("active_profile_id")
    if not pid:
        raise RuntimeError("No active profile selected")
    return pid


def get_state(profile_id: str | None = None) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    data = _ensure_store()
    pid = profile_id or _active_profile_id()
    section = _ensure_section(data, pid)
    changed = _ensure_seed_collections(section)
    if changed:
        _write_store(data)
    return data, section, pid


def snapshot(profile_id: str | None = None) -> Dict[str, Any]:
    _, section, pid = get_state(profile_id)
    collections = [
        dict(col)
        for col in sorted(section["collections"], key=lambda c: (c.get("sort_order") or 0, c.get("created_at") or 0))
    ]
    commands = [
        dict(cmd)
        for cmd in sorted(section["commands"], key=lambda c: (c.get("sort_order") or 0, c.get("created_at") or 0))
    ]
    return {"profile_id": pid, "collections": collections, "commands": commands}


def ensure_uncategorized(section: Dict[str, Any]) -> Dict[str, Any]:
    for col in section["collections"]:
        if (col.get("name") or "").strip().lower() == "uncategorized":
            return col
    new_col = _collection_obj("Uncategorized", _next_sort(section["collections"]))
    section["collections"].append(new_col)
    return new_col


def create_collection(name: str, icon: str | None = None) -> Dict[str, Any]:
    data, section, pid = get_state()
    col = _collection_obj(name, _next_sort(section["collections"]))
    col["icon"] = icon
    section["collections"].append(col)
    _write_store(data)
    return {"profile_id": pid, "collection": col}


def rename_collection(col_id: str, new_name: str, icon: str | None = None) -> Dict[str, Any] | None:
    data, section, pid = get_state()
    for col in section["collections"]:
        if col["id"] == col_id:
            col["name"] = new_name
            if icon is not None:
                col["icon"] = icon
            _write_store(data)
            return {"profile_id": pid, "collection": col}
    return None


def delete_collection(col_id: str) -> Tuple[bool, Dict[str, Any] | None]:
    data, section, pid = get_state()
    uncategorized = ensure_uncategorized(section)
    if col_id == uncategorized["id"]:
        return False, {"error": "Cannot delete the Uncategorized collection"}

    collections = section["collections"]
    target = next((c for c in collections if c["id"] == col_id), None)
    if not target:
        return False, None

    section["collections"] = [c for c in collections if c["id"] != col_id]
    for cmd in section["commands"]:
        if cmd.get("group_id") == col_id:
            cmd["group_id"] = uncategorized["id"]
            cmd["updated_at"] = int(time.time())
    _write_store(data)
    return True, {"profile_id": pid, "collection": target, "moved_to": uncategorized["id"]}


def reorder_collections(order: List[str]) -> Dict[str, Any]:
    data, section, pid = get_state()
    id_to_col = {c["id"]: c for c in section["collections"]}
    sort = 1000
    for cid in order:
        col = id_to_col.get(cid)
        if not col:
            continue
        col["sort_order"] = sort
        sort += 1000
    _write_store(data)
    return {"profile_id": pid, "collections": section["collections"]}


def create_command(payload: Dict[str, Any]) -> Dict[str, Any]:
    data, section, pid = get_state()
    group_id = payload.get("group_id")
    if not any(c["id"] == group_id for c in section["collections"]):
        group_id = ensure_uncategorized(section)["id"]
    cmd = _command_obj(
        group_id=group_id,
        title=payload.get("title") or "",
        command=payload.get("command") or "",
        description=payload.get("description") or "",
        requires_sudo=bool(payload.get("requires_sudo")),
        sort_order=_next_sort([c for c in section["commands"] if c.get("group_id") == group_id]),
    )
    section["commands"].append(cmd)
    _write_store(data)
    return {"profile_id": pid, "command": cmd}


def update_command(cmd_id: str, payload: Dict[str, Any]) -> Dict[str, Any] | None:
    data, section, pid = get_state()
    cmd = next((c for c in section["commands"] if c["id"] == cmd_id), None)
    if not cmd:
        return None

    if "group_id" in payload:
        group_id = payload.get("group_id")
        if not any(c["id"] == group_id for c in section["collections"]):
            group_id = ensure_uncategorized(section)["id"]
        if group_id != cmd["group_id"]:
            cmd["group_id"] = group_id
            cmd["sort_order"] = _next_sort([c for c in section["commands"] if c.get("group_id") == group_id])

    for key in ("title", "command", "description"):
        if key in payload:
            cmd[key] = payload.get(key) or ""

    if "requires_sudo" in payload:
        cmd["requires_sudo"] = bool(payload.get("requires_sudo"))

    cmd["updated_at"] = int(time.time())
    _write_store(data)
    return {"profile_id": pid, "command": cmd}


def delete_command(cmd_id: str) -> bool:
    data, section, _ = get_state()
    before = len(section["commands"])
    section["commands"] = [c for c in section["commands"] if c["id"] != cmd_id]
    if len(section["commands"]) == before:
        return False
    _write_store(data)
    return True


def reorder_commands(group_id: str, order: List[str]) -> Dict[str, Any]:
    data, section, pid = get_state()
    group_cmds = [c for c in section["commands"] if c.get("group_id") == group_id]
    id_to_cmd = {c["id"]: c for c in group_cmds}
    sort = 1000
    for cmd_id in order:
        c = id_to_cmd.get(cmd_id)
        if not c:
            continue
        c["sort_order"] = sort
        sort += 1000
    _write_store(data)
    return {"profile_id": pid, "commands": group_cmds}


def export_payload(profile_id: str | None = None) -> Dict[str, Any]:
    snap = snapshot(profile_id)
    lookup = {c["id"]: c.get("name", "") for c in snap["collections"]}
    commands = []
    for cmd in snap["commands"]:
        item = dict(cmd)
        item["collection_name"] = lookup.get(item.get("group_id"), "")
        commands.append(item)
    return {
        "version": 1,
        "profile_id": snap["profile_id"],
        "collections": snap["collections"],
        "commands": commands,
        "generated_at": int(time.time()),
    }


def import_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    data, section, pid = get_state()
    existing_names = {c["name"].strip().lower(): c for c in section["collections"]}
    imported = payload or {}
    new_collections = []
    added_cmds = 0
    mapped_ids: Dict[str, str] = {}

    for col in imported.get("collections", []):
        name = (col.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in existing_names:
            mapped_ids[col.get("id") or key] = existing_names[key]["id"]
            continue
        obj = _collection_obj(name, _next_sort(section["collections"]))
        obj["icon"] = col.get("icon")
        section["collections"].append(obj)
        existing_names[key] = obj
        mapped_ids[col.get("id") or key] = obj["id"]
        new_collections.append(obj)

    uncategorized = ensure_uncategorized(section)
    commands = imported.get("commands", [])

    def _dedupe_title(group_id: str, title: str, command_text: str) -> str:
        base = title or "(untitled)"
        normalized = base
        counter = 2
        existing = [
            (c.get("title") or "").strip()
            for c in section["commands"]
            if c.get("group_id") == group_id and (c.get("command") or "").strip() == command_text.strip()
        ]
        while normalized in existing:
            normalized = f"{base} ({counter})"
            counter += 1
        return normalized

    for cmd in commands:
        title = (cmd.get("title") or "").strip()
        command_text = (cmd.get("command") or "").strip()
        if not command_text:
            continue
        group_id = cmd.get("group_id")
        mapped_gid = mapped_ids.get(group_id) if group_id else None
        if not mapped_gid:
            name = (cmd.get("collection_name") or "").strip().lower()
            mapped_gid = existing_names.get(name, {}).get("id")
        if not mapped_gid:
            mapped_gid = uncategorized["id"]
        clean_title = _dedupe_title(mapped_gid, title or "Imported command", command_text)
        new_cmd = _command_obj(
            group_id=mapped_gid,
            title=clean_title,
            command=command_text,
            description=cmd.get("description") or "",
            requires_sudo=bool(cmd.get("requires_sudo")),
            sort_order=_next_sort([c for c in section["commands"] if c.get("group_id") == mapped_gid]),
        )
        section["commands"].append(new_cmd)
        added_cmds += 1

    _write_store(data)
    return {
        "profile_id": pid,
        "added_collections": len(new_collections),
        "added_commands": added_cmds,
    }
