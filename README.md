# feishu-know-llm

AI-powered Feishu (Lark) knowledge base manager built with Claude Code skills and Python.

Turn your LLM study notes into a structured Feishu wiki — with intelligent Q&A, discussion archiving, and interview prep management.

## Features

All features are triggered by natural language — just talk to Claude:

| Skill | Auto-triggers when you... | What it does |
|-------|--------------------------|------|
| plan-wiki | Provide docs, ask to organize knowledge | Analyzes docs → generates a structured knowledge tree |
| sync-wiki | Say "sync to Feishu" (manual `/sync-wiki`) | Creates wiki nodes in Feishu from the knowledge tree |
| ask-kb | Ask any AI/LLM technical question | Searches KB first, supports web search fallback |
| archive | Say "archive" / "save to KB" | Saves discussion highlights into the knowledge tree |
| interview | Mention interviews, 面试, 八股 | Records interview Q&A, links to KB knowledge points |

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/your-username/feishu-know-llm.git
cd feishu-know-llm
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

**Important**: After creating the app, add the bot as a member of your wiki space (Settings → Members → Add app).

### 4. Test connection

```bash
python -m lib.feishu
```

## Usage

Open Claude Code in this project directory and just talk naturally:

### Build a knowledge base

> 我整理了一些 LLM 的笔记放在 docs/ 里了，帮我规划一下知识库结构

Claude reads your docs, generates a knowledge tree, shows you the outline, and saves it after your confirmation.

### Ask questions

> MoE 和 Dense Model 有什么区别？各自的优缺点是什么？

Claude searches the knowledge base first, answers based on what it finds, and offers to search the web if the KB content is insufficient.

> 帮我搜一下最新的 MoE 相关论文

Claude fetches web results and combines them with KB content.

> 归档一下

Claude summarizes the discussion and saves key points into the appropriate KB node.

### Record interviews

> 我今天面试了字节的大模型岗，有几道题想讨论一下

Claude enters interview mode — records each question, discusses best answers, links to KB knowledge points, and saves the record.

## Project Structure

```
feishu-know-llm/
├── lib/                                # Shared Python modules
│   ├── config.py                       # Env var loader
│   └── feishu.py                       # Feishu API wrapper
├── .claude/skills/                     # Claude Code skills
│   ├── skill-creator/                  # Official skill-creator (from anthropics/skills)
│   ├── plan-wiki/                      # Knowledge tree planning
│   │   ├── SKILL.md
│   │   └── scripts/plan_structure.py
│   ├── sync-wiki/                      # Sync to Feishu
│   │   ├── SKILL.md
│   │   └── scripts/sync_to_feishu.py
│   ├── ask-kb/                         # Knowledge base Q&A
│   │   ├── SKILL.md
│   │   └── scripts/search_kb.py
│   ├── archive/                        # Archive discussions
│   │   ├── SKILL.md
│   │   └── scripts/archive_to_kb.py
│   └── interview/                      # Interview management
│       ├── SKILL.md
│       └── scripts/manage_interview.py
├── docs/                               # Your raw study documents
├── data/                               # Local data (gitignored)
│   ├── knowledge_tree.json
│   └── interviews/
├── .env.example
├── pyproject.toml
└── CLAUDE.md
```

## Knowledge Tree Example

Auto-generated structure from your LLM study notes:

```
- LLM Knowledge Base
  - Pre-training
    - Tokenizer: BPE / WordPiece / Unigram
    - Data Engineering: cleaning, dedup, filtering
    - Training: learning rate schedules, mixed precision
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
