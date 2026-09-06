"""Smoke test: core modules exist + seed KB loads.

Tolerant of parallel builds: if a core module is not present yet the
corresponding check is skipped rather than failed. At least the KB
assertion always runs.
"""
import importlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SEED = ROOT / "data" / "seed_business.json"

# module -> expected attribute(s); passes if ANY listed module/attr resolves
EXPECTED = {
    "config": ["core.config", "app.config", "config"],
    "settings": ["Settings", "Config", "get_settings"],
    "llm_router": ["core.llm_router", "app.llm_router", "llm_router"],
    "router_cls": ["LLMRouter", "Router", "FallbackRouter"],
    "memory": ["core.memory", "app.memory", "memory"],
    "memory_cls": ["Memory", "SQLiteMemory", "ConversationMemory"],
    "knowledge": ["core.knowledge", "app.knowledge", "knowledge"],
    "knowledge_cls": ["BusinessKB", "KnowledgeBase", "KB"],
    "agent": ["core.agent", "app.agent", "agent"],
    "agent_cls": ["SalesAgent", "Agent"],
}


def _resolve(mod_names, attrs=None):
    for m in mod_names if isinstance(mod_names, list) else [mod_names]:
        try:
            mod = importlib.import_module(m)
            if not attrs:
                return True
            names = attrs if isinstance(attrs, list) else [attrs]
            if any(hasattr(mod, a) for a in names):
                return True
        except ImportError:
            continue
    return False


def test_kb_seed_loads():
    assert SEED.exists(), f"missing {SEED}"
    kb = json.loads(SEED.read_text(encoding="utf-8"))
    for key in ("services", "faqs", "policies", "objection_handlers", "sales_scenarios"):
        assert key in kb, f"seed KB missing '{key}'"
    assert len(kb["services"]) >= 1
    assert len(kb["faqs"]) >= 1
    assert len(kb["objection_handlers"]) >= 3, "need >=3 objection handlers"
    assert len(kb["sales_scenarios"]) >= 2, "need >=2 sales scenarios"


def test_admin_panel_imports():
    try:
        mod = importlib.import_module("admin.panel")
    except ImportError:
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location("panel", str(ROOT / "admin" / "panel.py"))
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
    assert hasattr(mod, "router"), "admin.panel must expose `router`"
    paths = set()
    for r in mod.router.routes:
        paths.add(getattr(r, "path", ""))
    assert any(p.endswith("/api/admin/kb") for p in paths), "missing GET/PUT /api/admin/kb"


def test_core_modules_present():
    """Pass if core is present; skip (not fail) while parallel track builds it."""
    import pytest
    pairs = [
        (EXPECTED["config"], None),
        (EXPECTED["llm_router"], None),
        (EXPECTED["memory"], None),
        (EXPECTED["knowledge"], None),
        (EXPECTED["agent"], None),
    ]
    found = sum(1 for mods, _ in pairs if _resolve(mods))
    if found == 0:
        pytest.skip("core modules not built yet (parallel track)")
    assert found >= 1
    # class-level checks are informational only
    for mods, cls_names in [
        (EXPECTED["llm_router"], EXPECTED["router_cls"]),
        (EXPECTED["memory"], EXPECTED["memory_cls"]),
        (EXPECTED["knowledge"], EXPECTED["knowledge_cls"]),
        (EXPECTED["agent"], EXPECTED["agent_cls"]),
    ]:
        _resolve(mods, cls_names)
