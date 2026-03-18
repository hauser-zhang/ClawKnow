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
| archive | 归档对话要点到指定知识树节点 | 写（追加 summary）|
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
| `lib/workspace.py` | **新增**：workspace 路径解析、`kb.yaml` 读写、workspace 初始化 |

### 各 skill 脚本

| 脚本 | 变化 |
|------|------|
| `plan_structure.py` | 新增 `--kb` 参数；docs_dir 从 `kb.yaml` 读取 |
| `sync_to_feishu.py` | 新增 `--kb` 参数；可读取 workspace 的 feishu_space_id |
| `search_kb.py` | 新增 `--kb` 参数 |
| `archive_to_kb.py` | 新增 `--kb` 参数 |
| `manage_interview.py` | 新增 `--kb` 参数；面试记录存到对应 workspace 目录 |

所有脚本默认 `--kb default`，旧用法完全兼容。

### 目录结构（v1）

```
workspaces/
├── default/                  # 默认知识库（适合大多数人只用一个知识库的场景）
│   ├── kb.yaml               # 配置文件，进 git
│   ├── knowledge_tree.json   # 知识树，gitignored
│   └── interviews/           # 面试记录，gitignored
└── work-notes/               # 示例：第二个知识库
    ├── kb.yaml
    ├── knowledge_tree.json
    └── interviews/
```

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

1. **检索质量有限**：子串匹配，中文分词不好，复杂查询可能漏节点。
   如果节点超过几百个，考虑升级到 SQLite FTS5（不需要 Embedding）。

2. **同步不幂等**：`sync-wiki` 跑两次 = 飞书里出现两份。**每次同步前必须确认。**

3. **只能写飞书，不能读回**：知识库的权威数据源是本地 JSON，不是飞书。

4. **没有增量同步**：每次全量创建，不会跳过已有 `node_token` 的节点。

5. **`plan_structure.py` 需要 `ANTHROPIC_API_KEY`**：项目里唯一需要 API key 的地方。
   其他所有功能不需要。

6. **feishu_space_id 覆盖是进程级的**：每次运行脚本时临时覆盖，不持久化到 config。

---

## 下一步建议

| 优先级 | 功能 | 说明 |
|--------|------|------|
| 高 | FTS5 检索升级 | 用 SQLite FTS5 索引替代子串匹配，提升中文检索质量 |
| 高 | 增量同步 | 同步前检查 node_token 是否已存在，跳过已创建节点 |
| 中 | 面试总结页 | 把面试 JSON 生成 Markdown 摘要，写入飞书节点正文 |
| 中 | skill-creator 评估 | 对每个 skill 跑 benchmark，改进触发描述质量 |
| 低 | `ws` CLI 小工具 | `python tools/ws.py new <kb_id>` 一行命令创建新 workspace |
| 低 | 飞书内容读回 | 双向同步：把飞书页面内容同步回本地树的 summary 字段 |
