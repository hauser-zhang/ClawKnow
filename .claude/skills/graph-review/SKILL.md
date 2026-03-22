---
name: graph-review
description: >
  分析知识图谱健康状况：识别最近新增内容、长期未更新的停滞节点、无任何支撑材料的薄弱节点，
  以及标题词重叠的候选关系边，输出审查报告并推荐操作。
  触发：用户说"图谱审查"、"review graph"、"检查知识库健康"、"哪些节点没有内容"、
  "有哪些节点太久没有更新"、"graph review"、"知识图谱状态"。
  不触发：仅问某个具体技术概念（→ ask-kb）；导入论文（→ ingest-paper）；归档（→ archive）。
  无写操作，只读审查技能。
allowed-tools: Read, Bash(python *)
---

# 知识图谱健康审查

## 元数据

| 项目 | 内容 |
|------|------|
| 用途 | 读取知识树 + FTS 索引 → 输出结构化审查报告 |
| 输入 | workspace ID（可选）；审查时间窗口参数（可选）|
| 输出 | 四类审查结果：近期活跃 / 停滞节点 / 薄弱节点 / 候选边建议 |
| 副作用 | **无**（只读）|
| 需要确认 | 否 |

## 触发条件

**会触发：**
- "帮我做一次图谱审查"
- "哪些节点太久没有更新了"
- "知识库里有哪些节点没有内容？"
- "graph review"
- "检查一下知识库健康状况"
- "有没有候选的关系边没有建"

**不触发：**
- "Flash Attention 的原理是什么" → ask-kb
- "归档一下" → archive
- "同步到飞书" → sync-wiki

## 四类审查维度

| 类别 | 标签 | 含义 | 典型操作 |
|------|------|------|---------|
| 最近新增 | `[RECENT]` | 最近 N 天内有新归档记忆的节点 | 确认知识在积累 |
| 停滞节点 | `[STALE]` | 有记忆但 > 30 天无更新的节点 | 复习/补充新内容 |
| 薄弱节点 | `[WEAK]` | 叶子节点，无记忆、无文档片段、无关系边 | 归档或关联文档 |
| 候选关系边 | `[LINKS]` | 标题词高度重叠的节点对 | 用 link-paper-to-kb 建立边 |

## 执行流程

### 第一步：运行审查脚本

```bash
# 完整审查（默认 30 天停滞阈值 / 7 天最近窗口）
python e:/ai_projects/feishu-know-llm/tools/review_graph.py --kb <kb_id>

# 自定义时间窗口
python e:/ai_projects/feishu-know-llm/tools/review_graph.py --kb <kb_id> \
  --stale-days 14 --recent-days 3

# 只看薄弱节点
python e:/ai_projects/feishu-know-llm/tools/review_graph.py --kb <kb_id> --only weak

# JSON 输出（Claude 进一步处理）
python e:/ai_projects/feishu-know-llm/tools/review_graph.py --kb <kb_id> --json
```

### 第二步：分析报告并推荐操作

Claude 读取报告后，针对每类结果给出行动建议：

**薄弱节点** (`[WEAK]`)：
- 建议用户"归档"该节点的已知知识要点
- 或用 build_index.py 将相关文档索引进来

**停滞节点** (`[STALE]`)：
- 检查该节点是否仍然相关
- 建议重新学习/更新，或者合并/删除过时节点

**候选关系边** (`[LINKS]`)：
- 展示 2-3 个最值得建立的边
- 引导用户用 link-paper-to-kb 建立 `related_to` 或 `depends_on` 边

### 第三步（可选）：更新图谱导出

完成审查后，建议用户更新图谱文件：

```bash
python e:/ai_projects/feishu-know-llm/tools/export_graph.py --kb <kb_id>
```

这会生成最新的 `graph/nodes.jsonl`、`graph/edges.jsonl`、`graph/graph.json`。

## 图谱文件说明

| 文件 | 格式 | 内容 |
|------|------|------|
| `graph/nodes.jsonl` | JSONL（每行一个节点）| id, type, label, summary, node_token |
| `graph/edges.jsonl` | JSONL（每行一条边）| edge_id, src, src_type, dst, dst_type, type, weight, note |
| `graph/graph.json` | JSON（合并）| `{"nodes": [...], "edges": [...]}` |

这些文件可直接导入 Gephi、Cytoscape、D3.js 等可视化工具。
Claude 也可以直接读取 graph.json 做图谱分析。

## 错误处理

| 错误 | 处理方式 |
|------|---------|
| `knowledge_tree.json` 不存在 | 提示先运行 plan-wiki |
| `kb_index.db` 为空（无记忆）| 仍输出报告，所有节点标记为薄弱 |
| workspace 不存在 | 列出可用 workspace 后重新选择 |
