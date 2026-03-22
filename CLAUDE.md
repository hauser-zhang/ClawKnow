# CLAUDE.md — Project Instructions for Claude Code

> Read this file before making any substantial modification to this repository.
> Update this file (and CLAUDE_CN.md) whenever architecture, constraints, or data models change.

---

## Project Overview

**ClawKnow** is a Claude-native, multi-workspace knowledge management system.
Users interact in natural language; Claude Code skills handle all data operations.

Core workflows:
1. **plan-wiki** — analyze raw docs → generate hierarchical knowledge tree JSON
2. **sync-wiki** — push local knowledge tree to Feishu Wiki as real pages (manual only)
3. **ask-kb** — search the local knowledge tree, answer LLM/AI questions, optionally web-search
4. **archive** — extract discussion highlights and append them to a knowledge tree node
5. **interview** — record interview sessions, link Q&A to KB nodes, optionally sync to Feishu

Intelligence layer: **Claude itself** (via Claude Code context). Scripts are data plumbing only.

---

## Non-Goals and Constraints

These are permanent hard constraints. Do not work around them.

| Constraint | Rule |
|-----------|------|
| No new LLM API | Do NOT add calls to OpenAI, Gemini, OpenRouter, Groq, Together, or any other model provider |
| No embeddings | Do NOT add embedding APIs (OpenAI embeddings, Cohere, etc.) or local embedding models |
| No rerankers | Do NOT add hosted or local reranker APIs |
| No model server | Do NOT add Ollama, vLLM, LMStudio, or any self-hosted inference backend |
| Anthropic SDK | The existing `anthropic` SDK usage in `plan_structure.py` is the ONLY allowed model call. Do not expand it to other skills without explicit user instruction |
| Feishu API OK | `lark-oapi` calls are allowed and encouraged |
| Local-first | Prefer JSON files, SQLite+FTS5, and plain text over any hosted service |
| Claude does reasoning | Scripts handle I/O and data mutation. Claude (the running assistant) provides all intelligence, summarization, and judgment — not a called API |

---

## Repository Layout

```
ClawKnow/
├── lib/
│   ├── config.py          # Load .env vars; config.check() returns missing keys
│   ├── feishu.py          # lark-oapi wrapper: list_spaces, list_nodes, list_nodes_all,
│   │                      #   create_node, get_raw_content, get_blocks, append_text,
│   │                      #   replace_doc_content
│   ├── workspace.py       # Multi-workspace resolver (see Workspace Model below)
│   └── retrieval.py       # FTS5 two-stage retrieval + paper CRUD + edge management
├── .claude/
│   └── skills/
│       ├── skill-creator/ # Official Anthropic skill lifecycle tool (do not modify)
│       ├── plan-wiki/     # SKILL.md + scripts/plan_structure.py
│       ├── sync-wiki/     # SKILL.md + scripts/sync_to_feishu.py
│       ├── ask-kb/        # SKILL.md + scripts/search_kb.py + build_index.py
│       ├── archive/       # SKILL.md + scripts/archive_to_kb.py
│       ├── interview/     # SKILL.md + scripts/manage_interview.py
│       ├── ingest-paper/  # SKILL.md + scripts/ingest_paper.py
│       ├── discuss-paper/ # SKILL.md + scripts/discuss_paper.py
│       ├── link-paper-to-kb/  # SKILL.md + scripts/link_paper.py
│       └── graph-review/  # SKILL.md (read-only; uses tools/review_graph.py)
├── workspaces/            # One directory per knowledge base
│   └── default/           # Default workspace (always present)
│       ├── kb.yaml        # Workspace metadata — tracked in git
│       ├── knowledge_tree.json  # Local tree cache — gitignored
│       ├── kb_index.db    # FTS5 index + memories + edges — gitignored
│       ├── interviews/    # Interview record JSON files — gitignored
│       ├── papers/        # Paper JSON files — gitignored
│       └── graph/         # Exported graph JSONL files — gitignored
├── tools/
│   ├── migrate_legacy.py  # v0 → v1 one-time migration helper
│   ├── export_graph.py    # Export graph → nodes.jsonl + edges.jsonl + graph.json
│   └── review_graph.py    # Review graph health: stale/weak nodes, candidate links
├── docs/                  # User's raw study documents (.md / .txt / .rst)
├── .env                   # Secrets (gitignored)
├── .env.example
├── pyproject.toml
├── CLAUDE.md              # This file
├── CLAUDE_CN.md           # Chinese owner guide
└── README.md
```

