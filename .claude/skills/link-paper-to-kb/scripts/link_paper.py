"""Manage edges between papers and KB nodes (or between nodes).

Edges are stored in the ``edges`` table of kb_index.db.
Supported edge types: related_to, depends_on, compares_with,
                       derived_from, updated_by, cites

Usage:
  # Add a paper→kb_node edge
  link_paper.py --kb llm-knowledge --add-edge \\
      --src-id <paper_id> --src-type paper \\
      --dst-id "LLM Knowledge Base > Flash Attention" --dst-type kb_node \\
      --edge-type derived_from --note "FA2 improves FA1 parallelism"

  # List edges for a node/paper
  link_paper.py --kb llm-knowledge --list-edges --node-id <id>

  # Delete an edge by edge_id
  link_paper.py --kb llm-knowledge --delete-edge <edge_id>

  # List all papers (helper: get paper_ids)
  link_paper.py --kb llm-knowledge --list-papers
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import retrieval, workspace  # noqa: E402

_VALID_EDGE_TYPES = sorted(retrieval.EDGE_TYPES - {"contains"})  # contains is auto-derived


def cmd_add_edge(args: argparse.Namespace) -> None:
    if not args.src_id or not args.dst_id:
        print("ERROR: --src-id and --dst-id are required.")
        sys.exit(1)
    if args.edge_type not in _VALID_EDGE_TYPES:
        print(f"ERROR: Invalid edge type '{args.edge_type}'.")
        print(f"  Valid types: {', '.join(_VALID_EDGE_TYPES)}")
        sys.exit(1)

    db_path = workspace.get_index_path(PROJECT_ROOT, args.kb)
    conn = retrieval.open_db(db_path)
    try:
        edge_id = retrieval.write_edge(
            conn,
            src_id=args.src_id,
            dst_id=args.dst_id,
            edge_type=args.edge_type,
            src_type=args.src_type,
            dst_type=args.dst_type,
            weight=args.weight,
            note=args.note,
        )
    finally:
        conn.close()

    print(f"[kb={args.kb}] Edge created:")
    print(f"  [{args.src_type}] {args.src_id}")
    print(f"  --{args.edge_type}-->")
    print(f"  [{args.dst_type}] {args.dst_id}")
    print(f"  edge_id: {edge_id}")
    if args.note:
        print(f"  note: {args.note}")


def cmd_list_edges(args: argparse.Namespace) -> None:
    if not args.node_id:
        print("ERROR: --node-id is required for --list-edges.")
        sys.exit(1)

    db_path = workspace.get_index_path(PROJECT_ROOT, args.kb)
    conn = retrieval.open_db(db_path)
    try:
        edges = retrieval.list_edges(conn, node_id=args.node_id)
    finally:
        conn.close()

    if not edges:
        print(f"[kb={args.kb}] No edges found for '{args.node_id}'.")
        return

    print(f"[kb={args.kb}] {len(edges)} edge(s) for '{args.node_id}':\n")
    for e in edges:
        arrow = f"--{e['edge_type']}-->"
        note = f"  ({e['note']})" if e.get("note") else ""
        print(f"  [{e['src_type']}] {e['src_id']}")
        print(f"  {arrow}")
        print(f"  [{e['dst_type']}] {e['dst_id']}{note}")
        print(f"  edge_id: {e['edge_id']}")
        print()


def cmd_delete_edge(args: argparse.Namespace) -> None:
    db_path = workspace.get_index_path(PROJECT_ROOT, args.kb)
    conn = retrieval.open_db(db_path)
    try:
        deleted = retrieval.delete_edge(conn, args.delete_edge)
    finally:
        conn.close()

    if deleted:
        print(f"[kb={args.kb}] Edge '{args.delete_edge}' deleted.")
    else:
        print(f"[kb={args.kb}] Edge '{args.delete_edge}' not found.")
        sys.exit(1)


def cmd_list_papers(args: argparse.Namespace) -> None:
    db_path = workspace.get_index_path(PROJECT_ROOT, args.kb)
    conn = retrieval.open_db(db_path)
    try:
        papers = retrieval.list_papers(conn)
    finally:
        conn.close()

    if not papers:
        print(f"[kb={args.kb}] No papers found. Run ingest-paper first.")
        return

    print(f"[kb={args.kb}] {len(papers)} paper(s):\n")
    for p in papers:
        status = p.get("status", "?")
        year = p.get("year") or ""
        print(f"  [{status}] {p['title']} ({year})")
        print(f"    paper_id: {p['paper_id']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage edges between papers and KB nodes"
    )
    parser.add_argument(
        "--kb",
        default=workspace.DEFAULT_KB_ID,
        metavar="KB_ID",
    )
    parser.add_argument("--add-edge", action="store_true", help="Add a new edge")
    parser.add_argument("--list-edges", action="store_true", help="List edges for a node")
    parser.add_argument("--delete-edge", default="", metavar="EDGE_ID")
    parser.add_argument("--list-papers", action="store_true", help="List all papers (get IDs)")

    # Edge fields
    parser.add_argument("--src-id", default="", metavar="ID")
    parser.add_argument("--src-type", default="paper", choices=["paper", "kb_node"])
    parser.add_argument("--dst-id", default="", metavar="ID")
    parser.add_argument("--dst-type", default="kb_node", choices=["paper", "kb_node"])
    parser.add_argument(
        "--edge-type",
        default="related_to",
        choices=_VALID_EDGE_TYPES,
        metavar="TYPE",
    )
    parser.add_argument("--weight", type=float, default=1.0)
    parser.add_argument("--note", default="", metavar="TEXT")

    # List-edges filter
    parser.add_argument("--node-id", default="", metavar="ID_OR_PATH")

    args = parser.parse_args()

    if args.add_edge:
        cmd_add_edge(args)
    elif args.list_edges:
        cmd_list_edges(args)
    elif args.delete_edge:
        cmd_delete_edge(args)
    elif args.list_papers:
        cmd_list_papers(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
