---
name: ingest-url
description: >
  从网页 URL（知乎、博客、Medium 等）提取知识内容，归档到对应 KB 节点，并注册为参考来源。
  触发：用户给出一个网页链接并说要"加到知识库"、"更新笔记"、"导入这篇文章"、"把这个链接的内容归档"。
  也触发：用户直接给出 URL 并说"这篇文章关于 PPO/Transformer/某主题，帮我整理一下"。
  不触发：导入学术论文（→ ingest-paper）；普通问答（→ ask-kb）；归档已有讨论（→ archive）。
  写操作：向 kb_index.db 写入记忆（通过 archive_to_kb.py）；向 knowledge_tree.json 写入 source_refs（通过 ingest_url.py）。
allowed-tools: Read, Bash(python *), WebFetch, WebSearch
---

# 网页文章导入知识库

## 元数据

| 项目 | 内容 |
|------|------|
| 用途 | 从 URL 提取知识内容 → 归档为结构化记忆 → 注册参考来源 → 可选同步飞书 |
| 输入 | URL（必须）；目标 KB 节点路径（Claude 自动判断或用户指定）；workspace ID（可选）|
| 输出 | 归档的记忆列表；knowledge_tree.json 中节点的 source_refs 更新；飞书页面更新（可选）|
| 副作用 | 写 kb_index.db/memories；写 knowledge_tree.json source_refs |
| 需要确认 | 是 — 展示提取的记忆预览和来源标题，等用户确认后再执行 |

## 触发条件

**会触发：**
- 用户给出 `https://zhuanlan.zhihu.com/p/xxx` 并说"帮我整理到知识库"
- "把这篇文章的内容加到 PPO 节点里"
- "这个博客写的很好，导入到 RLHF 节点"
- "update node with this URL"
- URL + "归档" / "存到知识库" / "更新笔记"

**不触发：**
- 给出 arXiv/DOI 链接（→ ingest-paper）
- 仅讨论文章内容无归档意图（→ ask-kb 或直接回答）

## 执行流程

### 第一步：获取文章内容

```bash
# 先尝试 WebFetch 直接获取
# 如果返回 403 / 空内容，改用 WebSearch 搜索文章标题获取摘要
# 如果两者均失败，提示用户粘贴内容
```

### 第二步：确定目标节点

1. 分析文章主题，在知识树中找到最匹配的节点
2. 展示候选节点让用户确认：
   - `目标节点: LLM Knowledge Base > Post-Training Alignment > RLHF > PPO`
   - `来源标题: <文章标题>`
   - `来源 URL: <URL>`

### 第三步：检查父节点是否需要补全

```bash
python e:/ai_projects/feishu-know-llm/.claude/skills/ask-kb/scripts/search_kb.py \
  --kb <kb_id> "<父节点标题>"
```

如果父节点（如 RLHF）内容为空（无记忆、无摘要），则：
- 用 WebSearch 搜索父节点主题
- 同时归档父节点的基础内容

### 第四步：提取并预览记忆

Claude 从文章中提取知识要点，格式：
```
【归档预览】节点: LLM Knowledge Base > Post-Training Alignment > RLHF > PPO
来源: <文章标题> (<URL>)

类型    置信度  内容
───────────────────────────────────────────
概念    high    PPO (Proximal Policy Optimization) 通过 clip 机制限制策略更新幅度...
事实    high    PPO 的 clip 参数 ε 通常设为 0.2，控制新旧策略比率偏差...
洞察    medium  PPO 相比 TRPO 实现更简单，但 GAE 估计的方差对性能影响大...
...

确认归档以上 N 条记忆到该节点？(yes/no)
```

### 第五步：执行归档

用户确认后，调用 archive_to_kb.py 逐条写入（每条附带 source_refs）：

```bash
python e:/ai_projects/feishu-know-llm/.claude/skills/archive/scripts/archive_to_kb.py \
  --kb <kb_id> \
  --data '<json array of memory dicts>'
```

### 第六步：注册来源引用到节点

```bash
python e:/ai_projects/feishu-know-llm/.claude/skills/ingest-url/scripts/ingest_url.py \
  --kb <kb_id> \
  --node "LLM Knowledge Base > Post-Training Alignment > RLHF > PPO" \
  --url "<URL>" \
  --title "<文章标题>"
```

### 第七步（可选）：同步到飞书

询问用户是否立即同步：

```bash
# dry-run 先预览
python e:/ai_projects/feishu-know-llm/.claude/skills/sync-wiki/scripts/sync_to_feishu.py \
  --kb <kb_id>

# 用户确认后 apply
python e:/ai_projects/feishu-know-llm/.claude/skills/sync-wiki/scripts/sync_to_feishu.py \
  --kb <kb_id> --apply
```

## 预览/确认协议

归档前必须展示：
1. 目标节点路径
2. 来源标题 + URL
3. 每条提取记忆（类型 / 置信度 / 内容）
4. 如有父节点补全，同步预览父节点内容

**不允许跳过确认静默写入。**

## 参考来源优先级规则

当节点已有 source_refs 时：
- **主要参考**（排在前列）：已存在的 source_refs
- **追加到末尾**：新 URL（除非用户明确说"这是最重要的参考"则插到首位）
- **更新正文 vs 仅加参考资料**：
  - 文章有大量新知识点 → 提取记忆归档正文，URL 加入 source_refs
  - 文章与已有内容高度重叠，无新增要点 → 仅将 URL 加入参考资料底部

## 错误处理

| 错误 | 处理方式 |
|------|---------|
| URL 返回 403/blocked | 改用 WebSearch 搜索文章标题；或提示用户粘贴内容 |
| 目标节点在树中找不到 | 列出相似节点让用户选择 |
| knowledge_tree.json 不存在 | 提示先运行 plan-wiki |
| 父节点内容为空 | 自动触发父节点内容搜索补全流程 |
