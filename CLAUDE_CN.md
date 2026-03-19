# CLAUDE_CN.md — 项目主人指南

> 这份文档是给你自己看的，解释这个项目的设计逻辑和使用方式。
> 每次重大修改后，你（或 Claude）应同时更新 `CLAUDE.md` 和本文件。

---

## 项目定位

**ClawKnow** 是一个**完全由 Claude 驱动的多知识库管理系统**，核心目标是：

- 把你散乱的 LLM 学习笔记自动整理成飞书知识库（多层级页面结构）
- 在学习过程中随时提问，Claude 先查本地知识库再回答，不够再联网
- 把每次对话中的要点一句话"归档"进知识库，避免知识流失
- 记录面试/笔试经历，关联到知识库节点，同步到飞书
- **支持多个相互隔离的知识库**（例如：LLM 笔记 / 工作项目 / 读书笔记）

**关键理念**：Claude 本身就是智能层，Python 脚本只是数据读写工具。
你不需要部署任何模型服务，不需要向量数据库，不需要 RAG 框架。

---

## 为什么需要多 workspace（知识库隔离）

v0 版本只有一个全局知识库（`data/knowledge_tree.json`），带来几个问题：

1. **主题混杂**：LLM 笔记、面试记录、工作项目笔记全混在一棵树里，搜索精度差
2. **飞书空间绑定死**：所有内容只能同步到一个飞书 wiki 空间
3. **无法并行管理多个学习方向**：比如同时维护"LLM 知识库"和"系统设计知识库"

v1 的 workspace 模型解决这些问题：每个知识库 = 一个独立目录，有自己的树、面试记录、
可选的飞书空间绑定，互不干扰。

---

## `kb.yaml` 工作原理

每个 workspace 目录下有一个 `kb.yaml` 文件（会提交到 git），它是这个知识库的配置文件：

```yaml
id: default               # 必须和目录名一致
name: LLM 知识库          # 显示用的名称
description: 我的 LLM 学习笔记
docs_dir: docs            # 相对于项目根目录；plan-wiki 从这里读文档
feishu_space_id: ""       # 留空 = 用 .env 里的全局 FEISHU_WIKI_SPACE_ID
                          # 填了 = 只有这个知识库同步到这个飞书空间
created_at: "2026-03-18"
```

`kb.yaml` 是版本控制的（它定义知识库的"元数据"），
而知识树数据（`knowledge_tree.json`）和面试记录（`interviews/*.json`）是 gitignore 掉的
（它们是你的私人内容，不应该进代码库）。

---

## Claude Skills 是什么，为什么边界很重要

### Skills 是什么

ClawKnow 里的"skill"是 Claude Code 的编排单元，不是独立程序：

