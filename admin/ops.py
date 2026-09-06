"""Ops API: owner-facing reads/writes over CRM + learning pieces.

Mount from the main app::

    from admin.ops import router as ops_router
    app.include_router(ops_router)

Backed by crm.py / learning.py when those modules exist; otherwise it
degrades gracefully to ConversationStore (contacts/stages) and empty
lists (reminders/lessons), so the router always imports and serves.
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/ops", tags=["ops"])


class DealMove(BaseModel):
    contact_id: str
    stage: str
    deal_id: Optional[str] = None


def _db_path() -> str:
    return os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "conversations.db"))


def _store():  # lazy import keeps this router import-safe
    from memory import ConversationStore

    return ConversationStore(db_path=_db_path())


def _optional_module(name: str) -> Any | None:
    try:
        return __import__(name)
    except ImportError:
        return None


def _contact_row(user_id: str, stage: str, profile: dict) -> dict:
    return {"user_id": user_id, "stage": stage, "profile": profile}


@router.get("/contacts")
def list_contacts() -> list[dict]:
    """List contacts: CRM module when present, else bot conversation users."""
    crm = _optional_module("crm")
    if crm is not None:
        for fn_name in ("list_contacts", "all_contacts", "contacts"):
            fn = getattr(crm, fn_name, None)
            if callable(fn):
                try:
                    return list(fn())
                except Exception:
                    break
    store = _store()
    try:
        cur = store._conn.execute("SELECT user_id, stage, profile FROM users ORDER BY user_id")
        import json

        out = []
        for row in cur.fetchall():
            try:
                profile = json.loads(row["profile"] or "{}")
            except (ValueError, TypeError):
                profile = {}
            out.append(_contact_row(row["user_id"], row["stage"], profile))
        return out
    finally:
        store.close()


@router.get("/contacts/{contact_id}")
def get_contact(contact_id: str) -> dict:
    """Contact detail: profile + stage + recent history + notes."""
    crm = _optional_module("crm")
    if crm is not None:
        fn = getattr(crm, "get_contact", None)
        if callable(fn):
            try:
                result = fn(contact_id)
                if result is not None:
                    return result if isinstance(result, dict) else {"contact": result}
            except Exception:
                pass
    store = _store()
    try:
        profile = store.get_profile(contact_id)
        stage = store.get_stage(contact_id)
        history = store.get_history(contact_id, limit=20)
        notes = store.get_notes(contact_id)
        if not profile and stage == "new" and not history and not notes:
            raise HTTPException(status_code=404, detail="contact not found")
        return {
            "user_id": contact_id,
            "stage": stage,
            "profile": profile,
            "history": history,
            "notes": notes,
        }
    finally:
        store.close()


@router.get("/reminders/due")
def due_reminders() -> list:
    """Due reminders: learning.py/crm.py when present, else []."""
    for mod_name in ("learning", "crm"):
        mod = _optional_module(mod_name)
        if mod is None:
            continue
        for fn_name in ("list_due_reminders", "get_due_reminders", "due_reminders"):
            fn = getattr(mod, fn_name, None)
            if callable(fn):
                try:
                    result = fn()
                    return list(result) if result else []
                except Exception:
                    break
    # Fallback: reminders table in crm.db if some other track created it.
    crm_db = os.getenv("CRM_DB_PATH", "crm.db")
    if os.path.exists(crm_db):
        try:
            conn = sqlite3.connect(crm_db)
            try:
                cur = conn.execute("SELECT * FROM reminders WHERE due = 1")
                cols = [d[0] for d in cur.description or []]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
            finally:
                conn.close()
        except sqlite3.Error:
            pass
    return []


@router.post("/deals/move")
def move_deal(body: DealMove) -> dict:
    """Move a deal/contact to a new stage (CRM when present, else store)."""
    if not body.contact_id or not body.stage:
        raise HTTPException(status_code=422, detail="contact_id and stage are required")
    crm = _optional_module("crm")
    if crm is not None:
        for fn_name in ("move_deal", "set_stage", "update_stage"):
            fn = getattr(crm, fn_name, None)
            if callable(fn):
                try:
                    result = fn(
                        body.deal_id or body.contact_id,
                        body.stage,
                    )
                    return {"ok": True, "result": result}
                except TypeError:
                    continue
                except Exception as exc:
                    raise HTTPException(status_code=500, detail=str(exc)) from exc
    store = _store()
    try:
        store.set_stage(body.contact_id, body.stage)
        store.append_note(body.contact_id, f"deal moved to stage: {body.stage}")
        return {"ok": True, "contact_id": body.contact_id, "stage": body.stage}
    finally:
        store.close()


@router.get("/lessons")
def list_lessons() -> list:
    """Learned lessons: learning.py when present, else []."""
    learning = _optional_module("learning")
    if learning is not None:
        for fn_name in ("list_lessons", "get_lessons", "lessons"):
            fn = getattr(learning, fn_name, None)
            if callable(fn):
                try:
                    result = fn()
                    return list(result) if result else []
                except Exception:
                    break
        data = getattr(learning, "LESSONS", None)
        if isinstance(data, list):
            return data
    return []
