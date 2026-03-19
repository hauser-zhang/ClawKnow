"""Search the knowledge base using FTS5 two-stage retrieval.

Auto-rebuilds the node index when knowledge_tree.json has changed since the
last build.  Run build_index.py explicitly to also index document chunks.
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import retrieval, workspace  # noqa: E402


def _auto_rebuild_if_stale(project_root: Path, kb_id: str) -> None:
    """Rebuild the FTS5 node index if knowledge_tree.json has changed."""
    tree_path = workspace.get_tree_path(project_root, kb_id)
    if not tree_path.exists():
        return
    db_path = workspace.get_index_path(project_root, kb_id)
    conn = retrieval.open_db(db_path)
    try:
        if retrieval.is_index_stale(conn, tree_path):
            raw = tree_path.read_text(encoding="utf-8")
            tree_hash = retrieval.compute_hash(raw)
            n = retrieval.index_tree(conn, json.loads(raw), tree_hash)
            print(
                f"[index] Auto-rebuilt: {n} nodes indexed from '{kb_id}'.",
                file=sys.stderr,
            )
    finally:
        conn.close()


def _print_results(result: dict, kb_id: str) -> None:
    """Print two-stage search results in a format Claude can parse."""
    query = result["query"]
    nodes = result["nodes"]
    chunks = result["chunks"]
    memories = result["memories"]

    if not nodes and not chunks and not memories:
        print(f"[kb={kb_id}] 未找到与 '{query}' 相关的内容。")
        print("建议：可联网搜索补充，或先运行 plan-wiki 建立知识库。")
        return

    print(f"[kb={kb_id}] 查询: '{query}'\n")

    # Stage 1 — KB node matches
    if nodes:
        print(f"[KB] 知识库节点 ({len(nodes)} 个匹配):\n")
        for n in nodes:
            feishu_flag = "  [已同步飞书]" if n.get("node_token") else ""
            print(f"  路径: {n['kb_path']}{feishu_flag}")
            if n.get("summary"):
                preview = n["summary"][:300].replace("\n", " ")
                print(f"  摘要: {preview}")
            print()

    # Stage 2a — Document chunk evidence
    if chunks:
        print(f"[DOC] 文档片段 ({len(chunks)} 条):\n")
        for c in chunks:
            src = c.get("source_title") or c.get("source_path", "?")
            linked = c.get("kb_path") or "(未关联节点)"
            print(f"  来源: {src}  节点: {linked}")
            preview = c["content"][:300].replace("\n", " ")
            print(f"  内容: {preview}")
            print()

    # Stage 2b — Archived memory evidence
    if memories:
        print(f"[MEM] 归档记忆 ({len(memories)} 条):\n")
        for m in memories:
            date_str = (m.get("archived_at") or "")[:10]
            mtype = m.get("memory_type", "")
            conf = m.get("confidence", "")
            type_tag = f"  [{mtype}]" if mtype else ""
            conf_tag = f" ({conf})" if conf else ""
            print(f"  节点: {m['kb_path']}{type_tag}{conf_tag}  日期: {date_str}")
            preview = m["content"][:300].replace("\n", " ")
            print(f"  内容: {preview}")
            print()

    # Signal knowledge gaps
    if not result["has_kb_nodes"]:
        print(f"[GAP] 知识库中无节点与 '{query}' 匹配 — 建议联网搜索补充。")


def main() -> None:
    """Parse args and run FTS5 two-stage search against the workspace knowledge base."""
    parser = argparse.ArgumentParser(description="Search knowledge base (FTS5 two-stage)")
    parser.add_argument("query", nargs="+", help="Search query keywords")
    parser.add_argument(
        "--kb",
        default=workspace.DEFAULT_KB_ID,
        metavar="KB_ID",
        help=f"Workspace ID (default: {workspace.DEFAULT_KB_ID})",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=5,
        metavar="N",
        help="Max KB nodes to return (default: 5)",
    )
    args = parser.parse_args()
    query = " ".join(args.query)

    tree_path = workspace.get_tree_path(PROJECT_ROOT, args.kb)
    if not tree_path.exists():
        print(f"Knowledge tree not found for workspace '{args.kb}' ({tree_path}).")
        print("Run plan-wiki first to build the knowledge tree.")
        sys.exit(0)

    _auto_rebuild_if_stale(PROJECT_ROOT, args.kb)

    db_path = workspace.get_index_path(PROJECT_ROOT, args.kb)
    conn = retrieval.open_db(db_path)
    try:
        result = retrieval.two_stage_search(conn, query, top_nodes=args.top)
    finally:
        conn.close()

    _print_results(result, args.kb)


if __name__ == "__main__":
    main()
