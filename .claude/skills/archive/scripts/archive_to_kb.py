"""Archive discussion content into a knowledge tree node."""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import workspace  # noqa: E402


def find_node(tree: dict, path: list[str]) -> dict | None:
    """Walk the tree to find a node by path like ['后训练', 'RLHF', 'PPO']."""
    if not path:
        return tree
    for child in tree.get("children", []):
        if child["title"] == path[0]:
            return find_node(child, path[1:])
    return None


def update_summary(node: dict, content: str) -> None:
    """Append content to a node's summary."""
    existing = node.get("summary", "")
    if existing:
        node["summary"] = f"{existing}\n\n---\n{content}"
    else:
        node["summary"] = content


def main() -> None:
    """Parse args, locate target node, and append content to its summary."""
    parser = argparse.ArgumentParser(description="Archive content to a knowledge tree node")
    parser.add_argument(
        "node_path",
        help='">"-separated node path, e.g. "模型架构>MoE"',
    )
    parser.add_argument("content", help="Content to archive into the node summary")
    parser.add_argument(
        "--kb",
        default=workspace.DEFAULT_KB_ID,
        metavar="KB_ID",
        help=f"Workspace ID (default: {workspace.DEFAULT_KB_ID})",
    )
    args = parser.parse_args()

    path = [p.strip() for p in args.node_path.split(">")]

    tree_path = workspace.get_tree_path(PROJECT_ROOT, args.kb)
    if not tree_path.exists():
        print(f"ERROR: knowledge_tree.json not found for workspace '{args.kb}'.")
        sys.exit(1)

    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    node = find_node(tree, path)

    if node is None:
        print(f"ERROR: Node path not found: {' > '.join(path)}")
        print("Available top-level nodes:")
        for child in tree.get("children", []):
            print(f"  - {child['title']}")
        sys.exit(1)

    update_summary(node, args.content)
    tree_path.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[kb={args.kb}] Archived to: {' > '.join(path)}")


if __name__ == "__main__":
    main()
