"""Idempotent sync of local knowledge tree (and interviews) to Feishu wiki.

Sync modes
----------
  python sync_to_feishu.py [--kb KB_ID]                  # dry-run (default)
  python sync_to_feishu.py [--kb KB_ID] --apply          # execute sync
  python sync_to_feishu.py [--kb KB_ID] --recover        # scan remote → populate map (dry-run)
  python sync_to_feishu.py [--kb KB_ID] --recover --apply  # persist recovered map
  python sync_to_feishu.py [--kb KB_ID] --interviews [--apply]  # also sync interview pages

Idempotency guarantee
---------------------
  feishu_map.json records every local node path → (node_token, obj_token, content_hash).
  On each run the script computes a diff and only creates/updates nodes whose state has
  changed.  Running the same command twice is safe — the second run is a no-op.

No model API calls are made at any point.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import config, feishu, retrieval, workspace  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RATE_LIMIT_SLEEP = 0.35   # seconds between consecutive API calls
RETRY_DELAYS = [1.0, 2.0, 4.0]  # exponential back-off delays (seconds)

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _retry(fn, *args, **kwargs):
    """Call fn(*args, **kwargs) with up to len(RETRY_DELAYS) retries."""
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            return fn(*args, **kwargs)
        except RuntimeError as exc:
            if attempt == len(RETRY_DELAYS):
                raise
            delay = RETRY_DELAYS[attempt]
            logger.warning("attempt %d failed: %s — retrying in %.0fs…", attempt + 1, exc, delay)
            time.sleep(delay)


# ---------------------------------------------------------------------------
# Mapping file  (workspaces/<kb_id>/feishu_map.json)
# ---------------------------------------------------------------------------


def load_map(map_path: Path) -> dict:
    """Load feishu_map.json, returning an empty skeleton if absent."""
    if map_path.exists():
        try:
            return json.loads(map_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("feishu_map.json is corrupt — starting fresh")
    return {"version": 1, "nodes": {}, "interviews": {}}


def save_map(map_path: Path, mapping: dict) -> None:
    mapping["updated_at"] = _now()
    map_path.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Tree traversal
# ---------------------------------------------------------------------------


def _walk_tree(
    node: dict, parent_path: str = "", parent_token: str = ""
) -> list[tuple[str, str, str, dict]]:
    """Recursively walk the knowledge tree.

    Yields (kb_path, parent_kb_path, parent_token, node) tuples in pre-order,
    so parents always appear before their children.
    """
    title = node.get("title", "")
    kb_path = f"{parent_path} > {title}" if parent_path else title
    own_token = node.get("node_token", "")
    result: list[tuple[str, str, str, dict]] = [(kb_path, parent_path, parent_token, node)]
    for child in node.get("children", []):
        result.extend(_walk_tree(child, kb_path, own_token))
    return result


# ---------------------------------------------------------------------------
# Content rendering  (no external API calls)
# ---------------------------------------------------------------------------


def render_node_content(node: dict, kb_path: str, index_path: Path) -> str:
    """Render plain-text body content for a KB node.

    Includes: node summary, typed memories (with labels, confidence, sources).
    Returns empty string if the node has no meaningful content.
    """
    parts: list[str] = []

    summary = (node.get("summary") or "").strip()
    if summary:
        parts.append(f"【摘要】\n{summary}")

    if index_path.exists():
        try:
            conn = retrieval.open_db(index_path)
            memories = retrieval.list_memories_for_node(conn, kb_path)
            conn.close()
            if memories:
                lines: list[str] = []
                for m in memories:
                    label = retrieval._TYPE_LABELS.get(m.get("type", "fact"), m.get("type", ""))
                    line = f"[{label}] {m['content']}"
                    conf = m.get("confidence", "medium")
                    if conf != "medium":
                        line += f"  ({conf})"
                    refs: list[str] = m.get("source_refs") or []
                    if refs:
                        line += "\n    来源: " + ", ".join(refs)
                    lines.append(line)
                parts.append("【知识要点】\n" + "\n".join(lines))
        except Exception as exc:
            logger.debug("could not load memories for %s: %s", kb_path, exc)

    return "\n\n".join(parts)


def render_interview_content(interview: dict) -> str:
    """Render plain-text body for an interview record."""
    lines = [
        f"公司: {interview.get('company', '')}",
        f"日期: {interview.get('date', '')}",
        f"类型: {interview.get('type', '')}",
        "",
    ]
    for i, q in enumerate(interview.get("questions", []), 1):
        category = q.get("category", "")
        lines.append(f"Q{i}. [{category}] {q.get('question', '')}")
        if q.get("answer"):
            lines.append(f"A: {q['answer']}")
        if q.get("kb_path"):
            lines.append(f"知识点: {' > '.join(q['kb_path'])}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Diff computation
# ---------------------------------------------------------------------------


@dataclass
class SyncAction:
    action: str          # "create" | "update_content" | "skip"
    kb_path: str
    title: str
    node: dict
    parent_kb_path: str
    node_token: str = ""
    obj_token: str = ""
    content: str = ""
    content_hash: str = ""
    reason: str = ""


def build_diff(tree: dict, mapping: dict, index_path: Path) -> list[SyncAction]:
    """Compare local tree against feishu_map.json and produce a SyncAction list.

    Decision rules per node
    -----------------------
    1. Node in map AND content_hash unchanged  → skip
    2. Node in map AND content_hash changed    → update_content
    3. Node not in map but has node_token      → treat as recovered → update_content
    4. Node not in map, no token               → create
    """
    nodes_map: dict[str, dict] = mapping.get("nodes", {})
    actions: list[SyncAction] = []

    for kb_path, parent_path, _parent_token, node in _walk_tree(tree):
        content = render_node_content(node, kb_path, index_path)
        content_hash = _sha256(content)

        if kb_path in nodes_map:
            entry = nodes_map[kb_path]
            if entry.get("content_hash") == content_hash:
                actions.append(
                    SyncAction(
                        action="skip",
                        kb_path=kb_path,
                        title=node.get("title", ""),
                        node=node,
                        parent_kb_path=parent_path,
                        node_token=entry.get("node_token", ""),
                        obj_token=entry.get("obj_token", ""),
                        content=content,
                        content_hash=content_hash,
                        reason="mapped, content unchanged",
                    )
                )
            else:
                actions.append(
                    SyncAction(
                        action="update_content",
                        kb_path=kb_path,
                        title=node.get("title", ""),
                        node=node,
                        parent_kb_path=parent_path,
                        node_token=entry.get("node_token", ""),
                        obj_token=entry.get("obj_token", ""),
                        content=content,
                        content_hash=content_hash,
                        reason="mapped, content changed",
                    )
                )
        else:
            # Node not in map — check if the tree node already has tokens
            node_token = node.get("node_token", "")
            obj_token = node.get("obj_token", "")
            if node_token:
                actions.append(
                    SyncAction(
                        action="update_content",
                        kb_path=kb_path,
                        title=node.get("title", ""),
                        node=node,
                        parent_kb_path=parent_path,
                        node_token=node_token,
                        obj_token=obj_token,
                        content=content,
                        content_hash=content_hash,
                        reason="recovered from tree tokens",
                    )
                )
            else:
                actions.append(
                    SyncAction(
                        action="create",
                        kb_path=kb_path,
                        title=node.get("title", ""),
                        node=node,
                        parent_kb_path=parent_path,
                        content=content,
                        content_hash=content_hash,
                        reason="new node",
                    )
                )

    return actions


# ---------------------------------------------------------------------------
# Remote recovery
# ---------------------------------------------------------------------------


def recover_remote(tree: dict, mapping: dict) -> int:
    """BFS-scan the remote Feishu space and match nodes by title path.

    Populates *mapping["nodes"]* with recovered entries in-place.
    Returns the number of newly recovered nodes.

    Recovery works by building a remote title-path → node dict index, then
    matching each local kb_path against it.  Title paths that don't match are
    left as "create" in the diff.
    """
    logger.info("scanning remote Feishu space for existing nodes…")
    remote_index: dict[str, dict] = {}
    queue: list[tuple[str, str]] = [("", "")]  # (parent_token, path_prefix)

    while queue:
        parent_token, path_prefix = queue.pop(0)
        try:
            nodes = feishu.list_nodes_all(parent_token)
        except RuntimeError as exc:
            logger.error("list_nodes_all failed (parent=%s): %s", parent_token, exc)
            break
        for n in nodes:
            full_path = f"{path_prefix} > {n['title']}" if path_prefix else n["title"]
            remote_index[full_path] = n
            if n.get("has_child"):
                queue.append((n["node_token"], full_path))
        time.sleep(RATE_LIMIT_SLEEP)

    nodes_map: dict[str, Any] = mapping.setdefault("nodes", {})
    recovered = 0

    for kb_path, _parent_path, _parent_token, node in _walk_tree(tree):
        if kb_path in nodes_map:
            continue
        if kb_path not in remote_index:
            continue
        remote = remote_index[kb_path]
        nodes_map[kb_path] = {
            "node_token": remote["node_token"],
            "obj_token": remote["obj_token"],
            "title": node.get("title", ""),
            "synced_at": _now(),
            "content_hash": "",  # force content write on next apply
        }
        # Backfill tokens into the tree node so tree is kept consistent
        node["node_token"] = remote["node_token"]
        node["obj_token"] = remote["obj_token"]
        recovered += 1
        logger.info("  recovered: %s", kb_path)

    return recovered


# ---------------------------------------------------------------------------
# Content write helper
# ---------------------------------------------------------------------------


def _write_content(obj_token: str, content: str) -> bool:
    """Write rendered content to a Feishu document (best-effort)."""
    if not content.strip():
        return True
    paragraphs = [line for line in content.splitlines() if line.strip()]
    if not paragraphs:
        return True
    try:
        return feishu.replace_doc_content(obj_token, paragraphs)
    except Exception as exc:
        logger.error("content write failed (obj=%s): %s", obj_token, exc)
        return False


# ---------------------------------------------------------------------------
# Sync report
# ---------------------------------------------------------------------------


@dataclass
class SyncReport:
    created: int = 0
    content_updated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: str = field(default_factory=_now)
    finished_at: str = ""


def print_report(report: SyncReport, kb_id: str, dry_run: bool) -> None:
    mode = "DRY-RUN" if dry_run else "APPLIED"
    print()
    print(f"Sync Report [{mode}]  kb={kb_id}  {report.finished_at or _now()}")
    print("━" * 56)
    if dry_run:
        print(f"  would create       : {report.created}")
        print(f"  would update       : {report.content_updated}")
        print(f"  would skip         : {report.skipped}")
    else:
        print(f"  ✓ created          : {report.created}")
        print(f"  ✓ content updated  : {report.content_updated}")
        print(f"  → skipped          : {report.skipped}")
        print(f"  ✗ failed           : {report.failed}")
    if report.errors:
        print()
        print("  Errors:")
        for err in report.errors:
            print(f"    ✗ {err}")
    print("━" * 56)


# ---------------------------------------------------------------------------
# Apply sync
# ---------------------------------------------------------------------------


def apply_sync(
    actions: list[SyncAction],
    mapping: dict,
    map_path: Path,
    tree: dict,
    tree_path: Path,
    dry_run: bool,
) -> SyncReport:
    """Execute (or preview) the computed SyncAction list.

    In dry-run mode no API calls are made and nothing is written to disk.
    In apply mode the map file is saved after every successful create/update
    so a partial run can resume safely.
    """
    report = SyncReport()
    nodes_map: dict[str, dict] = mapping.setdefault("nodes", {})

    # Index of kb_path → resolved node_token for parent look-up during creates
    token_index: dict[str, str] = {
        path: entry.get("node_token", "")
        for path, entry in nodes_map.items()
    }

    _SYM = {"create": "+", "update_content": "~", "skip": "·"}

    for action in actions:
        sym = _SYM.get(action.action, "?")

        if action.action == "skip":
            report.skipped += 1
            if dry_run:
                print(f"  [{sym}] skip            {action.kb_path}")
            continue

        if dry_run:
            print(f"  [{sym}] {action.action:<15s} {action.kb_path}")
            if action.action == "create":
                report.created += 1
            else:
                report.content_updated += 1
            continue

        # ── Apply ────────────────────────────────────────────────────────
        try:
            if action.action == "create":
                parent_token = token_index.get(action.parent_kb_path, "")
                time.sleep(RATE_LIMIT_SLEEP)
                result = _retry(feishu.create_node, action.title, parent_token)
                node_token = result["node_token"]
                obj_token = result["obj_token"]

                # Write content immediately after creation
                content_ok = _write_content(obj_token, action.content)
                stored_hash = action.content_hash if content_ok else ""

                # Back-fill tokens into the live tree object
                action.node["node_token"] = node_token
                action.node["obj_token"] = obj_token

                # Register in token_index for child nodes later in this loop
                token_index[action.kb_path] = node_token

                nodes_map[action.kb_path] = {
                    "node_token": node_token,
                    "obj_token": obj_token,
                    "title": action.title,
                    "synced_at": _now(),
                    "content_hash": stored_hash,
                }
                save_map(map_path, mapping)
                report.created += 1
                print(f"  [+] created         {action.kb_path}  (node={node_token[:8]}…)")

            elif action.action == "update_content":
                time.sleep(RATE_LIMIT_SLEEP)
                content_ok = _write_content(action.obj_token, action.content)
                if content_ok:
                    nodes_map[action.kb_path] = {
                        "node_token": action.node_token,
                        "obj_token": action.obj_token,
                        "title": action.title,
                        "synced_at": _now(),
                        "content_hash": action.content_hash,
                    }
                    token_index[action.kb_path] = action.node_token
                    save_map(map_path, mapping)
                    report.content_updated += 1
                    print(f"  [~] updated         {action.kb_path}")
                else:
                    report.failed += 1
                    report.errors.append(f"content write failed: {action.kb_path}")

        except Exception as exc:
            msg = f"{action.action} failed for '{action.kb_path}': {exc}"
            report.errors.append(msg)
            logger.error(msg)
            report.failed += 1

    if not dry_run:
        # Persist updated tree tokens
        tree_path.write_text(
            json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    report.finished_at = _now()
    return report


# ---------------------------------------------------------------------------
# Interview sync
# ---------------------------------------------------------------------------


def sync_interviews(
    interviews_dir: Path,
    mapping: dict,
    map_path: Path,
    kb_root_token: str,
    dry_run: bool,
) -> SyncReport:
    """Sync interview JSON files as Feishu wiki pages.

    Interview pages are created under a dedicated '面试记录' node that is
    auto-created if it does not exist in the mapping yet.
    """
    report = SyncReport()

    if not interviews_dir.exists():
        logger.warning("interviews directory not found: %s", interviews_dir)
        return report

    files = sorted(interviews_dir.glob("*.json"))
    if not files:
        print("  (no interview files found)")
        return report

    interviews_map: dict[str, dict] = mapping.setdefault("interviews", {})

    # Ensure container node '面试记录' exists
    container_key = "__interviews_container__"
    container_token = ""
    if container_key in interviews_map:
        container_token = interviews_map[container_key].get("node_token", "")
    elif not dry_run:
        time.sleep(RATE_LIMIT_SLEEP)
        try:
            result = _retry(feishu.create_node, "面试记录", kb_root_token)
            container_token = result["node_token"]
            interviews_map[container_key] = {
                "node_token": container_token,
                "obj_token": result["obj_token"],
                "title": "面试记录",
                "synced_at": _now(),
            }
            save_map(map_path, mapping)
            print(f"  [+] created container  面试记录")
            report.created += 1
        except Exception as exc:
            msg = f"failed to create 面试记录 container: {exc}"
            report.errors.append(msg)
            logger.error(msg)
            report.failed += 1
            report.finished_at = _now()
            return report

    for f in files:
        name = f.stem
        try:
            interview = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("failed to read %s: %s", f, exc)
            report.failed += 1
            continue

        title = (
            f"{interview.get('date', name)}_"
            f"{interview.get('company', name)}_"
            f"{interview.get('type', '')}"
        )
        content = render_interview_content(interview)
        content_hash = _sha256(content)

        if name in interviews_map:
            entry = interviews_map[name]
            if entry.get("content_hash") == content_hash:
                report.skipped += 1
                if dry_run:
                    print(f"  [·] skip            {title}")
                continue

            if dry_run:
                print(f"  [~] update_content  {title}")
                report.content_updated += 1
                continue

            time.sleep(RATE_LIMIT_SLEEP)
            obj_token = entry.get("obj_token", "")
            if _write_content(obj_token, content):
                entry["content_hash"] = content_hash
                entry["synced_at"] = _now()
                save_map(map_path, mapping)
                report.content_updated += 1
                print(f"  [~] updated         {title}")
            else:
                report.failed += 1
                report.errors.append(f"content write failed: {name}")
        else:
            if dry_run:
                print(f"  [+] create          {title}")
                report.created += 1
                continue

            time.sleep(RATE_LIMIT_SLEEP)
            try:
                result = _retry(feishu.create_node, title, container_token)
                obj_token = result["obj_token"]
                _write_content(obj_token, content)
                interviews_map[name] = {
                    "node_token": result["node_token"],
                    "obj_token": obj_token,
                    "title": title,
                    "synced_at": _now(),
                    "content_hash": content_hash,
                }
                save_map(map_path, mapping)
                report.created += 1
                print(f"  [+] created         {title}")
            except Exception as exc:
                msg = f"create interview failed for '{name}': {exc}"
                report.errors.append(msg)
                logger.error(msg)
                report.failed += 1

    report.finished_at = _now()
    return report


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Idempotent sync of knowledge tree to Feishu wiki"
    )
    parser.add_argument(
        "--kb",
        default=workspace.DEFAULT_KB_ID,
        metavar="KB_ID",
        help=f"Workspace ID (default: {workspace.DEFAULT_KB_ID})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute the sync (default is dry-run — show plan only)",
    )
    parser.add_argument(
        "--recover",
        action="store_true",
        help="Scan remote Feishu space and recover node mappings before diff",
    )
    parser.add_argument(
        "--interviews",
        action="store_true",
        help="Also sync interview pages under a '面试记录' container node",
    )
    args = parser.parse_args()
    dry_run = not args.apply

    # Load workspace config
    try:
        kb_cfg = workspace.load_kb_config(PROJECT_ROOT, args.kb)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    space_override = (kb_cfg.get("feishu_space_id") or "").strip()
    if space_override:
        config.FEISHU_WIKI_SPACE_ID = space_override

    missing = config.check()
    if missing:
        print(f"ERROR: Missing env vars: {', '.join(missing)}")
        print("Check your .env file.")
        sys.exit(1)

    tree_path = workspace.get_tree_path(PROJECT_ROOT, args.kb)
    if not tree_path.exists():
        print(f"ERROR: knowledge_tree.json not found for workspace '{args.kb}'.")
        print("Run plan-wiki first to generate the knowledge tree.")
        sys.exit(1)

    map_path = workspace.get_map_path(PROJECT_ROOT, args.kb)
    index_path = workspace.get_index_path(PROJECT_ROOT, args.kb)
    interviews_dir = workspace.get_interviews_dir(PROJECT_ROOT, args.kb)

    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    mapping = load_map(map_path)
    mapping.setdefault("space_id", config.FEISHU_WIKI_SPACE_ID)
    mapping.setdefault("kb_id", args.kb)

    mode_label = "DRY-RUN" if dry_run else "APPLY"
    print(f"\n[{mode_label}] kb={args.kb}  space={config.FEISHU_WIKI_SPACE_ID}")

    # ── Recovery pass ────────────────────────────────────────────────────────
    if args.recover:
        print("\n[recover] Scanning remote Feishu space for existing nodes…")
        recovered = recover_remote(tree, mapping)
        if not dry_run:
            save_map(map_path, mapping)
            tree_path.write_text(
                json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        print(f"  recovered {recovered} node mapping(s).")

    # ── Diff ─────────────────────────────────────────────────────────────────
    actions = build_diff(tree, mapping, index_path)
    creates = sum(1 for a in actions if a.action == "create")
    updates = sum(1 for a in actions if a.action == "update_content")
    skips = sum(1 for a in actions if a.action == "skip")

    print(f"\n  tree: {len(actions)} node(s) — {creates} create, {updates} update, {skips} skip")
    if dry_run:
        print("  (pass --apply to execute)\n")

    report = apply_sync(actions, mapping, map_path, tree, tree_path, dry_run)

    # ── Interviews ───────────────────────────────────────────────────────────
    if args.interviews:
        # Find root KB node token for placing the container node
        root_token = ""
        nodes_map = mapping.get("nodes", {})
        if nodes_map:
            first_entry = next(iter(nodes_map.values()))
            root_token = first_entry.get("node_token", "")

        print(f"\n[interviews]")
        i_report = sync_interviews(
            interviews_dir, mapping, map_path, root_token, dry_run
        )
        report.created += i_report.created
        report.content_updated += i_report.content_updated
        report.skipped += i_report.skipped
        report.failed += i_report.failed
        report.errors.extend(i_report.errors)

    print_report(report, args.kb, dry_run)

    if not dry_run:
        print(f"\n  feishu_map.json  → {map_path}")
        print(f"  knowledge_tree.json updated at {tree_path}")


if __name__ == "__main__":
    main()
