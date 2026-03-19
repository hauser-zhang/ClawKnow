"""Archive typed memory records into a knowledge tree node.

Replaces the old summary-append model with structured, typed memory records.

Each memory has a type (concept/fact/insight/source_note/question/decision),
confidence level, and optional source references.  After writing all records,
the node's summary in knowledge_tree.json is regenerated from the full set of
typed memories for that node — no raw string appending.

Usage (single record):
  archive_to_kb.py "模型架构>MoE" --type fact --content "..." --confidence high

Usage (batch, JSON array):
  archive_to_kb.py "模型架构>MoE" --batch '[{"type":"concept","content":"..."}]'

Usage (regenerate summary only, no new records):
  archive_to_kb.py "模型架构>MoE" --regen-only

All modes accept --kb <kb_id> (default: default workspace).
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import retrieval, workspace  # noqa: E402


def find_node(tree: dict, path: list[str]) -> dict | None:
    """Walk the tree to find a node by path like ['后训练', 'RLHF']."""
    if not path:
        return tree
    for child in tree.get("children", []):
        if child["title"] == path[0]:
            return find_node(child, path[1:])
    return None


def main() -> None:
    """Parse args, write typed memory records, regenerate node summary."""
    parser = argparse.ArgumentParser(
        description="Archive typed memory records to a knowledge tree node"
    )
    parser.add_argument(
        "node_path",
        help='">"-separated node path, e.g. "模型架构>MoE"',
    )
    parser.add_argument(
        "--kb",
        default=workspace.DEFAULT_KB_ID,
        metavar="KB_ID",
        help=f"Workspace ID (default: {workspace.DEFAULT_KB_ID})",
    )
    parser.add_argument(
        "--type",
        dest="memory_type",
        default="fact",
        choices=sorted(retrieval.MEMORY_TYPES),
        help="Memory type for single-record mode (default: fact)",
    )
    parser.add_argument(
        "--content",
        default="",
        help="Memory content string (single-record mode)",
    )
    parser.add_argument(
        "--confidence",
        default="medium",
        choices=["high", "medium", "low"],
        help="Confidence level (default: medium)",
    )
    parser.add_argument(
        "--source",
        dest="sources",
        action="append",
        default=[],
        metavar="REF",
        help="Source reference string, repeatable (e.g. --source 'Paper: Vaswani 2017')",
    )
    parser.add_argument(
        "--batch",
        default="",
        metavar="JSON",
        help=(
            "JSON array of memory dicts. Each dict may have: type, content, "
            "confidence, source_refs (list), author. Overrides --type/--content."
        ),
    )
    parser.add_argument(
        "--regen-only",
        action="store_true",
        help="Regenerate node summary from existing memories without adding new records",
    )
    args = parser.parse_args()

    path = [p.strip() for p in args.node_path.split(">")]
    kb_path_str = " > ".join(path)

    # Load knowledge tree -------------------------------------------------------
    tree_path = workspace.get_tree_path(PROJECT_ROOT, args.kb)
    if not tree_path.exists():
        print(f"ERROR: knowledge_tree.json not found for workspace '{args.kb}'.")
        sys.exit(1)

    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    node = find_node(tree, path)
    if node is None:
        print(f"ERROR: Node path not found: {kb_path_str}")
        print("Available top-level nodes:")
        for child in tree.get("children", []):
            print(f"  - {child['title']}")
        sys.exit(1)

    # Open FTS index ------------------------------------------------------------
    db_path = workspace.get_index_path(PROJECT_ROOT, args.kb)
    conn = retrieval.open_db(db_path)

    # Write new memory records --------------------------------------------------
    written = 0
    if not args.regen_only:
        if args.batch:
            try:
                batch: list[dict] = json.loads(args.batch)
            except json.JSONDecodeError as exc:
                print(f"ERROR: Invalid --batch JSON: {exc}")
                sys.exit(1)
        elif args.content:
            batch = [
                {
                    "type": args.memory_type,
                    "content": args.content,
                    "confidence": args.confidence,
                    "source_refs": args.sources,
                }
            ]
        else:
            print("ERROR: Provide --content, --batch, or --regen-only.")
            sys.exit(1)

        for item in batch:
            content = item.get("content", "").strip()
            if not content:
                continue
            retrieval.write_memory(
                conn,
                kb_path=kb_path_str,
                content=content,
                memory_type=item.get("type", "fact"),
                source_refs=item.get("source_refs") or [],
                author=item.get("author", "claude"),
                confidence=item.get("confidence", "medium"),
            )
            written += 1

        if written:
            print(f"[kb={args.kb}] Wrote {written} memory record(s) to '{kb_path_str}'")

    # Regenerate node summary from all typed memories ---------------------------
    new_summary = retrieval.regen_node_summary(conn, kb_path_str)
    if new_summary:
        node["summary"] = new_summary
        tree_path.write_text(
            json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            f"[kb={args.kb}] Summary regenerated for '{kb_path_str}'"
            f" ({len(new_summary)} chars, {new_summary.count(chr(10)) + 1} lines)"
        )
    elif args.regen_only:
        print(
            f"[kb={args.kb}] No typed memories found for '{kb_path_str}'."
            " Nothing to regenerate."
        )

    # Re-index fts_nodes to reflect the updated summary -------------------------
    if new_summary:
        try:
            raw = tree_path.read_text(encoding="utf-8")
            retrieval.index_tree(conn, json.loads(raw), retrieval.compute_hash(raw))
        except Exception as exc:  # noqa: BLE001
            print(f"[index] Warning: failed to re-index nodes: {exc}", file=sys.stderr)

    conn.close()

    # Feishu sync reminder ------------------------------------------------------
    if node.get("obj_token"):
        print(
            "  Note: This node is synced to Feishu."
            " Run /sync-wiki to push the updated summary."
        )


if __name__ == "__main__":
    main()
