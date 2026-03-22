"""Paper discussion helper: list, search, show, and annotate ingested papers.

This script is the data layer for the discuss-paper skill.
Claude provides all analysis and discussion; this script handles I/O.

Usage:
  discuss_paper.py --kb llm-knowledge --list [--status reading]
  discuss_paper.py --kb llm-knowledge --search "flash attention"
  discuss_paper.py --kb llm-knowledge --show <paper_id>
  discuss_paper.py --kb llm-knowledge --paper-id <id> --add-insight "<text>"
  discuss_paper.py --kb llm-knowledge --paper-id <id> --set-status read
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import retrieval, workspace  # noqa: E402


def _load_paper(papers_dir: Path, paper_id: str) -> dict | None:
    path = papers_dir / f"{paper_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_paper(papers_dir: Path, paper: dict) -> None:
    paper["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = papers_dir / f"{paper['paper_id']}.json"
    path.write_text(json.dumps(paper, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_list(args: argparse.Namespace) -> None:
    db_path = workspace.get_index_path(PROJECT_ROOT, args.kb)
    conn = retrieval.open_db(db_path)
    try:
        papers = retrieval.list_papers(conn, status_filter=args.status or None)
    finally:
        conn.close()

    if not papers:
        status_msg = f" (status={args.status})" if args.status else ""
        print(f"[kb={args.kb}] No papers found{status_msg}.")
        print("  Run ingest-paper to add your first paper.")
        return

    print(f"[kb={args.kb}] {len(papers)} paper(s):\n")
    for p in papers:
        year = p.get("year") or ""
        status = p.get("status", "?")
        pid = p["paper_id"]
        print(f"  [{status}] {p['title']} ({year})")
        print(f"    id: {pid}")
        preview = (p.get("abstract_summary") or "")[:120].replace("\n", " ")
        if preview:
            print(f"    {preview}...")
        print()


def cmd_search(args: argparse.Namespace) -> None:
    db_path = workspace.get_index_path(PROJECT_ROOT, args.kb)
    conn = retrieval.open_db(db_path)
    try:
        papers = retrieval.search_papers(conn, args.search, top_k=5)
    finally:
        conn.close()

    if not papers:
        print(f"[kb={args.kb}] No papers match '{args.search}'.")
        return

    print(f"[kb={args.kb}] {len(papers)} paper(s) matching '{args.search}':\n")
    for p in papers:
        print(f"  [{p.get('status', '?')}] {p['title']} ({p.get('year', '')})")
        print(f"    id: {p['paper_id']}")
        preview = (p.get("abstract_summary") or "")[:120].replace("\n", " ")
        if preview:
            print(f"    {preview}...")
        print()


def cmd_show(args: argparse.Namespace) -> None:
    papers_dir = workspace.get_papers_dir(PROJECT_ROOT, args.kb)
    paper = _load_paper(papers_dir, args.paper_id)
    if paper is None:
        print(f"ERROR: Paper '{args.paper_id}' not found in {papers_dir}")
        sys.exit(1)

    print(f"[PAPER] {paper['title']}")
    authors = paper.get("authors", [])
    if isinstance(authors, list):
        authors = ", ".join(authors)
    year = paper.get("year") or ""
    venue = paper.get("venue") or ""
    print(f"  Authors: {authors}  Year: {year}  Venue: {venue}")
    doi = paper.get("doi") or ""
    arxiv = paper.get("arxiv_id") or ""
    if doi:
        print(f"  DOI: {doi}")
    if arxiv:
        print(f"  arXiv: {arxiv}")
    print(f"  Status: {paper.get('status', 'reading')}")
    print()

    if paper.get("abstract_summary"):
        print("Abstract Summary:")
        print(f"  {paper['abstract_summary']}")
        print()

    if paper.get("method_summary"):
        print("Method Summary:")
        print(f"  {paper['method_summary']}")
        print()

    if paper.get("key_claims"):
        print("Key Claims:")
        for i, c in enumerate(paper["key_claims"], 1):
            print(f"  {i}. {c}")
        print()

    if paper.get("limitations"):
        print("Limitations:")
        for lim in paper["limitations"]:
            print(f"  - {lim}")
        print()

    if paper.get("open_questions"):
        print("Open Questions:")
        for q in paper["open_questions"]:
            print(f"  ? {q}")
        print()

    if paper.get("related_kb_nodes"):
        print("Related KB Nodes:")
        for node in paper["related_kb_nodes"]:
            print(f"  -> {node}")
        print()

    if paper.get("user_insights"):
        print("User Insights:")
        for ins in paper["user_insights"]:
            print(f"  * {ins}")
        print()


def cmd_add_insight(args: argparse.Namespace) -> None:
    papers_dir = workspace.get_papers_dir(PROJECT_ROOT, args.kb)
    paper = _load_paper(papers_dir, args.paper_id)
    if paper is None:
        print(f"ERROR: Paper '{args.paper_id}' not found.")
        sys.exit(1)

    insight = args.add_insight.strip()
    if not insight:
        print("ERROR: --add-insight cannot be empty.")
        sys.exit(1)

    paper.setdefault("user_insights", [])
    paper["user_insights"].append(insight)
    _save_paper(papers_dir, paper)

    print(f"[kb={args.kb}] Added insight to '{paper['title']}'")
    print(f"  * {insight}")
    print(f"  Total insights: {len(paper['user_insights'])}")


def cmd_set_status(args: argparse.Namespace) -> None:
    papers_dir = workspace.get_papers_dir(PROJECT_ROOT, args.kb)
    paper = _load_paper(papers_dir, args.paper_id)
    if paper is None:
        print(f"ERROR: Paper '{args.paper_id}' not found.")
        sys.exit(1)

    old_status = paper.get("status", "reading")
    paper["status"] = args.set_status

    # Also update FTS index
    db_path = workspace.get_index_path(PROJECT_ROOT, args.kb)
    conn = retrieval.open_db(db_path)
    try:
        retrieval.index_paper(conn, paper)
    finally:
        conn.close()

    _save_paper(papers_dir, paper)
    print(
        f"[kb={args.kb}] Status updated: '{paper['title']}'"
        f" {old_status} -> {args.set_status}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List, search, show, and annotate ingested papers"
    )
    parser.add_argument(
        "--kb",
        default=workspace.DEFAULT_KB_ID,
        metavar="KB_ID",
        help=f"Workspace ID (default: {workspace.DEFAULT_KB_ID})",
    )
    parser.add_argument("--list", action="store_true", help="List all papers")
    parser.add_argument("--status", default="", choices=["", "reading", "read", "reviewed"])
    parser.add_argument("--search", default="", metavar="QUERY", help="Search papers by keyword")
    parser.add_argument("--show", action="store_true", help="Show full paper details")
    parser.add_argument("--paper-id", default="", metavar="ID", help="Target paper_id")
    parser.add_argument("--add-insight", default="", metavar="TEXT", help="Append user insight")
    parser.add_argument(
        "--set-status",
        default="",
        choices=["reading", "read", "reviewed"],
        metavar="STATUS",
        help="Update paper status",
    )
    args = parser.parse_args()

    if args.list:
        cmd_list(args)
    elif args.search:
        cmd_search(args)
    elif args.show and args.paper_id:
        cmd_show(args)
    elif args.add_insight and args.paper_id:
        cmd_add_insight(args)
    elif args.set_status and args.paper_id:
        cmd_set_status(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
