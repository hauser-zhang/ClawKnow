"""FTS5-based two-stage retrieval for ClawKnow knowledge bases.

Architecture:
    Stage 1 — FTS5 search over KB nodes (title + summary indexed).
    Stage 2 — For top-K matched nodes, retrieve supporting chunks and memories.
    Ranking  — BM25 (FTS5 built-in); recency preserved in metadata.

No external model APIs. Uses only Python stdlib sqlite3.

Schema (all in workspaces/<kb_id>/kb_index.db):
    fts_nodes    — FTS5: title + summary indexed; kb_path + tokens unindexed
    fts_chunks   — FTS5: content indexed; provenance columns unindexed
    fts_memories — FTS5: content indexed; kb_path + archived_at unindexed
    sources      — Regular table: file metadata + content_hash for change detection
    index_state  — Regular table: tree_hash for auto-rebuild detection

Extension points (intentionally disabled — do NOT enable without explicit user request):
    _EMBED_ENABLED   = False   # sentence-transformer embedding for semantic search
    _RERANK_ENABLED  = False   # cross-encoder reranking pass over FTS5 results
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Extension points — intentionally disabled. See module docstring.
# ---------------------------------------------------------------------------
_EMBED_ENABLED: bool = False   # noqa: F841 — semantic embedding reranking
_RERANK_ENABLED: bool = False  # noqa: F841 — cross-encoder reranking

# ---------------------------------------------------------------------------
# Memory type registry
# ---------------------------------------------------------------------------

#: Valid values for the ``type`` field of a memory record.
MEMORY_TYPES: frozenset[str] = frozenset(
    {"concept", "fact", "insight", "source_note", "question", "decision"}
)

_TYPE_LABELS: dict[str, str] = {
    "concept": "概念",
    "fact": "事实",
    "insight": "洞察",
    "source_note": "来源",
    "question": "待解答",
    "decision": "决策",
}

# Display order for regen_node_summary: foundational types first.
_TYPE_ORDER: list[str] = [
    "concept", "fact", "insight", "source_note", "question", "decision"
]

# ---------------------------------------------------------------------------
# Schema DDL — executed once on db open
# ---------------------------------------------------------------------------
_DDL_STATEMENTS = [
    "PRAGMA journal_mode=WAL",
    # FTS5 node index: title + summary are full-text indexed;
    # kb_path and token fields are stored-but-not-indexed (UNINDEXED).
    """CREATE VIRTUAL TABLE IF NOT EXISTS fts_nodes USING fts5(
        title,
        summary,
        kb_path     UNINDEXED,
        node_token  UNINDEXED,
        obj_token   UNINDEXED,
        updated_at  UNINDEXED,
        tokenize='unicode61'
    )""",
    # FTS5 document chunk index: content is full-text indexed;
    # provenance columns (chunk_id, source_id, …) are stored only.
    """CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5(
        content,
        chunk_id     UNINDEXED,
        source_id    UNINDEXED,
        source_title UNINDEXED,
        source_path  UNINDEXED,
        kb_path      UNINDEXED,
        chunk_index  UNINDEXED,
        created_at   UNINDEXED,
        tokenize='unicode61'
    )""",
    # FTS5 memory index: archived discussion highlights.
    """CREATE VIRTUAL TABLE IF NOT EXISTS fts_memories USING fts5(
        content,
        memory_id   UNINDEXED,
        kb_path     UNINDEXED,
        archived_at UNINDEXED,
        tokenize='unicode61'
    )""",
    # Regular table: document source metadata for change-detection.
    """CREATE TABLE IF NOT EXISTS sources (
        source_id    TEXT PRIMARY KEY,
        file_path    TEXT NOT NULL UNIQUE,
        title        TEXT NOT NULL DEFAULT '',
        content_hash TEXT NOT NULL DEFAULT '',
        chunk_count  INTEGER NOT NULL DEFAULT 0,
        indexed_at   TEXT NOT NULL
    )""",
    # Regular table: tracks tree_hash so search_kb.py can auto-rebuild.
    """CREATE TABLE IF NOT EXISTS index_state (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
    # Regular table: typed memory records (source of truth for structured data).
    # fts_memories is the search index; this table is the authoritative store.
    """CREATE TABLE IF NOT EXISTS memories (
        memory_id   TEXT PRIMARY KEY,
        type        TEXT NOT NULL DEFAULT 'fact',
        content     TEXT NOT NULL,
        kb_path     TEXT NOT NULL,
        source_refs TEXT NOT NULL DEFAULT '[]',
        author      TEXT NOT NULL DEFAULT 'claude',
        confidence  TEXT NOT NULL DEFAULT 'medium',
        created_at  TEXT NOT NULL,
        updated_at  TEXT
    )""",
]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def compute_hash(text: str) -> str:
    """Return the SHA-256 hex digest of *text* (UTF-8 encoded)."""
    return hashlib.sha256(text.encode()).hexdigest()


