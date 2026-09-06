"""Admin panel API: CRUD over the BusinessKB JSON file + hot-reload hook.

Mount from the main app::

    from admin.panel import router
    app.include_router(router)

Auth: if ADMIN_TOKEN env is set, requests must carry
``Authorization: Bearer <token>``. Empty token = open (dev only).
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Callable hot-reload hooks registered by the knowledge layer, e.g.
# knowledge.register_reload_hook(fn). Called after every successful write.
_reload_hooks: list[Callable[[dict], None]] = []


def register_reload_hook(fn: Callable[[dict], None]) -> None:
    _reload_hooks.append(fn)


def _kb_path() -> Path:
    return Path(os.getenv("KB_PATH", "data/business.json"))


def _seed_path() -> Path:
    return Path(os.getenv("SEED_KB_PATH", "data/seed_business.json"))


def _check_auth(authorization: str | None) -> None:
    token = os.getenv("ADMIN_TOKEN", "")
    if not token:
        return
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="unauthorized")


def _load_kb() -> dict:
    path = _kb_path()
    if not path.exists():
        seed = _seed_path()
        if seed.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(seed, path)
        else:
            raise HTTPException(status_code=404, detail="KB file not found and no seed available")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"KB file is corrupt: {exc}") from exc


def _save_kb(kb: dict) -> dict:
    path = _kb_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(kb, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    for hook in _reload_hooks:
        try:
            hook(kb)
        except Exception:
            pass
    # Best-effort hook into the core knowledge module if it exposes reload().
    try:
        import importlib

        for mod_name in ("core.knowledge", "knowledge", "app.knowledge"):
            try:
                mod = importlib.import_module(mod_name)
                reload_fn = getattr(mod, "reload_kb", getattr(mod, "reload", None))
                if callable(reload_fn):
                    try:
                        reload_fn(kb)
                    except TypeError:
                        reload_fn()
                    break
            except ImportError:
                continue
    except Exception:
        pass
    return kb


class KBUpdate(BaseModel):
    kb: dict[str, Any]


class ItemIn(BaseModel):
    item: dict[str, Any]


SECTION_KEYS = ("services", "faqs", "sales_scenarios", "objection_handlers")


def _section(kb: dict, name: str) -> list:
    if name not in SECTION_KEYS and name not in ("scenarios",):
        raise HTTPException(status_code=404, detail=f"unknown section: {name}")
    key = "sales_scenarios" if name == "scenarios" else name
    items = kb.get(key, [])
    if not isinstance(items, list):
        raise HTTPException(status_code=500, detail=f"section '{key}' is not a list")
    return items


def _find(items: list, item_id: str) -> int:
    for i, it in enumerate(items):
        if isinstance(it, dict) and str(it.get("id")) == str(item_id):
            return i
    return -1


@router.get("/kb")
def get_kb(authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    return _load_kb()


@router.put("/kb")
def put_kb(body: KBUpdate, authorization: str | None = Header(default=None)):
    _check_auth(authorization)
    if not isinstance(body.kb, dict):
        raise HTTPException(status_code=422, detail="kb must be an object")
    return _save_kb(body.kb)


@router.post("/reload")
def hot_reload(authorization: str | None = Header(default=None)):
    """Hot-reload hook: re-read KB from disk and notify listeners."""
    _check_auth(authorization)
    kb = _load_kb()
    for hook in _reload_hooks:
        try:
            hook(kb)
        except Exception:
            pass
    return {"ok": True, "reloaded_at": datetime.now(timezone.utc).isoformat()}
def _crud(section: str, authorization: str | None, item_id: str | None = None,
           item: dict | None = None, method: str = "get") -> Any:
    _check_auth(authorization)
    kb = _load_kb()
    key = "sales_scenarios" if section == "scenarios" else section
    items = _section(kb, section)
    if method == "get_list":
        return items
    if method == "post":
        assert item is not None
        if not item.get("id"):
            item["id"] = f"{key}-{len(items) + 1}"
        if _find(items, item["id"]) >= 0:
            raise HTTPException(status_code=409, detail="id already exists")
        items.append(item)
        kb[key] = items
        _save_kb(kb)
        return item
    assert item_id is not None
    idx = _find(items, item_id)
    if idx < 0:
        raise HTTPException(status_code=404, detail="not found")
    if method == "put":
        assert item is not None
        item["id"] = str(item_id)
        items[idx] = item
        kb[key] = items
        _save_kb(kb)
        return item
    if method == "delete":
        removed = items.pop(idx)
        kb[key] = items
        _save_kb(kb)
        return {"ok": True, "removed": removed}
    raise AssertionError("bad method")


def _section_routes(section: str, alias: str | None = None):
    """Register GET/POST/PUT/DELETE for one section (plus alias)."""
    names = [section] if not alias else [section, alias]

    for name in names:
        @router.get(f"/{name}", name=f"list_{name}")
        def list_items(authorization: str | None = Header(default=None), _s=section):
            return _crud(_s, authorization, method="get_list")

        @router.post(f"/{name}", name=f"create_{name}")
        def create_item(body: ItemIn, authorization: str | None = Header(default=None), _s=section):
            return _crud(_s, authorization, item=dict(body.item), method="post")

        @router.put(f"/{name}" + "/{item_id}", name=f"update_{name}")
        def update_item(item_id: str, body: ItemIn,
                        authorization: str | None = Header(default=None), _s=section):
            return _crud(_s, authorization, item_id=item_id, item=dict(body.item), method="put")

        @router.delete(f"/{name}" + "/{item_id}", name=f"delete_{name}")
        def delete_item(item_id: str, authorization: str | None = Header(default=None), _s=section):
            return _crud(_s, authorization, item_id=item_id, method="delete")


_section_routes("services")
_section_routes("faqs")
_section_routes("sales_scenarios", alias="scenarios")
_section_routes("objection_handlers", alias="objections")
