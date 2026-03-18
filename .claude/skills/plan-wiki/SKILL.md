---
name: plan-wiki
description: >
  分析 docs/ 目录下的学习文档，生成飞书知识库的树形结构（knowledge_tree.json）。
  触发：用户明确要求"规划知识库"、"整理文档到飞书"、"帮我建知识树"、"生成知识库结构"，
  或者提供文档后说要保存/组织到飞书知识库里。
  不触发：仅讨论文档内容本身（无建库意图）；仅提问技术概念；仅整理某个文件格式。
  写操作：会覆盖 workspaces/<kb_id>/knowledge_tree.json，执行前须用户确认。
allowed-tools: Read, Glob, Bash(python *)
---

# 知识库结构规划

## 元数据

| 项目 | 内容 |
|------|------|
| 用途 | 分析 docs/ 文档 → 生成分层知识树 → 保存为 JSON |
| 输入 | `docs/` 目录下的 `.md` / `.txt` / `.rst` 文件（或 kb.yaml 指定的 docs_dir）|
| 输出 | 控制台打印 Markdown 大纲 |
| 副作用 | **覆盖写** `workspaces/<kb_id>/knowledge_tree.json` |
| 需要确认 | 是 — 展示大纲后等用户确认再保存 |

## 触发条件

**会触发（需包含建库意图）：**
- "帮我规划一下知识库"
- "把 docs/ 里的文档整理成飞书知识库"
- "生成一个知识树结构"
- "我有一些笔记，帮我建个知识库"

**不触发：**
- 仅问"什么是 MoE"（→ ask-kb 处理）
- "帮我整理一下这篇文档的格式"
- "归档一下"（→ archive 处理）
- 已有知识树，仅问某个概念

## 执行流程

### 第一步：定位文档

用 Glob 找到 docs 目录下所有支持文件（`.md`, `.txt`, `.rst`）：

```bash
# 先确认 docs 目录和 kb_id（如用户未指定则用 default）
```

如果 `docs/` 为空，提示用户先放入文档后再继续。

### 第二步：生成知识树

```bash
# 默认 workspace
python ${CLAUDE_SKILL_DIR}/scripts/plan_structure.py

# 指定 workspace
python ${CLAUDE_SKILL_DIR}/scripts/plan_structure.py --kb <kb_id>
```

脚本调用 Claude API（`ANTHROPIC_API_KEY` 必须已配置）分析文档内容，
输出结构化 JSON 并打印 Markdown 大纲。

如果脚本因环境原因无法运行（无 API key、无网络），可直接在对话中分析文档内容，
按 `references/tree_schema.md` 中的 JSON 格式手动生成知识树。

### 第三步：预览并确认

将脚本输出的 Markdown 大纲展示给用户，格式如下：

```
📋 知识树预览（workspace: default）

- LLM 知识库
  - 预训练
    - Tokenizer: BPE/WordPiece/Unigram 分词算法原理与对比
    - 数据工程: 预训练数据清洗、去重、质量过滤
  - 后训练
    - SFT: 监督微调的数据格式与训练策略
    - RLHF
      - PPO: 近端策略优化算法原理
      - GRPO: 组相对策略优化，DeepSeek 提出

共 N 个节点，M 个叶子节点。

---
结构是否合理？可以告诉我需要增删哪些分类，或直接说"确认保存"。
```

**等待用户明确确认后**再写入文件，不要提前保存。

### 第四步：保存

用户说"确认"、"ok"、"保存"、"没问题"后，脚本已自动保存到
`workspaces/<kb_id>/knowledge_tree.json`。

如需应用用户的调整意见，直接修改 JSON 文件，或重新运行脚本。

## 错误处理

| 错误 | 处理方式 |
|------|---------|
| `ANTHROPIC_API_KEY` 未设置 | 提示用户在 `.env` 中配置；可手动生成树 |
| `docs/` 目录不存在或为空 | 提示用户放入文档 |
| JSON 解析失败 | 显示原始输出，提示用户检查或手动修正 |

## 参考

- 知识树 JSON 格式与 LLM 分类参考 → `references/tree_schema.md`
- 数据模型 → `CLAUDE.md` § Data Models
