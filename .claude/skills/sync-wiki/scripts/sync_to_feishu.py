"""Sync local knowledge_tree.json to Feishu wiki as nested nodes."""

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import config, feishu, workspace  # noqa: E402


def count_nodes(tree: dict) -> int:
    return 1 + sum(count_nodes(c) for c in tree.get("children", []))


def sync_recursive(node: dict, parent_token: str = "", depth: int = 0) -> int:
    """Create wiki nodes recursively. Returns total nodes created."""
    indent = "  " * depth
    result = feishu.create_node(node["title"], parent_token)
    node["node_token"] = result["node_token"]
    node["obj_token"] = result["obj_token"]
    print(f"{indent}+ {node['title']}  (node={result['node_token'][:8]}...)")

    created = 1
    for child in node.get("children", []):
        time.sleep(0.3)  # basic rate-limit guard
        created += sync_recursive(child, result["node_token"], depth + 1)
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync knowledge tree to Feishu wiki")
    parser.add_argument(
        "--kb",
        default=workspace.DEFAULT_KB_ID,
        metavar="KB_ID",
        help=f"Workspace ID (default: {workspace.DEFAULT_KB_ID})",
    )
    args = parser.parse_args()

    # Load workspace config; apply feishu_space_id override if present
    try:
        kb_cfg = workspace.load_kb_config(PROJECT_ROOT, args.kb)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    space_id_override = kb_cfg.get("feishu_space_id", "").strip()
    if space_id_override:
        config.FEISHU_WIKI_SPACE_ID = space_id_override

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

    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    total = count_nodes(tree)
    print(f"[kb={args.kb}] Syncing {total} node(s) to Feishu wiki space: {config.FEISHU_WIKI_SPACE_ID}\n")

    created = sync_recursive(tree)

    # Save updated tree with tokens
    tree_path.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nDone! Created {created} node(s).")
    print(f"knowledge_tree.json updated with node_token/obj_token at {tree_path}")


if __name__ == "__main__":
    main()