_sha256 = compute_hash  # internal alias used within this module


def _fts_query(query: str) -> str:
    """Convert a natural-language query to a safe FTS5 OR-phrase query.

    Each whitespace-separated token is double-quoted so it is treated as an
    exact phrase by FTS5 (prevents injection of FTS5 syntax operators).
    Tokens are joined with OR for broad recall.

    Example: "MoE 路由" → '"MoE" OR "路由"'
    """
    tokens = [t.strip() for t in query.split() if t.strip()]
    if not tokens:
        return ""
    # Escape any embedded double-quotes in the token itself
    escaped = [f'"{t.replace(chr(34), chr(34) + chr(34))}"' for t in tokens]
    return " OR ".join(escaped)


def _chunk_text(text: str, max_chars: int = 600) -> list[str]:
    """Split *text* into chunks at paragraph boundaries.

    Merges consecutive short paragraphs until *max_chars* is reached, then
    starts a new chunk. Single paragraphs longer than *max_chars* are kept
    as-is (no mid-paragraph split).
    """
    paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if not current:
            current = para
        elif len(current) + 2 + len(para) <= max_chars:
            current += "\n\n" + para
        else:
            chunks.append(current)
            current = para
    if current:
        chunks.append(current)
    return chunks


def _walk_tree(node: dict, path: list[str] | None = None) -> list[dict[str, Any]]:
    """Recursively yield flat records from a knowledge_tree.json node.

    Each record is a dict with:
        path  — list[str] representing the full path from root to this node
        node  — the original node dict
    """
    path = (path or []) + [node.get("title", "")]
    rows: list[dict[str, Any]] = [{"path": path, "node": node}]
    for child in node.get("children", []):
        rows.extend(_walk_tree(child, path))
    return rows


# ---------------------------------------------------------------------------
# DB connection + schema bootstrap
# ---------------------------------------------------------------------------