- **SKILL.md frontmatter** 告诉 Claude：什么时候自动调用这个 skill（`description` 字段）
- **SKILL.md body** 告诉 Claude：被调用后怎么执行（步骤、脚本、确认规则）
- **scripts/** 里的 Python 脚本只是数据管道（读写文件、调飞书 API）
- **Claude 自身**负责所有推理、总结、判断——不需要额外调模型 API

每个 skill 就是一个"责任边界"：一个 skill 只做一件事，且只写它该写的文件。

### 为什么边界太宽会出问题

以 `ask-kb` 为例，之前的 description 写着：
> "即使用户没有明确提到知识库，只要是 AI 技术问答都应该触发"

这会导致：
- 你随便问"什么是 Python 装饰器"，ask-kb 也被激活，去跑 search_kb.py
- 多轮对话里 ask-kb 和 archive 都想处理"归档"请求，产生重复行为
- 触发太频繁导致 Claude 在不必要的时候先跑脚本再回答，降低响应速度

**正确的设计原则**：每个 skill 的 `description` 应该尽量窄——只描述它独特的触发场景，
并明确写出"不触发"的反例，防止误激活。

### 五个 skill 的职责边界

| Skill | 职责 | 只读/只写 |
|-------|------|---------|
| plan-wiki | 分析文档 → 生成知识树结构 | 写（覆盖 knowledge_tree.json）|
| sync-wiki | 本地知识树 → 飞书页面 | 写（飞书 + 更新 tokens）|
| ask-kb | 检索知识库 + 回答 AI/ML 问题 | **只读** |
| archive | 归档对话要点 → 类型化记忆记录 → 重新生成节点摘要 | 写（kb_index.db/memories + knowledge_tree.json summary）|
| interview | 记录面试、讨论答案、关联知识库 | 写（interviews/*.json）|

**关键规则**：
- `ask-kb` 永远不写文件——归档必须由 `archive` 处理
- `archive` 不调用 `sync-wiki`——只提醒用户去同步
- `sync-wiki` 是唯一向飞书推送知识树节点的 skill

### 统一的 SKILL.md 结构

所有 skill 现在都遵循相同的 body 结构：

1. **元数据表** — 用途、输入、输出、副作用、是否需要确认
2. **触发条件** — 正例（会触发）+ 反例（不触发）
3. **执行流程** — 编号步骤 + bash 命令
4. **预览/确认协议** — 写操作前的 preview 模板（有写操作的 skill 必须有）
5. **错误处理** — 错误 → 处理方式表

### 写操作必须经过 preview/confirm

凡是会修改文件或调用飞书 API 的 skill，**必须**：
1. 先展示一个"预览块"（格式标准化）
2. 等待用户明确输入"确认"或等效词后才执行
3. 不能静默写入

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
| `pyyaml` 是允许的 | 它是格式解析库，不是模型 API；用于读写 `kb.yaml` |

---

## 用到的技术栈与基本原理

### Python 共享模块（`lib/`）

| 文件 | 作用 |
|------|------|
| `lib/config.py` | 从 `.env` 读取飞书/Anthropic 配置 |
| `lib/feishu.py` | 封装飞书 Wiki V2 + Docx V1 API |
| `lib/workspace.py` | workspace 路径解析、`kb.yaml` 读写、workspace 初始化 |
| `lib/retrieval.py` | **新增**：FTS5 两阶段检索 + 类型化记忆读写（见下节）|

### 各 skill 脚本

| 脚本 | 变化 |
|------|------|
| `plan_structure.py` | 新增 `--kb` 参数；docs_dir 从 `kb.yaml` 读取 |
| `sync_to_feishu.py` | 新增 `--kb` 参数；可读取 workspace 的 feishu_space_id |
| `search_kb.py` | 新增 `--kb` 参数 |
| `archive_to_kb.py` | 新增 `--kb` 参数 |
| `manage_interview.py` | 新增 `--kb` 参数；面试记录存到对应 workspace 目录 |

所有脚本默认 `--kb default`，旧用法完全兼容。

---

## 检索层（FTS5 两阶段检索）

### 为什么用 FTS5，而不是 Embedding

旧版 `search_kb.py` 使用子串匹配：对每个节点的 `title` 和 `summary` 做 `.lower() in` 判断，
中文分词效果差（找"注意力"却搜不到"自注意力"），无法排序，只能靠简单加权。

新版改用 **SQLite FTS5**（Python 标准库 `sqlite3`，不需要额外依赖）：

- `unicode61` tokenizer：把每个 CJK 字符视为独立 token，中文检索质量显著提升
- **BM25 排序**（SQLite 内置 `bm25()` 函数）：基于词频 + 逆文档频率打分，结果按相关性排序
- 零外部依赖：不需要 Embedding API、不需要模型服务，纯本地 SQLite

**为什么不用 Embedding？**

| 方案 | 优点 | 缺点 | 为何不选 |
|------|------|------|---------|
| FTS5 BM25 | 零依赖、离线、快 | 词法匹配，不理解语义 | ✅ 已实现 |
| Sentence-Transformer（本地） | 语义相似度 | 需要下载模型（几百MB）、有 GPU 更好 | 个人KB规模不需要 |
| OpenAI Embedding API | 语义质量高 | 付费、联网、数据离开本地 | 违反硬约束（不引入新付费API）|

对于个人知识库（几十到几百个节点），BM25 + Claude 自身的理解已经足够好。

### 两阶段检索流程

```
用户提问
   │
   ▼
Stage 1: fts_nodes MATCH query
   │     BM25 排序，取 Top-K 节点（title + summary 字段）
   │
   ▼
Stage 2: 每个匹配节点 → 获取相关证据
   ├── fts_chunks MATCH query（过滤：kb_path 包含节点路径）
   └── fts_memories MATCH query（过滤：kb_path 包含节点路径）
         ↓
   + Global pass（不过滤路径，捕获未关联节点的 chunks/memories）
         ↓
   返回结构化结果：📚 节点 / 📄 文档片段 / 🧠 归档记忆 / ⚠️ 知识空白提示
```

### 数据模型（`workspaces/<kb_id>/kb_index.db`）

```
fts_nodes        — KB 节点索引
  title          (indexed)    节点标题
  summary        (indexed)    节点摘要
  kb_path        (unindexed)  "大方向 > 子类 > 知识点"
  node_token     (unindexed)  飞书 node_token（已同步则有值）
  updated_at     (unindexed)  最近索引时间

fts_chunks       — 文档片段索引
  content        (indexed)    切分后的段落文本
  chunk_id       (unindexed)  SHA256(source_id + chunk_index)
  source_id      (unindexed)  SHA256(file_path)
  source_title   (unindexed)  文件名（美化后）
  source_path    (unindexed)  文件绝对路径
  kb_path        (unindexed)  关联的 KB 节点路径（可为空）
  chunk_index    (unindexed)  在源文档中的位置（0-based）
  created_at     (unindexed)  索引时间

fts_memories     — 归档记忆索引
  content        (indexed)    归档的对话摘要文本
  memory_id      (unindexed)  SHA256(kb_path + archived_at + content[:64])
  kb_path        (unindexed)  目标 KB 节点路径
  archived_at    (unindexed)  归档时间（ISO-8601）

sources          — 文档元数据（普通表，用于变更检测）
  source_id, file_path, title, content_hash, chunk_count, indexed_at

index_state      — 索引状态（普通表）
  key='tree_hash'  → knowledge_tree.json 的 SHA256，用于自动增量重建判断
```

### 自动重建逻辑

`search_kb.py` 每次运行时检查 `knowledge_tree.json` 的 SHA256 是否与 `index_state.tree_hash` 匹配：
- 匹配 → 跳过，直接搜索
- 不匹配（树有更新）→ 自动重建 `fts_nodes`，打印提示到 stderr

文档片段（`fts_chunks`）需要手动调用 `build_index.py --index-docs` 更新，不自动重建（避免每次搜索都重新处理所有文档）。

### 归档时同步更新索引

`archive_to_kb.py` 在写入类型化记忆后：
1. 把记忆写入 `memories` 结构化表（类型、置信度、来源引用）
2. 同步镜像到 `fts_memories`（保持搜索兼容性）
3. 调用 `regen_node_summary()` 重新生成 `knowledge_tree.json` 中节点的 `summary`（非追加）
4. 重建 `fts_nodes`（反映新生成的 summary）

这些步骤是 best-effort（失败不中断归档），日志打印到 stderr。

### 演示数据

运行 `python tools/seed_demo.py` 创建一个独立的 `demo` workspace，包含：
- 10 个 LLM 知识节点（Transformer、注意力、MoE、Flash Attention、RLHF、GRPO 等）
- `docs/demo_llm_notes.md` 的文档片段
- 2 条示例归档记忆

测试命令：`python .claude/skills/ask-kb/scripts/search_kb.py --kb demo MoE 路由`

---

## 类型化记忆（Typed Memory）——归档机制重设计

### 为什么"追加 summary"是糟糕的工程实践

旧版 `archive` 的工作方式：把新内容以 `---\n[日期] 补充：\n- 要点` 格式拼接到节点的
`summary` 字段后面。看似简单，实则有几个根本性问题：

1. **摘要变成垃圾桶**：归档 5–10 次后，`summary` 变成一堆 `---` 分隔的文本块，
   没有结构，搜索时 BM25 评分被稀释，阅读时无法分辨什么是定义、什么是疑问、什么是来源。

2. **无法区分知识质量**：一条已经验证的事实（`"Mixtral 激活 2/8 个专家"`）
   和一条还没确认的猜测（`"Expert Capacity 设过小可能导致不稳定？"`）
   混在一起，Claude 下次检索时无从判断可信度。

3. **无法按来源追溯**：不知道某条知识来自哪篇论文、哪次对话，无法验证或更新。

4. **摘要不可重建**：如果 summary 写乱了，只能手动清理，没有机制从原始数据重新生成。

### 类型化记忆的工作方式

新版 `archive` 把每条知识要点存为独立的**记忆记录**（memory record），写入
`kb_index.db` 的 `memories` 结构化表：

```
memories 表字段：
  memory_id   — SHA-256 稳定 ID，幂等去重
  type        — concept / fact / insight / source_note / question / decision
  content     — 知识内容（一到两句话）
  kb_path     — 归属节点路径
  source_refs — 来源引用列表（JSON 数组）
  author      — claude 或 user
  confidence  — high / medium / low
  created_at  — 写入时间
```

归档后，`regen_node_summary()` 从该节点的所有记忆生成结构化 `summary`，
按类型顺序排列，**完全替换**旧摘要：

```
[概念] MoE 通过 Gate 网络将 FFN 替换为稀疏激活的多个专家子网络
[事实] Mixtral 8×7B 每次激活 2/8 专家，推理 FLOPs 与 13B Dense 模型相当
[洞察] Expert Capacity 设置过小会导致 token dropping，需要实验调整
[来源] Paper: Switch Transformers (Fedus et al., 2021)
[待解答] Load Balancing Loss 系数 α 过大对训练稳定性的具体影响？
```

这个过程**不调用任何外部 API**，完全在本地 SQLite 里完成，确定性输出。

### 归档流程对比（Before vs After）

**Before（旧：追加模式）**

```
# 第一次归档（2026-03-18）
节点 summary：
  "MoE 将 FFN 替换为稀疏专家，Top-K 路由。"

# 第二次归档（2026-03-19）
节点 summary（追加后）：
  "MoE 将 FFN 替换为稀疏专家，Top-K 路由。
  ---
  [2026-03-19] 补充：
  - Expert Capacity 是防止专家过载的上限，超出则 token dropping
  - DeepSeekMoE 引入 Fine-grained expert segmentation
  ---
  [2026-03-20] 补充：
  - Load Balancing Loss 系数 α 建议 0.01，太大会干扰主任务训练"

# 问题：5 次归档后，summary 是一堵墙，无法判断哪条可信，哪条是疑问
```

**After（新：类型化记忆）**

```
# memories 表（结构化，每条独立）：
memory_id: abc...  type: concept     content: "MoE 将 FFN 替换为稀疏专家，Top-K 路由"           confidence: high
memory_id: def...  type: fact        content: "Expert Capacity 是防止专家过载上限，超出则 token dropping"  confidence: high  source_refs: ["DeepSeekMoE论文"]
memory_id: ghi...  type: fact        content: "DeepSeekMoE 引入 Fine-grained expert segmentation"       confidence: high  source_refs: ["DeepSeekMoE论文"]
memory_id: jkl...  type: insight     content: "Load Balancing Loss 系数 α 建议 0.01，太大会干扰训练"       confidence: medium
memory_id: mno...  type: question    content: "α 过大对训练稳定性的具体影响？"                             confidence: low

# 自动生成的 summary（可随时从 memories 重建）：
  [概念] MoE 将 FFN 替换为稀疏专家，Top-K 路由
  [事实] Expert Capacity 是防止专家过载上限，超出则 token dropping
  [事实] DeepSeekMoE 引入 Fine-grained expert segmentation
  [洞察] Load Balancing Loss 系数 α 建议 0.01，太大会干扰训练
  [待解答] α 过大对训练稳定性的具体影响？
```

优势：
- **结构清晰**：FTS5 搜索能看到置信度和类型标签
- **可重建**：`--regen-only` 随时从 memories 重新生成干净的 summary
- **可演进**：可按类型过滤（只看 `question`、只看 `concept`）
- **来源可溯**：`source_refs` 字段明确记录出处

### 六种记忆类型的使用指南

| 类型 | 中文标签 | 用途 | 典型示例 |
|------|---------|------|---------|
| `concept` | [概念] | 核心定义或原理 | "MoE 通过 Gate 网络选择 Top-K 专家" |
| `fact` | [事实] | 可验证的具体数据或行为 | "Mixtral 8×7B 推理 FLOPs 与 13B 相当" |
| `insight` | [洞察] | 对比、权衡或经验结论 | "Expert Capacity 设置需要实验调整" |
| `source_note` | [来源] | 论文/文章/项目引用 | "Paper: Switch Transformers, Fedus 2021" |
| `question` | [待解答] | 尚未验证的问题 | "α 过大的稳定性影响？" |
| `decision` | [决策] | 项目或实践决定 | "本项目暂不启用 Expert Capacity" |

**置信度**的含义：
- `high`：已经在可靠来源中验证
- `medium`：有合理依据，但未完全验证
- `low`：假设或猜测，需要后续确认

---

### 目录结构（v1，含检索层）

```
workspaces/
├── default/                  # 默认知识库（适合大多数人只用一个知识库的场景）
│   ├── kb.yaml               # 配置文件，进 git
│   ├── knowledge_tree.json   # 知识树，gitignored
│   ├── kb_index.db           # FTS5 索引，gitignored（自动生成）
│   └── interviews/           # 面试记录，gitignored
└── work-notes/               # 示例：第二个知识库
    ├── kb.yaml
    ├── knowledge_tree.json
    ├── kb_index.db
    └── interviews/
```

---

## 幂等同步（Idempotent Sync）

### 为什么 Create-Only 同步是危险的

旧版 `sync-wiki` 的行为：
- 每次运行都**无条件**在飞书创建所有节点
- 跑两次 = 飞书里出现两份完全相同的知识库
- 如果中途失败，已创建的节点无法回滚，只能手动到飞书删除

这使得用户必须非常小心地只运行一次，并且无法安全重试失败的同步。

### 新版幂等同步的设计

核心机制：**`feishu_map.json`** 映射文件（每个 workspace 一份，gitignored）。

```json
{
  "nodes": {
    "LLM知识库 > MoE架构": {
      "node_token": "abc...",
      "obj_token": "xyz...",
      "content_hash": "sha256..."
    }
  }
}
```

每次同步前，脚本计算本地知识树与 map 的**差异（diff）**：

| 状态 | 操作 |
|------|------|
| 路径在 map，`content_hash` 未变 | **skip**（不调任何 API） |
| 路径在 map，`content_hash` 变了 | **update_content**（只更新文档正文） |
| 路径不在 map，但树节点有 token | **update_content**（从旧格式恢复）|
| 路径不在 map，无 token | **create**（新建节点 + 写内容）|

每次成功的 create/update 后**立即保存 map**，所以中途失败可以安全重跑。

### 使用流程

**首次同步（全新知识库）：**

```bash
# 1. 先看 dry-run（默认行为，不写任何东西）
python .claude/skills/sync-wiki/scripts/sync_to_feishu.py --kb default

# 2. 确认预览后执行
python .claude/skills/sync-wiki/scripts/sync_to_feishu.py --kb default --apply
```

**飞书已有节点，但 feishu_map.json 为空（首次使用幂等版）：**

```bash
# 先恢复映射（BFS 扫描飞书，按标题路径匹配）
python .claude/skills/sync-wiki/scripts/sync_to_feishu.py --recover --apply

# 然后再做内容更新
python .claude/skills/sync-wiki/scripts/sync_to_feishu.py --apply
```

**同步面试记录：**

```bash
python .claude/skills/sync-wiki/scripts/sync_to_feishu.py --apply --interviews
```

### 页面内容渲染

同步时，每个新建/更新的节点会自动写入正文内容，包括：
- 节点的 `summary` 字段（`knowledge_tree.json` 中）
- 该节点下所有类型化记忆（从 `kb_index.db` 读取，格式化为 `[概念]`、`[事实]` 等标签）

**不调用任何外部 API**，全部在本地完成。

---

## 从 v0 迁移到 v1（迁移路径）

如果你之前已经在用 ClawKnow（v0，只有 `data/` 目录），执行一次迁移脚本即可：

```bash
python tools/migrate_legacy.py
```

脚本会：
1. 创建 `workspaces/default/` 目录和 `kb.yaml`
2. 把 `data/knowledge_tree.json` 复制到 `workspaces/default/knowledge_tree.json`
3. 把 `data/interviews/*.json` 复制到 `workspaces/default/interviews/`

**注意**：脚本只复制，不删除原文件，可以多次运行。
迁移后你可以手动删除 `data/`（确认 workspace 数据正确后）。

---

## 代码与文档如何协同演进

```
你说想改/加功能
       ↓
Claude 读 CLAUDE.md（了解约束和结构）
       ↓
Claude 修改/新增代码
       ↓
如果架构/数据模型/约束有变化
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

1. **看一眼 CLAUDE.md** 里的"Non-Goals and Constraints"，确认你的想法不违反约束
2. **确认路径深度**：脚本用 `Path(__file__).resolve().parents[4]` 找项目根目录（深度固定为 4）
3. **新建 workspace**：用 `lib.workspace.init_workspace()` 或参考 `workspaces/default/` 手动创建
4. **同步到飞书前一定要确认**：不幂等，跑两次会创建重复节点
5. **新增共享代码**：只有 2 个以上 skill 用到才放进 `lib/`，否则放在 skill 自己的 `scripts/` 里

---

## 目前的限制

1. **检索质量**：FTS5 BM25 + `unicode61` tokenizer，比原来的子串匹配好得多。
   中文仍是字符级 tokenization（非 jieba 词级分词），极复杂的语义查询仍可能漏掉节点，
   但对个人知识库规模（< 500 节点）已足够。

2. **同步已幂等**：`sync-wiki` 现在可以安全重复运行。`feishu_map.json` 记录已同步节点，
   第二次运行会 skip 所有未变更的节点。

3. **只能写飞书，不能读回**：知识库的权威数据源是本地 JSON，不是飞书。

4. **标题改名不自动同步**：如果本地节点标题修改后，`sync-wiki` 只更新文档正文内容，
   不会重命名飞书页面标题。需要在飞书手动改标题，然后更新 `feishu_map.json`。

5. **`plan_structure.py` 需要 `ANTHROPIC_API_KEY`**：项目里唯一需要 API key 的地方。
   其他所有功能不需要。

6. **feishu_space_id 覆盖是进程级的**：每次运行脚本时临时覆盖，不持久化到 config。

---

## 下一步建议

| 优先级 | 功能 | 说明 |
|--------|------|------|
| ✅ 已完成 | FTS5 检索升级 | `lib/retrieval.py` + `kb_index.db` 两阶段检索，BM25 排序 |
| ✅ 已完成 | 类型化记忆归档 | `memories` 表 + `write_memory` / `regen_node_summary`，替换 summary 追加模式 |
| ✅ 已完成 | 幂等同步 | `feishu_map.json` + dry-run/apply/recover 模式，安全重试 |
| ✅ 已完成 | 内容渲染 | 同步时自动写入摘要 + 类型化记忆到飞书文档正文 |
| ✅ 已完成 | 面试同步 | `--interviews` 把面试 JSON 同步为 `面试记录` 下的飞书页面 |
| 中 | skill-creator 评估 | 对每个 skill 跑 benchmark，改进触发描述质量 |
| 低 | `ws` CLI 小工具 | `python tools/ws.py new <kb_id>` 一行命令创建新 workspace |
| 低 | 标题改名同步 | 检测标题变更，调用飞书节点重命名 API |
| 低 | 飞书内容读回 | 双向同步：把飞书页面内容同步回本地树的 summary 字段 |