**No `src/` directory.** All business logic lives inside each skill's `scripts/` folder.
Shared code belongs in `lib/` only if used by 2+ skills.

---

## Workspace Model

### Directory structure

Each workspace lives at `workspaces/<kb_id>/` and contains:

| File | Tracked | Purpose |
|------|---------|---------|
| `kb.yaml` | Yes | Workspace metadata and per-KB Feishu space override |
| `knowledge_tree.json` | No | Local knowledge tree state |
| `kb_index.db` | No | FTS5 index + memories + paper index + edges |
| `feishu_map.json` | No | Local-path → Feishu token mapping for idempotent sync |
| `interviews/*.json` | No | Interview records |
| `papers/*.json` | No | Ingested paper records (one file per paper) |
| `graph/nodes.jsonl` | No | Exported graph node list (auto-generated) |
| `graph/edges.jsonl` | No | Exported graph edge list (auto-generated) |
| `graph/graph.json` | No | Combined graph JSON for visualization (auto-generated) |

### `kb.yaml` schema

```yaml
id: default               # must match the directory name
name: LLM 知识库          # human-readable name
description: ...          # optional free text
docs_dir: docs            # relative to project root; source docs for plan-wiki
feishu_space_id: ""       # override global FEISHU_WIKI_SPACE_ID if non-empty
created_at: "YYYY-MM-DD"
```

### Path resolution

Every skill script resolves project root with:

```python
PROJECT_ROOT = Path(__file__).resolve().parents[4]
# depth: project / .claude / skills / <skill-name> / scripts / script.py
#                   4         3         2              1         0
```

Scripts import `lib.workspace` for all path operations:

```python
from lib import workspace

tree_path      = workspace.get_tree_path(PROJECT_ROOT, kb_id)
index_path     = workspace.get_index_path(PROJECT_ROOT, kb_id)
interviews_dir = workspace.get_interviews_dir(PROJECT_ROOT, kb_id)
docs_dir       = workspace.get_docs_dir(PROJECT_ROOT, kb_id)
kb_cfg         = workspace.load_kb_config(PROJECT_ROOT, kb_id)
```

All scripts accept `--kb <kb_id>` (default: `default`).

### Feishu space ID resolution (sync-wiki / interview sync)

1. If `kb.yaml` has a non-empty `feishu_space_id` → use that
2. Otherwise fall back to `config.FEISHU_WIKI_SPACE_ID` from `.env`

---

## Data Models

### knowledge_tree.json

Single JSON object rooted at the top-level KB node. Every node has:

```jsonc
{
  "title": "string",           // required
  "summary": "string",         // optional; leaf nodes should have this
  "children": [],              // list of child nodes; omit or [] for leaves
  "node_token": "string",      // set by sync-wiki after Feishu sync
  "obj_token": "string"        // set by sync-wiki after Feishu sync
}
```

Path notation (used by `archive`): `"大方向 > 子类 > 知识点"` — nodes joined by `" > "`.

The `summary` field is now **generated** from typed memory records by
`retrieval.regen_node_summary()` — do not hand-edit it; it will be overwritten
on the next `archive` run.

### Memory record

Stored in `workspaces/<kb_id>/kb_index.db` → `memories` table.
Indexed for full-text search in `fts_memories`.

```jsonc
{
  "memory_id":   "sha256-derived stable id",
  "type":        "concept | fact | insight | source_note | question | decision",
  "content":     "string — the knowledge statement",
  "kb_path":     "大方向 > 子类 > 知识点",
  "source_refs": ["Paper: Vaswani 2017", "https://..."],  // optional
  "author":      "claude | user",
  "confidence":  "high | medium | low",
  "created_at":  "ISO-8601",
  "updated_at":  null                                     // reserved
}
```

**Type semantics:**
| Type | Use |
|------|-----|
| `concept` | Core definition or principle |
| `fact` | Verifiable data point or behavior |
| `insight` | Trade-off, comparison, or empirical conclusion |
| `source_note` | Paper / article / project citation |
| `question` | Open question awaiting verification |
| `decision` | Project or practice decision |