def open_db(db_path: Path) -> sqlite3.Connection:
    """Open (or create) the index database and ensure the schema exists.

    Safe to call on an existing database — all DDL statements are IF NOT EXISTS.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    for stmt in _DDL_STATEMENTS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # table / PRAGMA already exists
    conn.commit()


# ---------------------------------------------------------------------------
# Index building — KB nodes
# ---------------------------------------------------------------------------


def index_tree(conn: sqlite3.Connection, tree: dict, tree_hash: str = "") -> int:
    """Rebuild *fts_nodes* from a knowledge_tree.json dict.

    Clears all existing node entries, then re-inserts every node found by a
    recursive walk of the tree. Records *tree_hash* in index_state so that
    callers can detect when the index is stale.

    Returns the number of nodes indexed.
    """
    conn.execute("DELETE FROM fts_nodes")
    now = _now()
    entries = _walk_tree(tree)
    for entry in entries:
        node = entry["node"]
        kb_path = " > ".join(entry["path"])
        conn.execute(
            "INSERT INTO fts_nodes"
            "(title, summary, kb_path, node_token, obj_token, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                node.get("title", ""),
                node.get("summary", ""),
                kb_path,
                node.get("node_token", ""),
                node.get("obj_token", ""),
                now,
            ),
        )
    if tree_hash:
        conn.execute(
            "INSERT OR REPLACE INTO index_state(key, value) VALUES ('tree_hash', ?)",
            (tree_hash,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_state(key, value) VALUES ('tree_indexed_at', ?)",
            (now,),
        )
    conn.commit()
    return len(entries)


# ---------------------------------------------------------------------------
# Index building — document chunks
# ---------------------------------------------------------------------------


def index_source(
    conn: sqlite3.Connection,
    file_path: str,
    title: str,
    content: str,
    kb_path: str = "",
) -> int:
    """Chunk and index a source document into *fts_chunks*.

    Skips re-indexing if *content* has not changed since the last call
    (detected via SHA-256 hash stored in the *sources* table).

    Returns the number of new chunks indexed (0 if content unchanged).
    """
    source_id = _sha256(file_path)
    content_hash = _sha256(content)

    existing = conn.execute(
        "SELECT content_hash FROM sources WHERE source_id = ?", (source_id,)
    ).fetchone()
    if existing and existing["content_hash"] == content_hash:
        return 0  # content unchanged — skip

    # Remove stale chunks for this source
    conn.execute("DELETE FROM fts_chunks WHERE source_id = ?", (source_id,))

    chunks = _chunk_text(content)
    now = _now()
    for i, chunk in enumerate(chunks):
        chunk_id = _sha256(f"{source_id}:{i}")
        conn.execute(
            "INSERT INTO fts_chunks"
            "(content, chunk_id, source_id, source_title, source_path,"
            " kb_path, chunk_index, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (chunk, chunk_id, source_id, title, file_path, kb_path, i, now),
        )

    conn.execute(
        "INSERT OR REPLACE INTO sources"
        "(source_id, file_path, title, content_hash, chunk_count, indexed_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (source_id, file_path, title, content_hash, len(chunks), now),
    )
    conn.commit()
    return len(chunks)


# ---------------------------------------------------------------------------
# Index building — archived memories
# ---------------------------------------------------------------------------


def index_memory(
    conn: sqlite3.Connection,
    kb_path: str,
    content: str,
    archived_at: str = "",
) -> str:
    """Insert an archived discussion highlight into *fts_memories*.

    Uses INSERT OR IGNORE so calling this function repeatedly with the same
    content is idempotent.

    Returns the memory_id (SHA-256 derived stable identifier).
    """
    archived_at = archived_at or _now()
    memory_id = _sha256(f"{kb_path}:{archived_at}:{content[:64]}")
    conn.execute(
        "INSERT OR IGNORE INTO fts_memories"
        "(content, memory_id, kb_path, archived_at)"
        " VALUES (?, ?, ?, ?)",
        (content, memory_id, kb_path, archived_at),
    )
    conn.commit()
    return memory_id


def write_memory(
    conn: sqlite3.Connection,
    kb_path: str,
    content: str,
    memory_type: str = "fact",
    source_refs: list[str] | None = None,
    author: str = "claude",
    confidence: str = "medium",
) -> str:
    """Write a typed memory record and index it for full-text search.

    Inserts into both the ``memories`` structured table and ``fts_memories``
    search index.  Uses INSERT OR IGNORE so duplicate content at the same
    path within the same second is silently skipped.

    *memory_type* must be one of :data:`MEMORY_TYPES`; unknown values are
    coerced to ``'fact'``.

    Returns the stable ``memory_id`` (SHA-256 derived).
    """
    if memory_type not in MEMORY_TYPES:
        memory_type = "fact"
    now = _now()
    refs_json = json.dumps(source_refs or [], ensure_ascii=False)
    memory_id = _sha256(f"{kb_path}:{now}:{content[:64]}")
    conn.execute(
        "INSERT OR IGNORE INTO memories"
        "(memory_id, type, content, kb_path, source_refs, author, confidence, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (memory_id, memory_type, content, kb_path, refs_json, author, confidence, now),
    )
    # Mirror into fts_memories so existing search_memories() queries still work.
    conn.execute(
        "INSERT OR IGNORE INTO fts_memories"
        "(content, memory_id, kb_path, archived_at)"
        " VALUES (?, ?, ?, ?)",
        (content, memory_id, kb_path, now),
    )
    conn.commit()
    return memory_id


def list_memories_for_node(
    conn: sqlite3.Connection,
    kb_path: str,
    types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return all typed memory records linked to *kb_path*.

    If *types* is given, only memories of those types are returned.
    Results are ordered by creation time (oldest first).

    Each dict has keys: memory_id, type, content, kb_path, source_refs
    (list), author, confidence, created_at, updated_at.
    """
    sql = (
        "SELECT memory_id, type, content, kb_path, source_refs,"
        " author, confidence, created_at, updated_at"
        " FROM memories WHERE kb_path = ?"
    )
    params: list[Any] = [kb_path]
    if types:
        placeholders = ",".join("?" * len(types))
        sql += f" AND type IN ({placeholders})"
        params.extend(types)
    sql += " ORDER BY created_at"
    rows = conn.execute(sql, params).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        try:
            d["source_refs"] = json.loads(d.get("source_refs") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["source_refs"] = []
        results.append(d)
    return results


def regen_node_summary(conn: sqlite3.Connection, kb_path: str) -> str:
    """Regenerate a structured summary from all typed memories for *kb_path*.

    Groups memories by type in display order and emits one
    ``[类型标签] content`` line per memory.  Returns an empty string if no
    typed memories exist for this node.

    This function never calls an external API — formatting is deterministic.
    """
    memories = list_memories_for_node(conn, kb_path)
    if not memories:
        return ""
    by_type: dict[str, list[str]] = {t: [] for t in _TYPE_ORDER}
    for m in memories:
        mtype = m.get("type", "fact")
        if mtype in by_type:
            by_type[mtype].append(m["content"])
    parts: list[str] = []
    for mtype in _TYPE_ORDER:
        label = _TYPE_LABELS.get(mtype, mtype)
        for item in by_type[mtype]:
            parts.append(f"[{label}] {item}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Search — individual FTS5 table queries
# ---------------------------------------------------------------------------


def search_nodes(
    conn: sqlite3.Connection,
    query: str,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """FTS5 BM25 search over KB node titles and summaries.

    BM25 scores from SQLite are negative floats; lower (more negative) means
    a better match. Results are returned in ascending score order (best first).

    Returns a list of dicts with keys:
        kb_path, title, summary, node_token, obj_token, updated_at, score
    """
    if not query.strip():
        return []
    fts_q = _fts_query(query)
    if not fts_q:
        return []
    try:
        rows = conn.execute(
            "SELECT kb_path, title, summary, node_token, obj_token, updated_at,"
            " bm25(fts_nodes) AS score"
            " FROM fts_nodes"
            " WHERE fts_nodes MATCH ?"
            " ORDER BY score"
            " LIMIT ?",
            (fts_q, top_k),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []  # FTS5 unavailable or malformed query


def search_chunks(
    conn: sqlite3.Connection,
    query: str,
    kb_path_filter: str | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """FTS5 BM25 search over document chunks.

    If *kb_path_filter* is set, only chunks whose kb_path contains that string
    are returned (post-filter; FTS5 UNINDEXED columns are scanned linearly).

    Returns dicts with keys:
        chunk_id, source_id, source_title, source_path,
        kb_path, content, chunk_index, created_at, score
    """
    if not query.strip():
        return []
    fts_q = _fts_query(query)
    if not fts_q:
        return []
    try:
        # Over-fetch to allow for kb_path post-filtering
        fetch_limit = top_k * 4 if kb_path_filter else top_k
        rows = conn.execute(
            "SELECT chunk_id, source_id, source_title, source_path,"
            " kb_path, content, chunk_index, created_at,"
            " bm25(fts_chunks) AS score"
            " FROM fts_chunks"
            " WHERE fts_chunks MATCH ?"
            " ORDER BY score"
            " LIMIT ?",
            (fts_q, fetch_limit),
        ).fetchall()
        results = [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []

    if kb_path_filter:
        results = [r for r in results if kb_path_filter in r.get("kb_path", "")]
    return results[:top_k]


def search_memories(
    conn: sqlite3.Connection,
    query: str,
    kb_path_filter: str | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """FTS5 BM25 search over archived memories.

    If *kb_path_filter* is set, only memories whose kb_path contains that string
    are returned.

    Returns dicts with keys:
        memory_id, kb_path, content, archived_at, score,
        memory_type (if typed record exists), confidence (if typed)
    """
    if not query.strip():
        return []
    fts_q = _fts_query(query)
    if not fts_q:
        return []
    try:
        fetch_limit = top_k * 4 if kb_path_filter else top_k
        rows = conn.execute(
            "SELECT memory_id, kb_path, content, archived_at,"
            " bm25(fts_memories) AS score"
            " FROM fts_memories"
            " WHERE fts_memories MATCH ?"
            " ORDER BY score"
            " LIMIT ?",
            (fts_q, fetch_limit),
        ).fetchall()
        results = [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []

    if kb_path_filter:
        results = [r for r in results if kb_path_filter in r.get("kb_path", "")]
    results = results[:top_k]

    # Enrich with typed metadata from the memories table (best-effort).
    for r in results:
        mid = r.get("memory_id", "")
        if mid:
            row = conn.execute(
                "SELECT type, confidence FROM memories WHERE memory_id = ?", (mid,)
            ).fetchone()
            if row:
                r["memory_type"] = row["type"]
                r["confidence"] = row["confidence"]

    return results


# ---------------------------------------------------------------------------
# Two-stage retrieval
# ---------------------------------------------------------------------------


def two_stage_search(
    conn: sqlite3.Connection,
    query: str,
    top_nodes: int = 5,
    top_chunks_per_node: int = 3,
    top_memories_per_node: int = 3,
) -> dict[str, Any]:
    """Two-stage retrieval: find relevant KB nodes, then fetch supporting evidence.

    Stage 1: FTS5 BM25 search over *fts_nodes* (title + summary).
    Stage 2: For each top-K node, retrieve associated chunks and memories.
             A global pass (without node filter) also runs to catch orphaned
             chunks/memories not yet linked to a KB node.

    Returns a dict:
        query         — the original query string
        nodes         — list[dict] — matched KB nodes (kb_path, title, summary, score, …)
        chunks        — list[dict] — supporting document chunks (content, provenance, score)
        memories      — list[dict] — supporting archived memories (content, kb_path, score)
        has_kb_nodes  — bool — True if any KB nodes matched
        has_chunks    — bool — True if any chunks found
        has_memories  — bool — True if any memories found
    """
    nodes = search_nodes(conn, query, top_k=top_nodes)

    chunks: list[dict] = []
    memories: list[dict] = []
    seen_chunks: set[str] = set()
    seen_memories: set[str] = set()

    # Per-node evidence retrieval (Stage 2)
    for node in nodes:
        node_path = node["kb_path"]
        for c in search_chunks(
            conn, query, kb_path_filter=node_path, top_k=top_chunks_per_node
        ):
            cid = c.get("chunk_id", "")
            if cid and cid not in seen_chunks:
                seen_chunks.add(cid)
                chunks.append(c)
        for m in search_memories(
            conn, query, kb_path_filter=node_path, top_k=top_memories_per_node
        ):
            mid = m.get("memory_id", "")
            if mid and mid not in seen_memories:
                seen_memories.add(mid)
                memories.append(m)

    # Global pass — catch chunks / memories not linked to matched nodes
    for c in search_chunks(conn, query, top_k=top_chunks_per_node * 2):
        cid = c.get("chunk_id", "")
        if cid and cid not in seen_chunks:
            seen_chunks.add(cid)
            chunks.append(c)
    for m in search_memories(conn, query, top_k=top_memories_per_node * 2):
        mid = m.get("memory_id", "")
        if mid and mid not in seen_memories:
            seen_memories.add(mid)
            memories.append(m)

    cap = top_nodes * max(top_chunks_per_node, top_memories_per_node)
    return {
        "query": query,
        "nodes": nodes,
        "chunks": chunks[:cap],
        "memories": memories[:cap],
        "has_kb_nodes": bool(nodes),
        "has_chunks": bool(chunks),
        "has_memories": bool(memories),
    }


# ---------------------------------------------------------------------------
# Index freshness utilities
# ---------------------------------------------------------------------------


def get_tree_hash_in_index(conn: sqlite3.Connection) -> str:
    """Return the tree_hash stored in index_state, or '' if absent."""
    try:
        row = conn.execute(
            "SELECT value FROM index_state WHERE key = 'tree_hash'"
        ).fetchone()
        return row["value"] if row else ""
    except sqlite3.OperationalError:
        return ""


def is_index_stale(conn: sqlite3.Connection, tree_path: Path) -> bool:
    """Return True if *knowledge_tree.json* has changed since the last index build.

    Compares the SHA-256 of the file on disk against the hash recorded in
    *index_state* at the time of the last ``index_tree()`` call.
    Returns False if *tree_path* does not exist.
    """
    if not tree_path.exists():
        return False
    current_hash = _sha256(tree_path.read_text(encoding="utf-8"))
    indexed_hash = get_tree_hash_in_index(conn)
    return current_hash != indexed_hash
