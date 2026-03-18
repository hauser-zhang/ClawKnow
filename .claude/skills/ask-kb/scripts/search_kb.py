"""Search local knowledge tree for nodes matching a query."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
TREE_PATH = PROJECT_ROOT / "data" / "knowledge_tree.json"


def search(node: dict, query: str, path: list[str] | None = None) -> list[dict]:
    """Recursively search tree by keyword matching on title and summary."""
    path = (path or []) + [node["title"]]
    results = []

    score = 0
    q = query.lower()
    title_lower = node.get("title", "").lower()
    summary_lower = node.get("summary", "").lower()

    if q in title_lower:
        score += 3
    if q in summary_lower:
        score += 1
    # Also try matching individual Chinese characters / words
    for word in q.split():
        if word in title_lower:
            score += 2
        if word in summary_lower:
            score += 1

    if score > 0:
        results.append({
            "path": list(path),
            "title": node["title"],
            "summary": node.get("summary", ""),
            "score": score,
        })

    for child in node.get("children", []):
        results.extend(search(child, query, path))

    return results


def main():
    if len(sys.argv) < 2:
        print("Usage: python search_kb.py <query>")
        sys.exit(1)

    query = " ".join(sys.argv[1:])

    if not TREE_PATH.exists():
        print("Knowledge tree not found (data/knowledge_tree.json).")
        print("Run plan-wiki first to build the knowledge tree.")
        sys.exit(0)

    tree = json.loads(TREE_PATH.read_text(encoding="utf-8"))
    results = search(tree, query)
    results.sort(key=lambda r: r["score"], reverse=True)

    if not results:
        print(f"No matches for '{query}' in knowledge tree.")
        sys.exit(0)

    print(f"Found {len(results)} match(es) for '{query}':\n")
    for r in results[:10]:
        path_str = " > ".join(r["path"])
        print(f"  [{r['score']}] {path_str}")
        if r["summary"]:
            print(f"      {r['summary']}")
        print()


if __name__ == "__main__":
    main()
