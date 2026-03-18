"""Search local knowledge tree for nodes matching a query."""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import workspace  # noqa: E402


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


def main() -> None:
    """Parse args and run keyword search against the workspace knowledge tree."""
    parser = argparse.ArgumentParser(description="Search knowledge base")
    parser.add_argument("query", nargs="+", help="Search query keywords")
    parser.add_argument(
        "--kb",
        default=workspace.DEFAULT_KB_ID,
        metavar="KB_ID",
        help=f"Workspace ID (default: {workspace.DEFAULT_KB_ID})",
    )
    args = parser.parse_args()
    query = " ".join(args.query)

    tree_path = workspace.get_tree_path(PROJECT_ROOT, args.kb)
    if not tree_path.exists():
        print(f"Knowledge tree not found for workspace '{args.kb}' ({tree_path}).")
        print("Run plan-wiki first to build the knowledge tree.")
        sys.exit(0)

    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    results = search(tree, query)
    results.sort(key=lambda r: r["score"], reverse=True)

    if not results:
        print(f"No matches for '{query}' in knowledge base '{args.kb}'.")
        sys.exit(0)

    print(f"[kb={args.kb}] Found {len(results)} match(es) for '{query}':\n")
    for r in results[:10]:
        path_str = " > ".join(r["path"])
        print(f"  [{r['score']}] {path_str}")
        if r["summary"]:
            print(f"      {r['summary']}")
        print()


if __name__ == "__main__":
    main()
