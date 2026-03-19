"""Explicitly rebuild the FTS5 index for a workspace.

Indexes:
  - KB nodes from knowledge_tree.json        (always)
  - Document chunks from docs_dir            (--index-docs flag)
  - Memories are indexed automatically by archive_to_kb.py at archive time.

Usage:
  python build_index.py                      # index nodes for default workspace
  python build_index.py --kb work            # index nodes for 'work' workspace
  python build_index.py --index-docs         # also index doc chunks from docs_dir
  python build_index.py --rebuild            # force full rebuild even if tree unchanged
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import retrieval, workspace  # noqa: E402

_SUPPORTED_SUFFIXES = {".md", ".txt", ".rst"}


def main() -> None:
    """Parse args and rebuild the FTS5 index for the specified workspace."""
    parser = argparse.ArgumentParser(description="Rebuild FTS5 index for a workspace")
    parser.add_argument(
        "--kb",
        default=workspace.DEFAULT_KB_ID,
        metavar="KB_ID",
        help=f"Workspace ID (default: {workspace.DEFAULT_KB_ID})",
    )
    parser.add_argument(
        "--index-docs",
        action="store_true",
        help="Also index document chunks from docs_dir",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force full rebuild even if knowledge_tree.json is unchanged",
    )
    args = parser.parse_args()

    db_path = workspace.get_index_path(PROJECT_ROOT, args.kb)
    conn = retrieval.open_db(db_path)

    # 1. Index KB nodes -------------------------------------------------------
    tree_path = workspace.get_tree_path(PROJECT_ROOT, args.kb)
    if not tree_path.exists():
        print(f"No knowledge_tree.json for workspace '{args.kb}'. Skipping node index.")
    else:
        raw = tree_path.read_text(encoding="utf-8")
        tree_hash = retrieval.compute_hash(raw)
        if not args.rebuild and not retrieval.is_index_stale(conn, tree_path):
            print(f"[OK] Node index is up-to-date for workspace '{args.kb}' (use --rebuild to force).")
        else:
            n = retrieval.index_tree(conn, json.loads(raw), tree_hash)
            print(f"[OK] Indexed {n} KB nodes from workspace '{args.kb}'.")

    # 2. Index document chunks (optional) ------------------------------------
    if args.index_docs:
        docs_dir = workspace.get_docs_dir(PROJECT_ROOT, args.kb)
        if not docs_dir.exists():
            print(f"docs_dir '{docs_dir}' not found. Skipping doc indexing.")
        else:
            indexed_count = 0
            skipped_count = 0
            for f in sorted(docs_dir.rglob("*")):
                if f.suffix.lower() not in _SUPPORTED_SUFFIXES:
                    continue
                try:
                    content = f.read_text(encoding="utf-8")
                    title = f.stem.replace("_", " ").replace("-", " ").title()
                    n = retrieval.index_source(conn, str(f), title, content)
                    if n > 0:
                        indexed_count += 1
                        rel = f.relative_to(PROJECT_ROOT)
                        print(f"  + {rel} ({n} chunks)")
                    else:
                        skipped_count += 1
                except Exception as exc:
                    print(f"  ! {f.name}: {exc}", file=sys.stderr)
            print(
                f"[OK] Docs: {indexed_count} new/updated, {skipped_count} unchanged."
            )

    conn.close()
    print(f"\nIndex: {db_path}")


if __name__ == "__main__":
    main()
