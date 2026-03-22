"""Export the knowledge graph to JSONL and JSON files.

Reads knowledge_tree.json + edges table → writes:
  workspaces/<kb_id>/graph/nodes.jsonl   (one node per line)
  workspaces/<kb_id>/graph/edges.jsonl   (one edge per line)
  workspaces/<kb_id>/graph/graph.json    (combined, for simple visualization)

Node types: kb_node, paper
Edge types (auto-derived from tree): contains
Edge types (from edges table): related_to, depends_on, compares_with,
                                derived_from, updated_by, cites

Safe to run repeatedly — output is always regenerated from source data.

Usage:
  python tools/export_graph.py                    # default workspace
  python tools/export_graph.py --kb llm-knowledge
  python tools/export_graph.py --kb llm-knowledge --format jsonl   # default
  python tools/export_graph.py --kb llm-knowledge --format json    # combined only
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import retrieval, workspace  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export knowledge graph to nodes.jsonl + edges.jsonl + graph.json"
    )
    parser.add_argument(
        "--kb",
        default=workspace.DEFAULT_KB_ID,
        metavar="KB_ID",
        help=f"Workspace ID (default: {workspace.DEFAULT_KB_ID})",
    )
    parser.add_argument(
        "--format",
        default="all",
        choices=["all", "jsonl", "json"],
        help="Output format: all (default), jsonl, or json only",
    )
    args = parser.parse_args()

    tree_path = workspace.get_tree_path(PROJECT_ROOT, args.kb)
    if not tree_path.exists():
        print(f"ERROR: knowledge_tree.json not found for workspace '{args.kb}'.")
        print("  Run plan-wiki first to build the knowledge tree.")
        sys.exit(1)

    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    db_path = workspace.get_index_path(PROJECT_ROOT, args.kb)
    conn = retrieval.open_db(db_path)
    try:
        graph = retrieval.export_graph(conn, tree)
    finally:
        conn.close()

    nodes = graph["nodes"]
    edges = graph["edges"]

    graph_dir = workspace.get_graph_dir(PROJECT_ROOT, args.kb)
    graph_dir.mkdir(parents=True, exist_ok=True)

    if args.format in ("all", "jsonl"):
        nodes_path = graph_dir / "nodes.jsonl"
        edges_path = graph_dir / "edges.jsonl"
        nodes_path.write_text(
            "\n".join(json.dumps(n, ensure_ascii=False) for n in nodes),
            encoding="utf-8",
        )
        edges_path.write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in edges),
            encoding="utf-8",
        )
        print(f"[kb={args.kb}] Wrote {len(nodes)} nodes -> {nodes_path.name}")
        print(f"[kb={args.kb}] Wrote {len(edges)} edges -> {edges_path.name}")

    if args.format in ("all", "json"):
        graph_path = graph_dir / "graph.json"
        graph_path.write_text(
            json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[kb={args.kb}] Wrote combined graph -> {graph_path.name}")

    # Summary
    kb_nodes = sum(1 for n in nodes if n["type"] == "kb_node")
    paper_nodes = sum(1 for n in nodes if n["type"] == "paper")
    edge_types: dict[str, int] = {}
    for e in edges:
        edge_types[e["type"]] = edge_types.get(e["type"], 0) + 1

    print()
    print(f"Graph summary for workspace '{args.kb}':")
    print(f"  Nodes: {len(nodes)} total ({kb_nodes} kb_node, {paper_nodes} paper)")
    print(f"  Edges: {len(edges)} total")
    for etype, count in sorted(edge_types.items()):
        print(f"    {etype}: {count}")


if __name__ == "__main__":
    main()
