"""Register a web article as a source reference on a knowledge tree node.

Updates the node's ``source_refs`` list in knowledge_tree.json.
This script only handles the metadata registration; actual memory archiving
is handled by archive_to_kb.py (called separately by Claude during the skill flow).

Usage:
    # Add a source reference to a node
    python ingest_url.py --kb llm-knowledge \\
        --node "LLM Knowledge Base > Post-Training Alignment > RLHF > PPO" \\
        --url "https://zhuanlan.zhihu.com/p/677607581" \\
        --title "RLHF实战·PPO算法详解"

    # List current source_refs for a node
    python ingest_url.py --kb llm-knowledge \\
        --node "LLM Knowledge Base > Post-Training Alignment > RLHF > PPO" \\
        --list

    # Remove a source reference by index (0-based)
    python ingest_url.py --kb llm-knowledge \\
        --node "LLM Knowledge Base > Post-Training Alignment > RLHF > PPO" \\
        --remove 1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import workspace  # noqa: E402


# ---------------------------------------------------------------------------
# Tree helpers
# ---------------------------------------------------------------------------


def _find_node(tree: dict, kb_path: str) -> dict | None:
    """Find a node by its dot-separated path (e.g. 'A > B > C')."""
    parts = [p.strip() for p in kb_path.split(">")]

    def _walk(node: dict, depth: int) -> dict | None:
        if node.get("title", "").strip() != parts[depth]:
            return None
        if depth == len(parts) - 1:
            return node
        for child in node.get("children", []):
            result = _walk(child, depth + 1)
            if result is not None:
                return result
        return None

    # The root title is parts[0]
    return _walk(tree, 0)


def _format_entry(title: str | None, url: str) -> str:
    """Format a source_ref entry: 'Title (url)' or just 'url'."""
    if title and title.strip():
        return f"{title.strip()} ({url})"
    return url


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_add(args: argparse.Namespace, tree: dict, tree_path: Path) -> None:
    node = _find_node(tree, args.node)
    if node is None:
        print(f"ERROR: node not found: '{args.node}'")
        _suggest_nodes(tree, args.node)
        sys.exit(1)

    source_refs: list[str] = node.setdefault("source_refs", [])
    entry = _format_entry(args.title, args.url)

    # Check for duplicates (URL already present somewhere in the list)
    for existing in source_refs:
        if args.url in existing:
            print(f"Source ref already registered: {existing}")
            return

    if args.first:
        source_refs.insert(0, entry)
    else:
        source_refs.append(entry)

    tree_path.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[+] Added source ref to '{args.node}':")
    print(f"    {entry}")
    print(f"    Position: {'first' if args.first else 'last'} (total {len(source_refs)})")


def cmd_list(args: argparse.Namespace, tree: dict) -> None:
    node = _find_node(tree, args.node)
    if node is None:
        print(f"ERROR: node not found: '{args.node}'")
        sys.exit(1)

    source_refs: list[str] = node.get("source_refs") or []
    if not source_refs:
        print(f"No source_refs on node: '{args.node}'")
        return

    print(f"source_refs for '{args.node}' ({len(source_refs)} total):")
    for i, s in enumerate(source_refs):
        print(f"  [{i}] {s}")


def cmd_remove(args: argparse.Namespace, tree: dict, tree_path: Path) -> None:
    node = _find_node(tree, args.node)
    if node is None:
        print(f"ERROR: node not found: '{args.node}'")
        sys.exit(1)

    source_refs: list[str] = node.get("source_refs") or []
    idx = args.remove
    if idx < 0 or idx >= len(source_refs):
        print(f"ERROR: index {idx} out of range (0–{len(source_refs) - 1})")
        sys.exit(1)

    removed = source_refs.pop(idx)
    node["source_refs"] = source_refs
    tree_path.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[-] Removed: {removed}")


def _suggest_nodes(tree: dict, query: str) -> None:
    """Print up to 5 node paths that contain any query token."""
    tokens = set(query.lower().split(">"))
    tokens = {t.strip() for t in tokens}

    def _walk(node: dict, path: str) -> None:
        title = node.get("title", "")
        full = f"{path} > {title}" if path else title
        if any(t in title.lower() for t in tokens):
            print(f"  ? {full}")
        for child in node.get("children", []):
            _walk(child, full)

    print("Did you mean one of these?")
    _walk(tree, "")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register a web article as a source reference on a KB node"
    )
    parser.add_argument("--kb", default=workspace.DEFAULT_KB_ID, metavar="KB_ID")
    parser.add_argument(
        "--node",
        required=True,
        metavar="KB_PATH",
        help='Node path, e.g. "LLM Knowledge Base > RLHF > PPO"',
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", metavar="URL", help="URL to register as source ref")
    group.add_argument("--list", action="store_true", help="List current source_refs")
    group.add_argument("--remove", type=int, metavar="INDEX", help="Remove source ref by index")

    parser.add_argument("--title", default="", metavar="TITLE", help="Human-readable title for the source")
    parser.add_argument(
        "--first",
        action="store_true",
        help="Insert as the first (primary) source ref instead of appending",
    )

    args = parser.parse_args()

    tree_path = workspace.get_tree_path(PROJECT_ROOT, args.kb)
    if not tree_path.exists():
        print(f"ERROR: knowledge_tree.json not found for workspace '{args.kb}'.")
        print("Run plan-wiki first.")
        sys.exit(1)

    tree = json.loads(tree_path.read_text(encoding="utf-8"))

    if args.list:
        cmd_list(args, tree)
    elif args.remove is not None:
        cmd_remove(args, tree, tree_path)
    else:
        cmd_add(args, tree, tree_path)


if __name__ == "__main__":
    main()
