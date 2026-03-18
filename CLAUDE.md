# CLAUDE.md — Project Instructions for Claude Code

> Read this file before making any substantial modification to this repository.
> Update this file (and CLAUDE_CN.md) whenever architecture, constraints, or data models change.

---

## Project Overview

**feishu-know-llm** is a Claude-native knowledge management system. It uses Claude Code skills
as the primary interaction layer — users speak naturally, Claude invokes skills automatically.

Core workflows:
1. **plan-wiki** — analyze raw docs in `docs/` → generate hierarchical knowledge tree JSON
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

If a design idea would normally require a model API call, find a local-file or Claude-workflow alternative first.

---

## Repository Layout

```
feishu-know-llm/
├── lib/
│   ├── config.py          # Load .env vars; config.check() returns missing keys
│   └── feishu.py          # lark-oapi wrapper: list_spaces, list_nodes, create_node,
│                          #   get_raw_content, get_blocks, append_text
├── .claude/
│   └── skills/
│       ├── skill-creator/ # Official Anthropic skill lifecycle tool (do not modify)
│       ├── plan-wiki/     # SKILL.md + scripts/plan_structure.py
│       ├── sync-wiki/     # SKILL.md + scripts/sync_to_feishu.py
│       ├── ask-kb/        # SKILL.md + scripts/search_kb.py
│       ├── archive/       # SKILL.md + scripts/archive_to_kb.py
│       └── interview/     # SKILL.md + scripts/manage_interview.py
├── docs/                  # User's raw study documents (.md / .txt / .rst)
├── data/                  # Gitignored local state
│   ├── knowledge_tree.json
│   └── interviews/        # YYYYMMDD_HHMMSS_<company>.json
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

Each skill script resolves the project root with:

```python
PROJECT_ROOT = Path(__file__).resolve().parents[4]
# skill path depth: project / .claude / skills / <skill-name> / scripts / script.py
#                              4        3        2              1         0
```

Scripts that import `lib` must add `PROJECT_ROOT` to `sys.path`:

```python
sys.path.insert(0, str(PROJECT_ROOT))
from lib import config, feishu
```

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

Filename: `data/interviews/YYYYMMDD_HHMMSS_<company>.json`

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
      "kb_path": "string"      // e.g. "后训练 > RLHF > PPO"
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
- **node_token / obj_token:** Written back to `knowledge_tree.json` after each node is created.
  These tokens identify the live Feishu pages and enable future `append_text` calls.

---

## Skill Registry

| Skill | Auto-trigger conditions | Script | Side effects |
|-------|------------------------|--------|-------------|
| plan-wiki | User provides docs / asks to organize knowledge / 规划知识库 | `plan_structure.py` | Writes `data/knowledge_tree.json` |
| sync-wiki | User says "sync to Feishu" / 同步到飞书 | `sync_to_feishu.py` | Creates Feishu wiki nodes; updates tree tokens |
| ask-kb | AI/LLM technical question (Transformer, MoE, RLHF, RAG, etc.) | `search_kb.py` | None (read-only) |
| archive | User says "归档" / "archive" / "save to KB" | `archive_to_kb.py` | Appends to node summary in tree JSON |
| interview | User mentions 面试/笔试/机试/八股 | `manage_interview.py` | Writes to `data/interviews/` |

SKILL.md files are written in Chinese. All scripts and code comments are in English.

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

---

## Documentation Policy

- After any change to architecture, data models, skill behavior, or constraints:
  update **both** `CLAUDE.md` and `CLAUDE_CN.md`.
- `CLAUDE.md` stays concise and machine-readable (tables, code blocks, short prose).
- `CLAUDE_CN.md` may be more explanatory.
- README.md is for external readers (GitHub). Keep it stable; update only for user-facing changes.

---

## Migration Notes

- **Model version:** `plan_structure.py` currently calls `claude-sonnet-4-20250514`. When a
  newer stable Sonnet is released, update the model string there. Do not change to Opus or
  Haiku without user instruction.
- **Path depth:** If a skill's script is ever moved (e.g., nested one level deeper), update
  the `parents[N]` index accordingly. Current depth = 4 (`project/.claude/skills/name/scripts/`).
- **lark-oapi API surface:** `CreateSpaceNodeRequest`, `BatchUpdateDocumentBlockRequest`, etc.
  are from the current lark-oapi v1.x API. Check for breaking changes on SDK upgrades.

---

## Known Limitations

1. **Search quality:** Substring matching only. No stemming, no synonym expansion, weak CJK
   support. Fine for personal KB; would need FTS5 upgrade for larger corpora.
2. **Sync is destructive on re-run:** Running sync-wiki a second time creates duplicate Feishu
   nodes. Guard with user confirmation every time.
3. **plan_structure.py uses Claude API:** The one Claude API call in this repo. Requires
   `ANTHROPIC_API_KEY` in `.env`. If the key is missing, the skill exits with an error message.
4. **No Feishu content read-back:** The current implementation can write to Feishu but cannot
   read document body content into the local tree. `get_raw_content` exists in `lib/feishu.py`
   but is not wired into any skill yet.
5. **No incremental sync:** The tree is synced in full each time. Partial/incremental sync
   (diff existing tokens vs new nodes) is not implemented.

---

## Next Suggested Steps

These are suggestions, not commitments. Implement only when the user requests them.

1. **FTS5 index** — migrate `data/knowledge_tree.json` to SQLite with FTS5 for better search,
   especially for CJK. Keep the JSON as the source of truth; index is rebuilt on demand.
2. **Incremental sync** — before creating a node, check if `node_token` already exists in the
   local tree; skip if present.
3. **ask-kb web-search integration** — the SKILL.md already describes this; wire up Claude's
   `WebSearch` tool within the skill flow more explicitly.
4. **Interview summary page** — generate a per-company markdown summary from interview JSON
   and append it to the Feishu node body via `append_text`.
5. **skill-creator eval** — run the skill-creator benchmark on each skill to get quality scores
   and improve descriptions.
