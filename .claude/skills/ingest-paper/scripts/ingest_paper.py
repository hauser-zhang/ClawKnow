"""Save or update a paper record in the workspace.

The paper JSON is passed via --data as a JSON string (Claude prepares it).
The script validates required fields, assigns a stable paper_id, saves the
JSON file to workspaces/<kb_id>/papers/<paper_id>.json, and updates the
fts_papers index in kb_index.db.

Usage:
  ingest_paper.py --kb llm-knowledge --data '<json>'

  # Show all ingested papers
  ingest_paper.py --kb llm-knowledge --list [--status reading]

  # Show one paper
  ingest_paper.py --kb llm-knowledge --show <paper_id>
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import retrieval, workspace  # noqa: E402

_REQUIRED_FIELDS = {"title"}


def _derive_paper_id(paper: dict) -> str:
    """Derive a stable paper_id from doi, arxiv_id, or title."""
    if paper.get("doi"):
        key = f"doi:{paper['doi'].strip().lower()}"
    elif paper.get("arxiv_id"):
        key = f"arxiv:{paper['arxiv_id'].strip().lower()}"
    else:
        key = f"title:{paper.get('title', '').strip().lower()}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _save_paper_file(papers_dir: Path, paper: dict) -> Path:
    """Write paper dict to papers/<paper_id>.json."""
    papers_dir.mkdir(parents=True, exist_ok=True)
    paper_id = paper["paper_id"]
    out_path = papers_dir / f"{paper_id}.json"
    out_path.write_text(json.dumps(paper, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def _load_paper_file(papers_dir: Path, paper_id: str) -> dict | None:
    """Load a paper JSON file, or return None if not found."""
    path = papers_dir / f"{paper_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_save(args: argparse.Namespace) -> None:
    """Parse --data JSON, assign paper_id, save file, update FTS index."""
    try:
        paper: dict = json.loads(args.data)
    except json.JSONDecodeError as exc:
        print(f"ERROR: Invalid --data JSON: {exc}")
        sys.exit(1)

    missing = _REQUIRED_FIELDS - set(paper.keys())
    if missing:
        print(f"ERROR: Missing required fields: {', '.join(sorted(missing))}")
        sys.exit(1)

    # Assign / preserve paper_id
    if not paper.get("paper_id"):
        paper["paper_id"] = _derive_paper_id(paper)

    now = datetime.now(timezone.utc).isoformat()
    paper.setdefault("added_at", now)
    paper["updated_at"] = now
    paper.setdefault("status", "reading")
    paper.setdefault("authors", [])
    paper.setdefault("key_claims", [])
    paper.setdefault("limitations", [])
    paper.setdefault("open_questions", [])
    paper.setdefault("related_kb_nodes", [])
    paper.setdefault("user_insights", [])

    papers_dir = workspace.get_papers_dir(PROJECT_ROOT, args.kb)
    out_path = _save_paper_file(papers_dir, paper)
    print(f"[kb={args.kb}] Saved paper '{paper['title']}' -> {out_path.name}")

    # Update FTS index
    db_path = workspace.get_index_path(PROJECT_ROOT, args.kb)
    conn = retrieval.open_db(db_path)
    try:
        retrieval.index_paper(conn, paper)
        print(f"[kb={args.kb}] FTS index updated for paper_id={paper['paper_id']}")
    finally:
        conn.close()


def cmd_list(args: argparse.Namespace) -> None:
    """List all ingested papers for the workspace."""
    db_path = workspace.get_index_path(PROJECT_ROOT, args.kb)
    conn = retrieval.open_db(db_path)
    try:
        papers = retrieval.list_papers(conn, status_filter=args.status)
    finally:
        conn.close()

    if not papers:
        status_msg = f" (status={args.status})" if args.status else ""
        print(f"[kb={args.kb}] No papers found{status_msg}.")
        return

    print(f"[kb={args.kb}] {len(papers)} paper(s):\n")
    for p in papers:
        year = p.get("year") or ""
        authors = p.get("authors") or ""
        venue = p.get("venue") or ""
        status = p.get("status", "?")
        aid = p.get("arxiv_id") or p.get("doi") or p["paper_id"]
        print(f"  [{status}] {p['title']} ({year})")
        print(f"    authors: {authors}  venue: {venue}")
        print(f"    id: {p['paper_id']}  ref: {aid}")
        summary = (p.get("abstract_summary") or "")[:120].replace("\n", " ")
        if summary:
            print(f"    summary: {summary}...")
        print()


def cmd_show(args: argparse.Namespace) -> None:
    """Print full paper JSON for the given paper_id."""
    papers_dir = workspace.get_papers_dir(PROJECT_ROOT, args.kb)
    paper = _load_paper_file(papers_dir, args.show)
    if paper is None:
        print(f"ERROR: Paper '{args.show}' not found in {papers_dir}")
        sys.exit(1)
    print(json.dumps(paper, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest or list paper records in a ClawKnow workspace"
    )
    parser.add_argument(
        "--kb",
        default=workspace.DEFAULT_KB_ID,
        metavar="KB_ID",
        help=f"Workspace ID (default: {workspace.DEFAULT_KB_ID})",
    )
    parser.add_argument(
        "--data",
        default="",
        metavar="JSON",
        help="Full paper JSON string to save (ingest mode)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all papers in the workspace",
    )
    parser.add_argument(
        "--status",
        default="",
        choices=["", "reading", "read", "reviewed"],
        metavar="STATUS",
        help="Filter by status when using --list",
    )
    parser.add_argument(
        "--show",
        default="",
        metavar="PAPER_ID",
        help="Print full JSON for one paper",
    )
    args = parser.parse_args()

    if args.show:
        cmd_show(args)
    elif args.list:
        cmd_list(args)
    elif args.data:
        cmd_save(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
