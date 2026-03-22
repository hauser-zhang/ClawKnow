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
    # FTS5 paper index: academic papers ingested for reading and discussion.
    # title + abstract_summary + method_summary are full-text indexed.
    """CREATE VIRTUAL TABLE IF NOT EXISTS fts_papers USING fts5(
        title,
        abstract_summary,
        method_summary,
        paper_id  UNINDEXED,
        year      UNINDEXED,
        authors   UNINDEXED,
        venue     UNINDEXED,
        doi       UNINDEXED,
        arxiv_id  UNINDEXED,
        status    UNINDEXED,
        added_at  UNINDEXED,
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
    # Regular table: unified edge store for all relationship types.
    # src/dst can be kb_node paths or paper_ids; edge_type encodes semantics.
    # Valid edge_types: contains, related_to, depends_on, compares_with,
    #                   derived_from, updated_by, cites
    """CREATE TABLE IF NOT EXISTS edges (
        edge_id    TEXT PRIMARY KEY,
        src_id     TEXT NOT NULL,
        src_type   TEXT NOT NULL DEFAULT 'kb_node',
        dst_id     TEXT NOT NULL,
        dst_type   TEXT NOT NULL DEFAULT 'kb_node',
        edge_type  TEXT NOT NULL,
        weight     REAL NOT NULL DEFAULT 1.0,
        note       TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
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


# ---------------------------------------------------------------------------
# Paper indexing and retrieval
# ---------------------------------------------------------------------------

#: Valid values for a paper's ``status`` field.
PAPER_STATUSES: frozenset[str] = frozenset({"reading", "read", "reviewed"})

#: Valid edge types for the ``edges`` table.
EDGE_TYPES: frozenset[str] = frozenset(
    {"contains", "related_to", "depends_on", "compares_with", "derived_from", "updated_by", "cites"}
)


def index_paper(conn: sqlite3.Connection, paper: dict[str, Any]) -> str:
    """Insert or replace a paper record into *fts_papers*.

    *paper* must have at least ``paper_id`` and ``title``.
    Other fields are optional and default to empty strings.

    Returns *paper_id*.
    """
    paper_id = paper.get("paper_id", "")
    if not paper_id:
        raise ValueError("paper must have a non-empty 'paper_id'")
    authors = paper.get("authors", [])
    authors_str = ", ".join(authors) if isinstance(authors, list) else str(authors)
    # Remove stale entry first (FTS5 DELETE + INSERT = UPDATE)
    conn.execute("DELETE FROM fts_papers WHERE paper_id = ?", (paper_id,))
    conn.execute(
        "INSERT INTO fts_papers"
        "(title, abstract_summary, method_summary, paper_id, year, authors,"
        " venue, doi, arxiv_id, status, added_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            paper.get("title", ""),
            paper.get("abstract_summary", ""),
            paper.get("method_summary", ""),
            paper_id,
            str(paper.get("year", "")),
            authors_str,
            paper.get("venue", ""),
            paper.get("doi", ""),
            paper.get("arxiv_id", ""),
            paper.get("status", "reading"),
            paper.get("added_at", _now()),
        ),
    )
    conn.commit()
    return paper_id


