"""Archive discussion content into a knowledge tree node."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
TREE_PATH = PROJECT_ROOT / "data" / "knowledge_tree.json"


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


def main():
    if len(sys.argv) < 3:
        print("Usage: python archive_to_kb.py <node_path> <content>")
        print('  node_path: ">" separated, e.g. "模型架构>MoE"')
        sys.exit(1)

    path_str = sys.argv[1]
    content = sys.argv[2]
    path = [p.strip() for p in path_str.split(">")]

    if not TREE_PATH.exists():
        print("ERROR: knowledge_tree.json not found.")
        sys.exit(1)

    tree = json.loads(TREE_PATH.read_text(encoding="utf-8"))
    node = find_node(tree, path)

    if node is None:
        print(f"ERROR: Node path not found: {' > '.join(path)}")
        print("Available top-level nodes:")
        for child in tree.get("children", []):
            print(f"  - {child['title']}")
        sys.exit(1)

    update_summary(node, content)
    TREE_PATH.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Archived to: {' > '.join(path)}")


if __name__ == "__main__":
    main()
