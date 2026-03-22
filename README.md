# ClawKnow

AI-powered, Claude-native Feishu knowledge base manager — supporting multiple isolated workspaces.

Turn your LLM study notes into a structured Feishu wiki, with intelligent Q&A, discussion archiving, interview prep management, and **multi-knowledge-base isolation**.

## Features

All features are triggered by natural language — just talk to Claude:

| Skill | Auto-triggers when you... | What it does |
|-------|--------------------------|--------------|
| plan-wiki | Provide docs, ask to organize knowledge | Analyzes docs → generates a structured knowledge tree |
| sync-wiki | Say "sync to Feishu" (manual `/sync-wiki`) | Creates wiki nodes in Feishu from the knowledge tree |
| ask-kb | Ask any AI/LLM technical question | Searches KB + papers first, supports web search fallback |
| archive | Say "archive" / "save to KB" | Saves typed memory records; regenerates node summary |
| interview | Mention interviews, 面试, 八股 | Records interview Q&A, links to KB knowledge points |
| ingest-paper | Provide arXiv/DOI/URL to import | Claude fills structured paper record; saves + FTS-indexes |
| discuss-paper | Say "discuss this paper" / "paper list" | Multi-round discussion; accumulates user insights |
| link-paper-to-kb | Say "link paper to KB" / "add edge" | Creates typed relation edges in the knowledge graph |
| graph-review | Say "graph review" / "check KB health" | Reports stale/weak nodes and candidate link suggestions |

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/hauser-zhang/ClawKnow.git
cd ClawKnow
pip install -e .
```

### 2. Configure credentials

```bash
cp .env.example .env
```

Fill in `.env`:

| Variable | Description | Where to get it |
|----------|-------------|-----------------|
| `FEISHU_APP_ID` | Feishu app ID | [Feishu Open Platform](https://open.feishu.cn) → Create app |
| `FEISHU_APP_SECRET` | Feishu app secret | Same as above |
| `FEISHU_WIKI_SPACE_ID` | Wiki space ID | From wiki URL |
| `ANTHROPIC_API_KEY` | Claude API key | [Anthropic Console](https://console.anthropic.com) |

### 3. Set up Feishu permissions

Enable these scopes for your Feishu app:

- `wiki:wiki` — Wiki read/write
- `docx:document` — Document read/write

**Important**: After creating the app, add the bot as a member of your wiki space
(Settings → Members → Add app).

### 4. Test connection

```bash
python -m lib.feishu
```

## Workspaces

ClawKnow supports multiple isolated knowledge bases, each in its own workspace directory.

### Default workspace

Out of the box, everything goes into `workspaces/default/`.
No extra configuration is needed — all skills default to `--kb default`.

### Create a new workspace

1. Create the directory structure:

```bash
mkdir -p workspaces/my-project/interviews
```

2. Create `workspaces/my-project/kb.yaml`:

```yaml
id: my-project
name: My Project KB
description: Notes for project X
docs_dir: docs/my-project     # relative to project root
feishu_space_id: ""           # leave empty to use global FEISHU_WIKI_SPACE_ID
created_at: "2026-03-18"
```

3. Use the `--kb` flag when invoking skills (Claude handles this automatically
   once you mention the workspace name):

```bash
python .claude/skills/plan-wiki/scripts/plan_structure.py --kb my-project
python .claude/skills/ask-kb/scripts/search_kb.py --kb my-project "your query"
```

### Migrate from legacy layout (v0 → v1)

If you used ClawKnow before the multi-workspace update, run:

```bash
python tools/migrate_legacy.py
```

This copies `data/knowledge_tree.json` and `data/interviews/*.json` into
`workspaces/default/` without deleting the originals.

## Usage

Open Claude Code in this project directory and just talk naturally:

### Build a knowledge base

> 我整理了一些 LLM 的笔记放在 docs/ 里了，帮我规划一下知识库结构

Claude reads your docs, generates a knowledge tree, shows you the outline, and saves it
after your confirmation.

### Ask questions

> MoE 和 Dense Model 有什么区别？各自的优缺点是什么？

Claude searches the knowledge base first, answers based on what it finds, and offers to
search the web if the KB content is insufficient.

> 帮我搜一下最新的 MoE 相关论文

Claude fetches web results and combines them with KB content.

> 归档一下

Claude summarizes the discussion and saves key points into the appropriate KB node.

### Record interviews

> 我今天面试了字节的大模型岗，有几道题想讨论一下

Claude enters interview mode — records each question, discusses best answers, links to KB
knowledge points, and saves the record.

## Project Structure

```
ClawKnow/
├── lib/                                # Shared Python modules
│   ├── config.py                       # Env var loader
│   ├── feishu.py                       # Feishu API wrapper (lark-oapi)
│   ├── workspace.py                    # Workspace resolver (multi-KB)
│   └── retrieval.py                    # FTS5 retrieval + paper CRUD + edge management
├── workspaces/                         # One directory per knowledge base
│   └── default/                        # Default workspace
│       ├── kb.yaml                     # Workspace metadata (tracked)
│       ├── knowledge_tree.json         # Local tree cache (gitignored)
│       ├── kb_index.db                 # FTS5 index + memories + edges (gitignored)
│       ├── interviews/                 # Interview records (gitignored)
│       ├── papers/                     # Ingested paper records (gitignored)
│       └── graph/                      # Exported graph files (gitignored)
├── .claude/skills/                     # Claude Code skills
│   ├── plan-wiki/
│   ├── sync-wiki/
│   ├── ask-kb/
│   ├── archive/
│   ├── interview/
│   ├── ingest-paper/                   # Import academic papers
│   ├── discuss-paper/                  # Multi-round paper discussion
│   ├── link-paper-to-kb/               # Create relation edges
│   └── graph-review/                   # Knowledge graph health review
├── tools/
│   ├── export_graph.py                 # Export graph → JSONL + JSON
│   ├── review_graph.py                 # Graph health review script
│   └── migrate_legacy.py              # v0 → v1 migration helper
├── docs/                               # Your raw study documents
├── .env.example
├── pyproject.toml
└── CLAUDE.md                           # Claude Code project instructions
```

## Knowledge Tree Example

Auto-generated structure from your LLM study notes:

```
- LLM Knowledge Base
  - Pre-training
    - Tokenizer: BPE / WordPiece / Unigram
    - Data Engineering: cleaning, dedup, filtering
  - Post-training
    - SFT: supervised fine-tuning
    - RLHF
      - PPO
      - GRPO
      - DPO / KTO
  - Architecture
    - Transformer: attention, positional encoding
    - MoE: sparse experts, routing
    - SSM: Mamba, linear attention
  - Inference
    - KV Cache
    - Quantization: GPTQ, AWQ, GGUF
    - Speculative Decoding
  - Applications
    - RAG
    - Agent
    - Multimodal
```

## License

MIT