def search_papers(
    conn: sqlite3.Connection,
    query: str,
    top_k: int = 5,
    status_filter: str | None = None,
) -> list[dict[str, Any]]:
    """FTS5 BM25 search over paper title, abstract_summary, and method_summary.

    If *status_filter* is set, only papers with that status are returned
    (post-filter on the UNINDEXED ``status`` column).

    Returns dicts with keys:
        paper_id, title, abstract_summary, method_summary, year, authors,
        venue, doi, arxiv_id, status, added_at, score
    """
    if not query.strip():
        return []
    fts_q = _fts_query(query)
    if not fts_q:
        return []
    try:
        fetch_limit = top_k * 4 if status_filter else top_k
        rows = conn.execute(
            "SELECT paper_id, title, abstract_summary, method_summary, year, authors,"
            " venue, doi, arxiv_id, status, added_at, bm25(fts_papers) AS score"
            " FROM fts_papers"
            " WHERE fts_papers MATCH ?"
            " ORDER BY score"
            " LIMIT ?",
            (fts_q, fetch_limit),
        ).fetchall()
        results = [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    if status_filter:
        results = [r for r in results if r.get("status") == status_filter]
    return results[:top_k]


def list_papers(
    conn: sqlite3.Connection,
    status_filter: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return all indexed papers, optionally filtered by status.

    Results ordered by added_at descending (most recent first).
    Each dict has the same keys as ``search_papers`` results (without score).
    """
    if status_filter:
        rows = conn.execute(
            "SELECT paper_id, title, abstract_summary, method_summary, year, authors,"
            " venue, doi, arxiv_id, status, added_at"
            " FROM fts_papers WHERE status = ?"
            " ORDER BY added_at DESC LIMIT ?",
            (status_filter, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT paper_id, title, abstract_summary, method_summary, year, authors,"
            " venue, doi, arxiv_id, status, added_at"
            " FROM fts_papers"
            " ORDER BY added_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Edge management (unified: kb_node↔kb_node, paper↔kb_node, paper↔paper)
# ---------------------------------------------------------------------------


def write_edge(
    conn: sqlite3.Connection,
    src_id: str,
    dst_id: str,
    edge_type: str,
    src_type: str = "kb_node",
    dst_type: str = "kb_node",
    weight: float = 1.0,
    note: str = "",
) -> str:
    """Insert an edge record into the ``edges`` table.

    Uses INSERT OR IGNORE so calling with identical (src_id, dst_id, edge_type)
    twice is safe — the second call is silently skipped.

    *edge_type* should be one of :data:`EDGE_TYPES`; unrecognised values are
    stored as-is.

    Returns the ``edge_id`` (SHA-256 derived stable identifier).
    """
    now = _now()
    edge_id = _sha256(f"{src_type}:{src_id}:{edge_type}:{dst_type}:{dst_id}")
    conn.execute(
        "INSERT OR IGNORE INTO edges"
        "(edge_id, src_id, src_type, dst_id, dst_type, edge_type, weight, note, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (edge_id, src_id, src_type, dst_id, dst_type, edge_type, weight, note, now),
    )
    conn.commit()
    return edge_id


def list_edges(
    conn: sqlite3.Connection,
    node_id: str | None = None,
    edge_type: str | None = None,
) -> list[dict[str, Any]]:
    """Return edges, optionally filtered by node_id (src or dst) and/or edge_type.

    Each dict has: edge_id, src_id, src_type, dst_id, dst_type, edge_type,
                   weight, note, created_at.
    """
    conditions: list[str] = []
    params: list[Any] = []
    if node_id is not None:
        conditions.append("(src_id = ? OR dst_id = ?)")
        params.extend([node_id, node_id])
    if edge_type is not None:
        conditions.append("edge_type = ?")
        params.append(edge_type)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"SELECT edge_id, src_id, src_type, dst_id, dst_type, edge_type, weight, note, created_at"
        f" FROM edges {where} ORDER BY created_at",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def delete_edge(conn: sqlite3.Connection, edge_id: str) -> bool:
    """Delete an edge by its edge_id. Returns True if a row was deleted."""
    cur = conn.execute("DELETE FROM edges WHERE edge_id = ?", (edge_id,))
    conn.commit()
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Graph export helpers
# ---------------------------------------------------------------------------


def export_graph(
    conn: sqlite3.Connection,
    tree: dict[str, Any],
) -> dict[str, Any]:
    """Build an in-memory graph dict from the knowledge tree and edge table.

    Returns:
        {
            "nodes": [{"id": kb_path, "type": "kb_node"|"paper", "label": title,
                        "summary": ..., "node_token": ..., "obj_token": ...}],
            "edges": [{"edge_id": ..., "src": ..., "src_type": ..., "dst": ...,
                        "dst_type": ..., "type": ..., "weight": ..., "note": ...}]
        }

    Nodes are generated from:
      - The knowledge tree (type="kb_node"), with a synthetic ``contains`` edge
        from parent to each child.
      - Papers indexed in fts_papers (type="paper").

    Edges are generated from the ``edges`` table.
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_edges: set[str] = set()

    # Walk tree → kb_node entries + contains edges
    def _walk(node: dict[str, Any], parent_path: str | None = None, path: list[str] | None = None) -> None:
        p = (path or []) + [node.get("title", "")]
        kb_path = " > ".join(p)
        nodes.append({
            "id": kb_path,
            "type": "kb_node",
            "label": node.get("title", ""),
            "summary": node.get("summary", ""),
            "node_token": node.get("node_token", ""),
            "obj_token": node.get("obj_token", ""),
        })
        if parent_path is not None:
            eid = _sha256(f"contains:{parent_path}:{kb_path}")
            if eid not in seen_edges:
                seen_edges.add(eid)
                edges.append({
                    "edge_id": eid,
                    "src": parent_path,
                    "src_type": "kb_node",
                    "dst": kb_path,
                    "dst_type": "kb_node",
                    "type": "contains",
                    "weight": 1.0,
                    "note": "tree structure",
                })
        for child in node.get("children", []):
            _walk(child, kb_path, p)

    _walk(tree)

    # Paper entries
    try:
        paper_rows = conn.execute(
            "SELECT paper_id, title, abstract_summary, year, authors, status FROM fts_papers"
        ).fetchall()
        for row in paper_rows:
            nodes.append({
                "id": row["paper_id"],
                "type": "paper",
                "label": row["title"],
                "summary": row["abstract_summary"],
                "year": row["year"],
                "authors": row["authors"],
                "status": row["status"],
            })
    except sqlite3.OperationalError:
        pass  # table may not exist yet

    # Edges from the edges table
    try:
        edge_rows = conn.execute(
            "SELECT edge_id, src_id, src_type, dst_id, dst_type, edge_type, weight, note"
            " FROM edges ORDER BY created_at"
        ).fetchall()
        for row in edge_rows:
            eid = row["edge_id"]
            if eid not in seen_edges:
                seen_edges.add(eid)
                edges.append({
                    "edge_id": eid,
                    "src": row["src_id"],
                    "src_type": row["src_type"],
                    "dst": row["dst_id"],
                    "dst_type": row["dst_type"],
                    "type": row["edge_type"],
                    "weight": row["weight"],
                    "note": row["note"],
                })
    except sqlite3.OperationalError:
        pass

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# Graph review helpers
# ---------------------------------------------------------------------------


def review_graph(
    conn: sqlite3.Connection,
    tree: dict[str, Any],
    stale_days: int = 30,
    recent_days: int = 7,
) -> dict[str, Any]:
    """Analyse the graph and return a review report dict.

    Returns:
        {
            "recently_added": [{"kb_path": ..., "created_at": ..., "content": ...}],
            "stale_nodes":    [{"kb_path": ..., "last_activity": ...}],
            "weak_nodes":     [{"kb_path": ..., "title": ...}],
            "candidate_links": [{"a": ..., "b": ..., "reason": ...}]
        }

    - **recently_added**: memories created within *recent_days* (from ``memories`` table).
    - **stale_nodes**: KB nodes where no memory has been written in *stale_days* days.
    - **weak_nodes**: KB leaf nodes with no typed memories, no doc chunks, and no paper edges.
    - **candidate_links**: KB node pairs that share common title words (simple heuristic).
    """
    from datetime import timedelta

    now_dt = datetime.now(timezone.utc)
    recent_cutoff = (now_dt - timedelta(days=recent_days)).isoformat()
    stale_cutoff = (now_dt - timedelta(days=stale_days)).isoformat()

    # Recently added memories
    recently_added: list[dict[str, Any]] = []
    try:
        rows = conn.execute(
            "SELECT kb_path, content, created_at FROM memories"
            " WHERE created_at >= ? ORDER BY created_at DESC LIMIT 30",
            (recent_cutoff,),
        ).fetchall()
        recently_added = [dict(r) for r in rows]
    except sqlite3.OperationalError:
        pass

    # Build node list from tree
    all_nodes = _walk_tree(tree)

    # Last activity per kb_path (most recent memory created_at)
    activity_map: dict[str, str] = {}
    try:
        rows = conn.execute(
            "SELECT kb_path, MAX(created_at) AS last_at FROM memories GROUP BY kb_path"
        ).fetchall()
        for r in rows:
            activity_map[r["kb_path"]] = r["last_at"]
    except sqlite3.OperationalError:
        pass

    # Stale nodes: has some memories but none recently
    stale_nodes: list[dict[str, Any]] = []
    for entry in all_nodes:
        path_str = " > ".join(entry["path"])
        last = activity_map.get(path_str)
        if last and last < stale_cutoff:
            stale_nodes.append({"kb_path": path_str, "last_activity": last})

    # Weak nodes: leaf nodes (no children) with no memories, no chunks, no paper edges
    node_with_memories = set(activity_map.keys())
    try:
        chunk_paths = {
            r[0]
            for r in conn.execute("SELECT DISTINCT kb_path FROM fts_chunks").fetchall()
            if r[0]
        }
    except sqlite3.OperationalError:
        chunk_paths = set()
    try:
        paper_linked = set()
        for r in conn.execute(
            "SELECT dst_id FROM edges WHERE dst_type = 'kb_node'"
        ).fetchall():
            paper_linked.add(r[0])
        for r in conn.execute(
            "SELECT src_id FROM edges WHERE src_type = 'kb_node'"
        ).fetchall():
            paper_linked.add(r[0])
    except sqlite3.OperationalError:
        paper_linked = set()

    weak_nodes: list[dict[str, Any]] = []
    for entry in all_nodes:
        node = entry["node"]
        path_str = " > ".join(entry["path"])
        is_leaf = not node.get("children")
        if is_leaf:
            has_support = (
                path_str in node_with_memories
                or path_str in chunk_paths
                or path_str in paper_linked
            )
            if not has_support:
                weak_nodes.append({"kb_path": path_str, "title": node.get("title", "")})

    # Candidate links: pairs of nodes sharing ≥2 title words (very simple heuristic)
    stopwords = {"a", "an", "the", "of", "in", "for", "and", "to", "with"}
    def _tokens(s: str) -> set[str]:
        return {w.lower() for w in re.split(r"\W+", s) if len(w) > 2 and w.lower() not in stopwords}

    candidate_links: list[dict[str, Any]] = []
    node_titles = [(e["path"][-1], " > ".join(e["path"]), _tokens(e["path"][-1])) for e in all_nodes]
    for i, (t1, p1, tok1) in enumerate(node_titles):
        for t2, p2, tok2 in node_titles[i + 1:]:
            if p1 == p2:
                continue
            shared = tok1 & tok2
            if len(shared) >= 2:
                candidate_links.append({
                    "a": p1,
                    "b": p2,
                    "reason": f"shared title words: {', '.join(sorted(shared))}",
                })
    candidate_links = candidate_links[:20]  # cap output

    return {
        "recently_added": recently_added,
        "stale_nodes": stale_nodes,
        "weak_nodes": weak_nodes,
        "candidate_links": candidate_links,
    }