**Summary regeneration** (`retrieval.regen_node_summary()`): collects all
`memories` rows for a `kb_path`, sorts by `_TYPE_ORDER`, and emits
`[类型标签] content` lines.  No external API call.  Deterministic.

### Paper record

Filename: `workspaces/<kb_id>/papers/<paper_id>.json`

```jsonc
{
  "paper_id": "16-char hex (sha256 of doi|arxiv_id|title)",
  "title": "string",
  "authors": ["string"],
  "year": 2024,
  "doi": "10.xxx/yyy",
  "arxiv_id": "2401.xxxxx",
  "venue": "NeurIPS 2024",
  "url": "https://...",
  "abstract_summary": "Claude's 2-4 sentence summary of the abstract",
  "method_summary": "Technical method/contribution summary (3-6 sentences)",
  "key_claims": ["verifiable claim from the paper"],
  "limitations": ["stated or obvious limitation"],
  "open_questions": ["open question raised after reading"],
  "related_kb_nodes": ["KB > Path > To > Node"],
  "user_insights": ["free-form user notes accumulated during discussion"],
  "status": "reading | read | reviewed",
  "added_at": "ISO-8601",
  "updated_at": "ISO-8601 | null"
}
```

The paper is also indexed in `kb_index.db → fts_papers` (title + abstract_summary +
method_summary are full-text indexed) so `ask-kb` can surface papers during search.
**No model API is called** to fill these fields — Claude (the running assistant) fills
them during the `ingest-paper` session.

### Edge record

Stored in `kb_index.db → edges` table. Represents a directed relationship between any
two entities (kb_node paths or paper_ids).

```jsonc
{
  "edge_id":    "sha256(src_type:src_id:edge_type:dst_type:dst_id)",
  "src_id":     "kb_path string | paper_id",
  "src_type":   "kb_node | paper",
  "dst_id":     "kb_path string | paper_id",
  "dst_type":   "kb_node | paper",
  "edge_type":  "contains | related_to | depends_on | compares_with | derived_from | updated_by | cites",
  "weight":     1.0,
  "note":       "optional human note",
  "created_at": "ISO-8601"
}
```

`contains` edges are auto-derived from the tree structure by `export_graph.py`.
All other types are user-created via the `link-paper-to-kb` skill.

**Edge type semantics:**
| Type | Meaning |
|------|---------|
| `contains` | Parent node contains child (tree structure, auto-derived) |
| `related_to` | Bidirectional content relation (no strong directionality) |
| `depends_on` | Understanding src requires dst first |
| `compares_with` | src is compared or contrasted with dst |
| `derived_from` | src's method/conclusion derives from dst |
| `updated_by` | dst paper/archive corrects or extends src |
| `cites` | src explicitly cites dst |

### Interview record

Filename: `workspaces/<kb_id>/interviews/YYYYMMDD_HHMMSS_<company>.json`

```jsonc
{
  "company": "string",
  "date": "YYYY-MM-DD",
  "type": "面试 | 笔试 | 机试",
  "questions": [
    {
      "question": "string",
      "category": "八股 | 算法 | 项目 | 系统设计 | other",
      "answer": "string",
      "kb_path": ["大方向", "子类", "知识点"]
    }
  ]
}
```

---

## Retrieval Strategy

### Architecture — two-stage FTS5 search

Stage 1 searches `fts_nodes` (KB node title + summary) with BM25 ranking.
Stage 2 retrieves supporting evidence for each matched node from `fts_chunks` and `fts_memories`.
A global pass also fetches chunks/memories not yet linked to a KB node.

All retrieval is handled by `lib/retrieval.py`. `search_kb.py` auto-rebuilds the node index
whenever `knowledge_tree.json` has changed (detected via SHA-256 hash stored in `index_state`).

### Schema (`workspaces/<kb_id>/kb_index.db`)

| Table | Type | Indexed columns | Purpose |
|-------|------|----------------|---------|
| `fts_nodes` | FTS5 | `title`, `summary` | KB node full-text search |
| `fts_chunks` | FTS5 | `content` | Document chunk search |
| `fts_memories` | FTS5 | `content` | Archived memory search index |
| `fts_papers` | FTS5 | `title`, `abstract_summary`, `method_summary` | Paper full-text search |
| `memories` | Regular | — | Typed memory records (source of truth; see Data Models) |
| `edges` | Regular | — | Unified edge store: kb_node↔kb_node, paper↔kb_node, paper↔paper |
| `sources` | Regular | — | Doc metadata + content_hash (change detection) |
| `index_state` | Regular | — | `tree_hash` for auto-rebuild detection |

