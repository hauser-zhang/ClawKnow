# CLAUDE_CN.md — 项目主人指南

> 这份文档是给你自己看的，解释这个项目的设计逻辑和使用方式。
> 每次重大修改后，你（或 Claude）应同时更新 `CLAUDE.md` 和本文件。

---

## 项目定位

这是一个**完全由 Claude 驱动的个人知识库系统**，核心目标是：

- 把你散乱的 LLM 学习笔记自动整理成飞书知识库（多层级页面结构）
- 在学习过程中随时提问，Claude 先查本地知识库再回答，不够再联网
- 把每次对话中的要点一句话"归档"进知识库，避免知识流失
- 记录面试/笔试经历，关联到知识库节点，同步到飞书

**关键理念**：Claude 本身就是智能层，Python 脚本只是数据读写工具。
你不需要部署任何模型服务，不需要向量数据库，不需要 RAG 框架。

---

## 当前明确约束

以下约束是刻意设计的，不是遗漏，改代码时请遵守：

| 约束 | 原因 |
|------|------|
| 不引入新的付费大模型 API | 现有 Claude API 已够用；避免多模型依赖和费用累积 |
| 不使用 Embedding API | 当前检索规模不需要向量检索；简单关键词匹配 + Claude 理解已足够 |
| 不引入 Reranker | 同上 |
| 不部署本地模型服务 | 个人知识库不需要 Ollama/vLLM；Claude Code 就是推理引擎 |
| 不创建 `src/` 目录 | 逻辑在各 skill 的 `scripts/` 里，共享代码在 `lib/`，结构清晰 |
| 飞书 API 可以用 | `lark-oapi` 是官方 SDK，这是允许的外部服务依赖 |

---

## 为什么暂时不接更多付费大模型 API

整个项目里**只有一处**调用了 Claude API：
`plan-wiki` skill 里的 `plan_structure.py`，用来把你的笔记文档解析成知识树 JSON。

其他所有"智能"——问答、归档建议、面试分析——都是 **Claude Code 对话上下文本身**提供的，
完全不需要额外 API 调用。这意味着：

- **零额外费用**：除了 Claude Code 的正常使用，不产生额外 API 账单
- **零延迟开销**：搜索结果直接展示给对话中的 Claude，无需二次调用
- **可理解性强**：每步发生了什么你都能看到，没有黑箱模型调用链

如果未来检索规模变大（几千个知识点以上），可以升级到 SQLite FTS5 全文检索，
但仍然不需要向量 Embedding。

---

## 用到的技术栈与基本原理

### Python 脚本（数据层）

| 文件 | 作用 |
|------|------|
| `lib/config.py` | 从 `.env` 读取飞书/Anthropic 配置 |
| `lib/feishu.py` | 封装飞书 Wiki V2 + Docx V1 API |
| `plan-wiki/scripts/plan_structure.py` | 读 `docs/`，调用 Claude API，生成 `data/knowledge_tree.json` |
| `sync-wiki/scripts/sync_to_feishu.py` | 读树 JSON，递归创建飞书节点，写回 node_token |
| `ask-kb/scripts/search_kb.py` | 关键词匹配搜索树，返回 top-10 结果给 Claude |
| `archive/scripts/archive_to_kb.py` | 按路径定位节点，追加内容到 summary |
| `interview/scripts/manage_interview.py` | 保存/列出/同步面试记录 JSON |

### 知识树结构（`data/knowledge_tree.json`）

```
知识库（根节点）
├── 大方向A
│   ├── 子类A1
│   │   ├── 知识点（有 summary）
│   │   └── 知识点（有 summary）
│   └── 子类A2
└── 大方向B
    └── ...
```

每个节点的字段：`title`、`summary`（可选）、`children`（可选）、
`node_token` 和 `obj_token`（同步飞书后才有）。

### 路径表示法

归档时用 `"大方向 > 子类 > 知识点"` 这种格式定位节点，例如：
`"后训练 > RLHF > PPO"`

### 检索原理

`search_kb.py` 做的是简单子串匹配：
- 命中 title：+3 分
- 命中 summary：+1 分
- 按分数倒排，返回前 10 条

结果直接展示在 Claude 的对话上下文里，由 Claude 负责理解和组织答案。

---

## 代码与文档如何协同演进

```
你说想改/加功能
       ↓
Claude 读 CLAUDE.md（了解约束和结构）
       ↓
Claude 修改/新增代码
       ↓
如果架构/模型/约束有变化
       ↓
Claude 同步更新 CLAUDE.md 和 CLAUDE_CN.md
       ↓
你确认后 commit
```

**语言约定**：
- Python 代码、注释、commit message、PR 描述 → 英文
- SKILL.md 文件 → 中文（方便你直接检查触发条件和行为说明）
- CLAUDE_CN.md（本文件）→ 中文

---

## 你每次改代码前应该先做什么

1. **看一眼 CLAUDE.md** 里的"Non-Goals and Constraints"部分，确认你的想法不违反约束
2. **确认路径深度**：如果要新建 skill，记得脚本里用 `Path(__file__).resolve().parents[4]` 获取项目根目录
3. **同步到飞书前一定要确认**：`sync-wiki` 不是幂等的，跑两次会创建重复节点
4. **新增共享代码**：只有 2 个以上 skill 用到才放进 `lib/`，否则放在 skill 自己的 `scripts/` 里

---

## 目前的限制

1. **检索质量有限**：只做子串匹配，中文分词不好，复杂查询可能漏掉相关节点。
   目前知识量小，够用；如果节点超过几百个，考虑升级到 SQLite FTS5。

2. **同步不幂等**：`sync-wiki` 跑两次 = 飞书里出现两份一样的内容。
   **每次同步前必须手动确认。**

3. **只能写飞书，不能读回**：`lib/feishu.py` 有 `get_raw_content` 函数，
   但目前没有任何 skill 把飞书内容读回本地树。知识库的权威数据源是本地 JSON，不是飞书。

4. **没有增量同步**：每次都是全量创建，不会跳过已经存在 `node_token` 的节点
   （这个可以改，但目前没做）。

5. **`plan_structure.py` 需要 `ANTHROPIC_API_KEY`**：这是项目里唯一需要 API key 的地方。
   没有 key 就没法从文档生成知识树。其他所有功能不需要这个 key。

---

## 下一步建议

以下是一些有价值的改进方向，等你需要时再做：

| 优先级 | 功能 | 说明 |
|--------|------|------|
| 高 | FTS5 检索升级 | 把 knowledge_tree.json 建 SQLite FTS5 索引，提升中文检索质量 |
| 高 | 增量同步 | 同步前检查 node_token 是否已存在，避免重复创建 |
| 中 | 面试总结页 | 把面试 JSON 生成一份 Markdown 摘要，写入飞书节点正文 |
| 中 | skill-creator 评估 | 对每个 skill 跑一次 skill-creator benchmark，改进触发描述质量 |
| 低 | 飞书内容读回 | 把飞书页面内容同步回本地树的 summary 字段（双向同步） |
