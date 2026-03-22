"""Workspace resolver for multi-KB support.

Workspaces are isolated knowledge-base directories under workspaces/<kb_id>/.
Each workspace contains:
    kb.yaml               -- workspace metadata and config
    knowledge_tree.json   -- local knowledge tree (gitignored)
    interviews/           -- interview records (gitignored)
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

DEFAULT_KB_ID = "default"
_WORKSPACES_DIR = "workspaces"


def get_workspace_dir(project_root: Path, kb_id: str) -> Path:
    """Return the workspace directory path for *kb_id*."""
    return project_root / _WORKSPACES_DIR / kb_id


def load_kb_config(project_root: Path, kb_id: str) -> dict:
    """Load and return kb.yaml for the given workspace."""
    ws_dir = get_workspace_dir(project_root, kb_id)
    config_path = ws_dir / "kb.yaml"
    if not config_path.exists():
        raise FileNotFoundError(
            f"Workspace '{kb_id}' not found: {config_path}\n"
            f"  To migrate from legacy layout: python tools/migrate_legacy.py\n"
            f"  To create a new workspace:     workspaces/{kb_id}/kb.yaml"
        )
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_tree_path(project_root: Path, kb_id: str) -> Path:
    """Return path to knowledge_tree.json for *kb_id*."""
    return get_workspace_dir(project_root, kb_id) / "knowledge_tree.json"


def get_interviews_dir(project_root: Path, kb_id: str) -> Path:
    """Return path to the interviews directory for *kb_id*."""
    return get_workspace_dir(project_root, kb_id) / "interviews"


def get_docs_dir(project_root: Path, kb_id: str) -> Path:
    """Return docs directory for this workspace.

    Reads docs_dir from kb.yaml (relative to project root).
    Falls back to project_root/docs if not specified or workspace not found.
    """
    try:
        cfg = load_kb_config(project_root, kb_id)
        docs = cfg.get("docs_dir") or "docs"
    except FileNotFoundError:
        docs = "docs"
    docs_path = Path(docs)
    if not docs_path.is_absolute():
        docs_path = project_root / docs_path
    return docs_path


def list_workspaces(project_root: Path) -> list[dict]:
    """Return config dicts for all valid workspaces, sorted by id."""
    ws_root = project_root / _WORKSPACES_DIR
    if not ws_root.exists():
        return []
    result = []
    for d in sorted(ws_root.iterdir()):
        if d.is_dir() and (d / "kb.yaml").exists():
            with open(d / "kb.yaml", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            result.append(cfg)
    return result


def get_index_path(project_root: Path, kb_id: str) -> Path:
    """Return path to the FTS5 SQLite index database for this workspace."""
    return get_workspace_dir(project_root, kb_id) / "kb_index.db"


def get_map_path(project_root: Path, kb_id: str) -> Path:
    """Return path to feishu_map.json for this workspace.

    This file records the local-node → Feishu node_token/obj_token mapping
    used by the idempotent sync logic to avoid duplicate node creation.
    """
    return get_workspace_dir(project_root, kb_id) / "feishu_map.json"


def get_papers_dir(project_root: Path, kb_id: str) -> Path:
    """Return path to the papers directory for *kb_id*.

    Each paper is stored as a JSON file: papers/<paper_id>.json.
    This directory is gitignored (personal reading notes, not source code).
    """
    return get_workspace_dir(project_root, kb_id) / "papers"


def get_graph_dir(project_root: Path, kb_id: str) -> Path:
    """Return path to the graph export directory for *kb_id*.

    Contains nodes.jsonl, edges.jsonl, and graph.json — all auto-generated,
    gitignored, and safe to delete and regenerate.
    """
    return get_workspace_dir(project_root, kb_id) / "graph"


def init_workspace(
    project_root: Path,
    kb_id: str,
    name: str = "",
    description: str = "",
) -> Path:
    """Create workspace directory structure and kb.yaml if not already present."""
    ws_dir = get_workspace_dir(project_root, kb_id)
    ws_dir.mkdir(parents=True, exist_ok=True)
    (ws_dir / "interviews").mkdir(exist_ok=True)

    config_path = ws_dir / "kb.yaml"
    if not config_path.exists():
        cfg = {
            "id": kb_id,
            "name": name or kb_id,
            "description": description,
            "docs_dir": "docs",
            "feishu_space_id": "",
            "created_at": date.today().isoformat(),
        }
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)

    return ws_dir