FTS5 tokenizer: `unicode61` — treats each CJK character as a separate token, which is
meaningfully better than substring matching for Chinese text.

### Provenance fields (unindexed, stored in FTS5 rows)

| Table | Provenance |
|-------|-----------|
| `fts_nodes` | `kb_path`, `node_token`, `obj_token`, `updated_at` |
| `fts_chunks` | `chunk_id`, `source_id`, `source_title`, `source_path`, `kb_path`, `chunk_index`, `created_at` |
| `fts_memories` | `memory_id`, `kb_path`, `archived_at` |

### Data flow

- `plan-wiki` writes `knowledge_tree.json` → `search_kb.py` auto-rebuilds `fts_nodes` on next query.
- `archive` writes typed records to `memories` + mirrors to `fts_memories`, then calls
  `regen_node_summary()` to regenerate `knowledge_tree.json` node summary (no raw append).
- `build_index.py --index-docs` chunks docs from `docs_dir` and inserts into `fts_chunks`.
- `tools/seed_demo.py` creates a `demo` workspace with sample tree, doc chunks, and memories.

### Ranking

BM25 via SQLite's built-in `bm25(fts_nodes)` function. Scores are negative floats;
lower (more negative) = better match. No external model calls for ranking.

### Disabled extension points

```python
# lib/retrieval.py — intentionally False; do NOT enable without explicit user request
_EMBED_ENABLED   = False   # sentence-transformer embedding for semantic reranking
_RERANK_ENABLED  = False   # cross-encoder reranking pass over FTS5 results
```

Do not add embedding APIs (OpenAI embeddings, Cohere, sentence-transformers, etc.).
Do not add reranker APIs. BM25 + Claude's own reading is sufficient at personal-KB scale.

---

## Paper Workflow

### Overview

Papers are an independent knowledge layer parallel to the KB node tree.
They are **not** a replacement for `archive` — they serve a different purpose:

| | KB node memories (`archive`) | Paper records (`ingest-paper`) |
|-|-----|------|
| Source | Free-form discussion highlights | Published academic papers |
| Accumulation | Many small facts over time | One structured record per paper |
| Linkage | Tied to a KB node path | Linked to KB nodes via `edges` |
| Retrieval | `fts_memories` + `fts_nodes` | `fts_papers` (separate FTS5 table) |

### Three-skill flow

```
User provides paper URL / arXiv / abstract text
           │
           ▼
    ingest-paper  ──► papers/<id>.json  ──► fts_papers index
           │
           ▼ (optional — multi-round discussion)
    discuss-paper ──► papers/<id>.json (user_insights append)
           │
           ▼ (optional — build graph connections)
    link-paper-to-kb ──► edges table
                              │
                              ▼
                     export_graph.py ──► graph/nodes.jsonl + edges.jsonl
```

### API constraint

**No model API calls** during paper workflow.
- `ingest-paper`: Claude (the running assistant) fills in `abstract_summary`,
  `method_summary`, `key_claims`, etc. during the conversation. `ingest_paper.py`
  only validates and saves the JSON.
- `discuss-paper`: Claude reads the saved JSON and discusses it. No API call.
- `link-paper-to-kb`: Pure data write to SQLite `edges` table.

### ask-kb integration

`search_kb.py` runs `retrieval.search_papers()` on every query and appends
`[PAPER]` results after `[MEM]` results.  Paper results appear only when papers
have been ingested — no change in behavior for workspaces with no papers.

---

## Graph Projection

### Why a graph, not just a tree

The `knowledge_tree.json` is hierarchical — each node has exactly one parent.
But knowledge is not hierarchical: "PPO" belongs under "RLHF" but also
**depends_on** understanding "Policy Gradient", **cites** Schulman 2017,
and **compares_with** "GRPO". These cross-cutting relations cannot be expressed
in a tree; they require a graph layer.

### Design principles

- **Lightweight**: edges stored in SQLite `edges` table; export is JSONL/JSON files.
  No graph database required.
- **Local-first**: all data is local; no external service.
- **Claude does reasoning**: the graph layer is a _data substrate_ — Claude reads it
  and makes sense of it. No graph algorithms are run by scripts.
