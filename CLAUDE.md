# feishu-know-llm

AI-powered Feishu knowledge base manager using Claude Code skills.

## Architecture

- `lib/` — Shared Python modules (Feishu API client, config loader)
- `.claude/skills/` — Claude Code skills (each a self-contained folder)
- `docs/` — User's raw documents to organize into a knowledge base
- `data/` — Local cache (knowledge_tree.json, interview records)

## Skills

| Skill | Trigger | Side effects |
|-------|---------|-------------|
| plan-wiki | User provides docs or asks to structure knowledge | Writes data/knowledge_tree.json |
| sync-wiki | User says "sync to Feishu" (manual only) | Creates Feishu wiki nodes |
| ask-kb | User asks AI/LLM technical questions | None (read-only) |
| archive | User says "archive" or "save to KB" | Updates knowledge_tree.json |
| interview | User mentions interviews / 面试 | Writes to data/interviews/ |

## Conventions

- Code and comments in English
- Skills (SKILL.md) in Chinese for user readability
- Use `lark-oapi` SDK for all Feishu API calls
- Knowledge tree stored as JSON at `data/knowledge_tree.json`
- Each skill script resolves project root via `Path(__file__).resolve().parents[4]`
- Python 3.10+, dependencies in pyproject.toml
