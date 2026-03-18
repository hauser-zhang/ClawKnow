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
│   ├── feishu.py          # lark-oapi wrapper: list_spaces, list_nodes, create_node,
│   │                      #   get_raw_content, get_blocks, append_text
│   └── workspace.py       # Multi-workspace resolver (see Workspace Model below)
├── .claude/
│   └── skills/
│       ├── skill-creator/ # Official Anthropic skill lifecycle tool (do not modify)
│       ├── plan-wiki/     # SKILL.md + scripts/plan_structure.py
│       ├── sync-wiki/     # SKILL.md + scripts/sync_to_feishu.py
│       ├── ask-kb/        # SKILL.md + scripts/search_kb.py
│       ├── archive/       # SKILL.md + scripts/archive_to_kb.py
│       └── interview/     # SKILL.md + scripts/manage_interview.py
├── workspaces/            # One directory per knowledge base
│   └── default/           # Default workspace (always present)
│       ├── kb.yaml        # Workspace metadata — tracked in git
│       ├── knowledge_tree.json  # Local tree cache — gitignored
│       └── interviews/    # Interview record JSON files — gitignored
├── tools/
│   └── migrate_legacy.py  # v0 → v1 one-time migration helper
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
| `interviews/*.json` | No | Interview records |

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

Current implementation: **substring keyword search** on `title` (+3 per match) and `summary`
(+1 per match), sorted descending, top 10 returned. See `ask-kb/scripts/search_kb.py`.

This is intentionally simple. Claude reads the results and synthesizes the answer.

**Future extension point (disabled, unimplemented):** SQLite FTS5 index over node title+summary
for better CJK tokenization. Only add if the simple search demonstrably fails for the user.
Do not add embedding-based retrieval.

---

## Sync Strategy

- **Direction:** local → Feishu only (one-way, append-only).
- **Idempotency:** NOT idempotent. Running `sync-wiki` twice creates duplicate nodes.
  Always confirm with the user before syncing.
- **Rate limiting:** `sync_to_feishu.py` sleeps 0.3 s between API calls.
- **node_token / obj_token:** Written back to the workspace `knowledge_tree.json` after each
  node is created. These tokens identify the live Feishu pages.

---

## Skill Registry

| Skill | Trigger | Write ops | Confirm required | Script |
|-------|---------|-----------|-----------------|--------|
| plan-wiki | User explicitly asks to plan/build a knowledge base | `knowledge_tree.json` (overwrite) | Yes — preview outline first | `plan_structure.py` |
| sync-wiki | User says "sync to Feishu" (manual only, `disable-model-invocation: true`) | Feishu wiki nodes + tree tokens | Yes — show node count + risk warning | `sync_to_feishu.py` |
| ask-kb | AI/ML/LLM technical question in ClawKnow context | None (read-only) | No | `search_kb.py` |
| archive | User explicitly says "归档" / "save to KB" | `knowledge_tree.json` (append summary) | Yes — preview archiving plan | `archive_to_kb.py` |
| interview | User mentions interview / 面试 / 八股 context | `interviews/*.json`; Feishu (on sync) | Save: yes; Sync: yes | `manage_interview.py` |

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
    │       │
    │       └─ (nudge) ──► archive ──────────────► knowledge_tree.json (append)
    │                           │ (if node has obj_token)
    │                           └─────────────────► sync-wiki (reminder only)
    │
    └─► interview ──► search_kb.py (read, borrows ask-kb script)
                  ──► manage_interview.py save ──► interviews/*.json (write)
                  ──► manage_interview.py sync ──► Feishu wiki
```

**Boundary rules:**
- `ask-kb` is read-only. It never writes. Archiving is delegated to `archive`.
- `archive` does not call `sync-wiki`. It only reminds the user to sync if needed.
- `interview` reuses `ask-kb`'s `search_kb.py` script directly; it does not invoke the `ask-kb` skill.
- `sync-wiki` is the only skill that writes to Feishu wiki nodes from the knowledge tree.
- Only `plan-wiki` and `archive` write to `knowledge_tree.json`.

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
- `CLAUDE_CN.md` may be more explanatory.
- README.md is for external readers (GitHub). Keep it stable; update only for user-facing changes.

---

## Migration Notes

### v0 → v1 (single-KB → multi-workspace)

- **Old paths:** `data/knowledge_tree.json`, `data/interviews/*.json`
- **New paths:** `workspaces/<kb_id>/knowledge_tree.json`, `workspaces/<kb_id>/interviews/*.json`
- **How to migrate:** `python tools/migrate_legacy.py` — safe to run multiple times, never
  overwrites existing files.
- **Backward compat:** Old `data/` path entries remain in `.gitignore`. The `data/` directory
  itself is not deleted automatically.

### Other migration notes

- **Model version:** `plan_structure.py` currently calls `claude-sonnet-4-20250514`. Update the
  model string when a newer stable Sonnet is released.
- **Path depth:** If a skill script is ever nested differently, update the `parents[N]` index.
  Current depth = 4.
- **lark-oapi:** `CreateSpaceNodeRequest`, `BatchUpdateDocumentBlockRequest` etc. are from
  lark-oapi v1.x. Check for breaking changes on SDK upgrades.

---

## Known Limitations

1. **Search quality:** Substring matching only. No stemming, no synonym expansion, weak CJK
   support. Fine for a personal KB; would need FTS5 upgrade for larger corpora.
2. **Sync is not idempotent:** Running sync-wiki twice creates duplicate Feishu nodes.
   Always confirm with the user.
3. **plan_structure.py requires `ANTHROPIC_API_KEY`:** The only model API call in this repo.
   All other skills work without it.
4. **No Feishu content read-back:** `lib/feishu.py` has `get_raw_content()` but no skill
   wires it into the local tree. Local JSON is the authoritative source.
5. **No incremental sync:** Full tree sync every time; no diff against existing `node_token`s.
6. **feishu_space_id override is runtime-only:** The override is applied by mutating
   `config.FEISHU_WIKI_SPACE_ID` in the script process. It does not persist across runs.

---

## Next Suggested Steps

Implement only when the user requests them.

1. **FTS5 index** — migrate `knowledge_tree.json` to SQLite with FTS5 for better CJK search.
2. **Incremental sync** — skip nodes whose `node_token` already exists in the local tree.
3. **Interview summary page** — generate per-company Markdown and append via `append_text`.
4. **skill-creator eval** — benchmark each skill's description to improve auto-trigger quality.
5. **`ws` CLI helper** — a thin `tools/ws.py` that wraps `workspace.init_workspace()` for
   creating new workspaces from the command line.