- **Additive, not replacing**: the tree is still the primary structure. The graph
  adds cross-cutting edges on top.

### Edge semantics

| Type | Meaning | Auto-derived? |
|------|---------|--------------|
| `contains` | Parent→child in tree | Yes — by `export_graph.py` |
| `related_to` | Content relation (bidirectional) | No |
| `depends_on` | src requires understanding dst | No |
| `compares_with` | src vs dst comparison | No |
| `derived_from` | src method derived from dst | No |
| `updated_by` | dst corrects/extends src | No |
| `cites` | src explicitly cites dst | No |

### Graph export

Run `python tools/export_graph.py --kb <kb_id>` to generate:

```
workspaces/<kb_id>/graph/
├── nodes.jsonl   # one node per line: {id, type, label, summary, ...}
├── edges.jsonl   # one edge per line: {edge_id, src, src_type, dst, ...}
└── graph.json    # combined {nodes: [...], edges: [...]}
```

Safe to run repeatedly. All files are regenerated from source (tree + db).
Files are gitignored — they are derived artifacts, not source data.

### Graph review

`python tools/review_graph.py --kb <kb_id>` produces a report with four sections:

| Section | What it shows | Action |
|---------|--------------|--------|
| `[RECENT]` | Memories created in last 7 days | Confirm knowledge is accumulating |
| `[STALE]` | Nodes with no update in >30 days | Review / update or archive new insights |
| `[WEAK]` | Leaf nodes with zero support | Archive facts or link to a paper |
| `[LINKS]` | Node pairs sharing ≥2 title words | Consider adding a `related_to` edge |

---

## Sync Strategy

### Direction and idempotency

- **Direction:** local → Feishu only (one-way).
- **Idempotent:** `sync_to_feishu.py` is now idempotent. Running it twice is safe.
  The mapping file `feishu_map.json` tracks what has already been synced.
- **Rate limiting:** 0.35 s sleep between API calls; up to 3 retries with exponential back-off.
- **node_token / obj_token:** Written back to `knowledge_tree.json` and `feishu_map.json`
  after each node is created. These tokens identify the live Feishu pages.

### Mapping file (`workspaces/<kb_id>/feishu_map.json`)

Tracks local-node path → `(node_token, obj_token, content_hash)` for every synced node.
Gitignored (contains runtime Feishu identifiers, not source data).

```jsonc
{
  "version": 1,
  "space_id": "...",
  "kb_id": "default",
  "updated_at": "...",
  "nodes": {
    "LLM知识库 > MoE架构": {
      "node_token": "abc...",
      "obj_token": "xyz...",
      "title": "MoE架构",
      "synced_at": "...",
      "content_hash": "sha256..."   // SHA-256 of rendered body content
    }
  },
  "interviews": { ... }
}
```

### Sync phases

| Phase | Flag | Description |
|-------|------|-------------|
| Dry-run (default) | _(none)_ | Compute diff, print create/update/skip plan, no writes |
| Apply | `--apply` | Execute diff, create/update nodes, save map after each success |
| Recover | `--recover` | BFS-scan remote space, match by title path, populate map |
| Interviews | `--interviews` | Also sync `interviews/*.json` under a `面试记录` container node |

### Diff rules per node

1. Path in map **and** `content_hash` unchanged → **skip**
2. Path in map **and** `content_hash` changed → **update_content** (overwrite doc body only)
3. Path not in map but `node_token` present in tree → **update_content** (recovery from old sync)
4. Path not in map, no token → **create** (new node + write content)

### Content rendering (no model API)

After creating a node, its Feishu document body is written with:
- Node `summary` (from `knowledge_tree.json`)
- Typed memories from `kb_index.db` (`memories` table), formatted with type labels

Content is plain text paragraphs written via `feishu.replace_doc_content()`.
No model API calls are made during rendering.

---

## Skill Registry

