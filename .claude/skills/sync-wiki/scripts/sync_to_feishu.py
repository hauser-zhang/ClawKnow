"""Sync local knowledge_tree.json to Feishu wiki as nested nodes."""

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import config  # noqa: E402
from lib import feishu   # noqa: E402

TREE_PATH = PROJECT_ROOT / "data" / "knowledge_tree.json"


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


def main():
    missing = config.check()
    if missing:
        print(f"ERROR: Missing env vars: {', '.join(missing)}")
        print("Check your .env file.")
        sys.exit(1)

    if not TREE_PATH.exists():
        print("ERROR: data/knowledge_tree.json not found.")
        print("Run plan-wiki first to generate the knowledge tree.")
        sys.exit(1)

    tree = json.loads(TREE_PATH.read_text(encoding="utf-8"))
    total = count_nodes(tree)
    print(f"Syncing {total} node(s) to Feishu wiki space: {config.FEISHU_WIKI_SPACE_ID}\n")

    created = sync_recursive(tree)

    # Save updated tree with tokens
    TREE_PATH.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nDone! Created {created} node(s).")
    print("knowledge_tree.json updated with node_token/obj_token.")


if __name__ == "__main__":
    main()
