"""Review the knowledge graph: identify stale, weak, and newly active nodes.

Prints a structured review report that Claude can interpret and act on.

Categories:
  recently_added  — memories created within the last N days
  stale_nodes     — leaf nodes with no activity in >30 days
  weak_nodes      — leaf nodes with zero support (no memories, chunks, or edges)
  candidate_links — node pairs sharing ≥2 title words (heuristic link suggestions)

Usage:
  python tools/review_graph.py                         # default workspace
  python tools/review_graph.py --kb llm-knowledge
  python tools/review_graph.py --kb llm-knowledge --stale-days 14 --recent-days 3
  python tools/review_graph.py --kb llm-knowledge --only weak  # single category
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import retrieval, workspace  # noqa: E402


def _print_report(report: dict, kb_id: str, only: str) -> None:
    recently = report["recently_added"]
    stale = report["stale_nodes"]
    weak = report["weak_nodes"]
    candidates = report["candidate_links"]

    print(f"[kb={kb_id}] Graph Review Report\n")

    if only in ("", "recent"):
        print(f"[RECENT] Recently added memories ({len(recently)}):")
        if recently:
            for r in recently[:10]:
                date = (r.get("created_at") or "")[:10]
                path = r.get("kb_path", "?")
                preview = (r.get("content") or "")[:120].replace("\n", " ")
                print(f"  {date}  {path}")
                print(f"    {preview}")
        else:
            print("  (none)")
        print()

    if only in ("", "stale"):
        print(f"[STALE] Stale nodes — no activity in >{report.get('stale_days', 30)} days ({len(stale)}):")
        if stale:
            for s in stale[:20]:
                last = (s.get("last_activity") or "")[:10]
                print(f"  {s['kb_path']}  (last: {last})")
        else:
            print("  (none)")
        print()

    if only in ("", "weak"):
        print(f"[WEAK] Weakly supported leaf nodes — no memories/chunks/edges ({len(weak)}):")
        if weak:
            for w in weak[:20]:
                print(f"  {w['kb_path']}")
        else:
            print("  (none — all leaf nodes have at least one support record)")
        print()

    if only in ("", "candidates"):
        print(f"[LINKS] Candidate relation edges — shared title words ({len(candidates)}):")
        if candidates:
            for c in candidates[:10]:
                print(f"  {c['a']}")
                print(f"  <-> {c['b']}")
                print(f"      reason: {c['reason']}")
                print()
        else:
            print("  (none found)")
        print()

    if only == "":
        weak_count = len(weak)
        stale_count = len(stale)
        cand_count = len(candidates)
        print(
            f"Summary: {len(recently)} recent | {stale_count} stale | "
            f"{weak_count} weak | {cand_count} candidate link(s)"
        )
        if weak_count:
            print(f"  Action: archive or add doc chunks for {weak_count} weak node(s).")
        if candidates:
            print(f"  Action: consider adding edges via /link-paper-to-kb for {cand_count} candidate pair(s).")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Review graph health: stale, weak, recent nodes and candidate links"
    )
    parser.add_argument(
        "--kb",
        default=workspace.DEFAULT_KB_ID,
        metavar="KB_ID",
    )
    parser.add_argument(
        "--stale-days",
        type=int,
        default=30,
        metavar="N",
        help="Days without activity to consider a node stale (default: 30)",
    )
    parser.add_argument(
        "--recent-days",
        type=int,
        default=7,
        metavar="N",
        help="Days to look back for recent additions (default: 7)",
    )
    parser.add_argument(
        "--only",
        default="",
        choices=["", "recent", "stale", "weak", "candidates"],
        metavar="CATEGORY",
        help="Print only one category of the report",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of formatted text",
    )
    args = parser.parse_args()

    tree_path = workspace.get_tree_path(PROJECT_ROOT, args.kb)
    if not tree_path.exists():
        print(f"ERROR: knowledge_tree.json not found for workspace '{args.kb}'.")
        sys.exit(1)

    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    db_path = workspace.get_index_path(PROJECT_ROOT, args.kb)
    conn = retrieval.open_db(db_path)
    try:
        report = retrieval.review_graph(
            conn, tree,
            stale_days=args.stale_days,
            recent_days=args.recent_days,
        )
    finally:
        conn.close()

    report["stale_days"] = args.stale_days
    report["recent_days"] = args.recent_days

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report, args.kb, args.only)


if __name__ == "__main__":
    main()