| Skill | Trigger | Write ops | Confirm required | Script |
|-------|---------|-----------|-----------------|--------|
| plan-wiki | User explicitly asks to plan/build a knowledge base | `knowledge_tree.json` (overwrite) | Yes — preview outline first | `plan_structure.py` |
| sync-wiki | User says "sync to Feishu" (manual only, `disable-model-invocation: true`) | Feishu wiki nodes + tree tokens | Yes — show node count + risk warning | `sync_to_feishu.py` |
| ask-kb | AI/ML/LLM technical question in ClawKnow context | None (read-only) | No | `search_kb.py` |
| archive | User explicitly says "归档" / "save to KB" | `kb_index.db/memories` (typed records); `knowledge_tree.json` (summary regenerated) | Yes — typed preview with type + confidence | `archive_to_kb.py` |
| interview | User mentions interview / 面试 / 八股 context | `interviews/*.json`; Feishu (on sync) | Save: yes; Sync: yes | `manage_interview.py` |
| ingest-paper | User provides paper URL/arXiv/DOI to import | `papers/<paper_id>.json`; `kb_index.db/fts_papers` | Yes — preview card before saving | `ingest_paper.py` |
| discuss-paper | User wants to discuss / list / annotate ingested papers | `papers/<paper_id>.json` (user_insights append) | Yes — before appending insights | `discuss_paper.py` |
| link-paper-to-kb | User wants to create/list/delete relation edges | `kb_index.db/edges` | Yes — before edge creation/deletion | `link_paper.py` |
| graph-review | User asks for graph health report / stale/weak nodes | None (read-only) | No | `tools/review_graph.py` |

SKILL.md files are written in Chinese. All scripts and code comments are in English.

### Skill Structure Convention

Each skill folder contains:
```
.claude/skills/<skill-name>/
├── SKILL.md               # Frontmatter (name, description, allowed-tools) + flow instructions
├── scripts/               # Python data scripts
│   └── <script>.py
└── references/            # (Optional) Reference docs: schemas, style guides, examples
    └── <ref>.md
```

`SKILL.md` body sections (standardized):
1. **元数据** — purpose, inputs, outputs, side effects, confirm-required (table)
2. **触发条件** — positive examples + counter-examples ("不触发")
3. **执行流程** — numbered steps with bash commands
4. **预览/确认协议** — preview template for write-heavy skills
5. **错误处理** — error → action table

### Skill Boundary and Composition

```
User input
    │
    ├─► plan-wiki ──────────────────────────► knowledge_tree.json (write)
    │       │ (after plan)                          │
    │       └─────────────────────────────────────► sync-wiki ──► Feishu wiki
    │
    ├─► ask-kb ──► search_kb.py (read) ──► answer
    │       │         (also searches fts_papers)
    │       └─ (nudge) ──► archive ──────────────► knowledge_tree.json (append)
    │                           │ (if node has obj_token)
    │                           └─────────────────► sync-wiki (reminder only)
    │
    ├─► interview ──► search_kb.py (read, borrows ask-kb script)
    │             ──► manage_interview.py save ──► interviews/*.json (write)
    │             ──► manage_interview.py sync ──► Feishu wiki
    │
    ├─► ingest-paper ──────────────────────► papers/<id>.json (write)
    │                                      ► kb_index.db/fts_papers (write)
    │
    ├─► discuss-paper ─────────────────────► papers/<id>.json user_insights (append)
    │
    ├─► link-paper-to-kb ──────────────────► kb_index.db/edges (write)
    │                                              │
    │                                              ▼
    │                                    export_graph.py ──► graph/*.jsonl
    │
    └─► graph-review ──► review_graph.py (read-only) ──► report
```

**Boundary rules:**
- `ask-kb` is read-only. It never writes. Archiving is delegated to `archive`.
- `archive` does not call `sync-wiki`. It only reminds the user to sync if needed.
- `interview` reuses `ask-kb`'s `search_kb.py` script directly; it does not invoke the `ask-kb` skill.
- `sync-wiki` is the only skill that writes to Feishu wiki nodes from the knowledge tree.
- Only `plan-wiki` and `archive` write to `knowledge_tree.json`.
- `ingest-paper` / `discuss-paper` / `link-paper-to-kb` are a separate paper layer — they never write to `knowledge_tree.json`.

---

## Developer Conventions

- **Language:** Code, comments, docstrings, commit messages, and PR descriptions → English.
  SKILL.md files → Chinese (owner readability).
- **Deps:** Add to `pyproject.toml` only. No `requirements.txt`. No pinning unless a breaking
  change requires it.
- **New skill:** Use `skill-creator` (`.claude/skills/skill-creator/`) to scaffold and evaluate.
- **New shared util:** Add to `lib/` only if 2+ skills need it. Otherwise keep it in the skill's
  own `scripts/`.
- **No `src/` directory.** Never create one.
- **Python:** 3.10+. Use `pathlib`, type hints on new functions.
- **Secrets:** Never commit `.env`. All credentials go in `.env` only.
- **New workspace:** Create `workspaces/<id>/kb.yaml` (commit this) and
  `workspaces/<id>/interviews/` (gitignored). Use `lib.workspace.init_workspace()` or
  `tools/migrate_legacy.py` as a reference.

---

## Documentation Policy

- After any change to architecture, data models, skill behavior, or constraints:
  update **both** `CLAUDE.md` and `CLAUDE_CN.md`.
- `CLAUDE.md` stays concise and machine-readable (tables, code blocks, short prose).
- `CLAUDE_CN.md` may be more explanatory. It is **gitignored** — personal owner guide, not for repo consumers.
- `README.md` is for external readers (GitHub). Keep it stable; update only for user-facing changes.
- `.claude/rules/` is **gitignored** — developer operational notes, not for repo consumers.

---

## Migration Notes

### v0 → v1 (single-KB → multi-workspace)

- **Old paths:** `data/knowledge_tree.json`, `data/interviews/*.json`
- **New paths:** `workspaces/<kb_id>/knowledge_tree.json`, `workspaces/<kb_id>/interviews/*.json`
- **How to migrate:** `python tools/migrate_legacy.py` — safe to run multiple times, never
  overwrites existing files.
- **Status:** Migration complete. The `data/` directory has been removed; legacy `.gitignore`
  entries for `data/` have been cleaned up.

### Other migration notes

- **Model version:** `plan_structure.py` currently calls `claude-sonnet-4-20250514`. Update the
  model string when a newer stable Sonnet is released.
- **Path depth:** If a skill script is ever nested differently, update the `parents[N]` index.
  Current depth = 4.
- **lark-oapi:** `CreateSpaceNodeRequest`, `BatchUpdateDocumentBlockRequest` etc. are from
  lark-oapi v1.x. Check for breaking changes on SDK upgrades.

---

## Known Limitations

1. **Search quality:** FTS5 BM25 with `unicode61` tokenizer. No stemming or synonym expansion.
   CJK character-level tokenization is adequate for personal KBs; for corpora with 1000+ nodes
   consider SQLite FTS5 with a jieba tokenizer plugin (optional future work).
2. **Sync title rename not supported:** If a node's title changes after the initial sync,
   `sync-wiki` does not rename the existing Feishu page (only content is updated).
   Rename manually in Feishu and update `feishu_map.json` if needed.
3. **plan_structure.py requires `ANTHROPIC_API_KEY`:** The only model API call in this repo.
   All other skills work without it.
4. **No Feishu content read-back:** `lib/feishu.py` has `get_raw_content()` but no skill
   wires it into the local tree. Local JSON is the authoritative source.
5. **feishu_space_id override is runtime-only:** The override is applied by mutating
   `config.FEISHU_WIKI_SPACE_ID` in the script process. It does not persist across runs.
6. **`replace_doc_content` uses `DeleteChildren`:** If the lark-oapi SDK version does not
   expose `DeleteChildren`, the delete step is silently skipped and content is appended instead.
   Upgrade the SDK to get true replace behavior.

---

## Next Suggested Steps

Implement only when the user requests them.

1. **FTS5 index** — ✅ implemented in `lib/retrieval.py`; `kb_index.db` per workspace.
2. **Idempotent sync** — ✅ implemented; `feishu_map.json` + dry-run/apply/recover modes.
3. **Content rendering** — ✅ summaries + typed memories written to Feishu doc body on sync.
4. **Interview sync** — ✅ `--interviews` flag syncs JSON records under a `面试记录` node.
5. **Paper workflow** — ✅ `ingest-paper`, `discuss-paper`, `link-paper-to-kb` skills; `fts_papers` + `edges` table.
6. **Graph projection** — ✅ `export_graph.py` + `review_graph.py` + `graph-review` skill.
7. **skill-creator eval** — benchmark each skill's description to improve auto-trigger quality.
8. **`ws` CLI helper** — a thin `tools/ws.py` that wraps `workspace.init_workspace()` for
   creating new workspaces from the command line.
9. **Rename sync** — detect title changes and call Feishu node rename API.
10. **Graph visualization** — a minimal `graph/index.html` using D3.js force layout that
    reads `graph.json` — no server needed, open in browser directly.
