---
name: link-paper-to-kb
description: >
  在论文与知识库节点之间（或节点与节点之间）建立有向关系边，支持多种语义边类型：
  related_to（相关）、depends_on（依赖）、compares_with（对比）、
  derived_from（衍生自）、updated_by（更新/修正）、cites（引用）。
  触发：用户说"关联论文到 KB"、"建立边"、"论文关联"、"link paper"、"link to kb"、
  "这篇论文和 Flash Attention 节点有关"、"加一条 depends_on 边"。
  也触发：用户说"查看关系图"、"列出某节点的边"、"图谱"。
  不触发：导入论文（→ ingest-paper）；讨论论文（→ discuss-paper）；归档记忆（→ archive）。
  写操作：向 kb_index.db 的 edges 表写入边记录（需确认）。
allowed-tools: Read, Bash(python *)
---

# 论文与知识节点关系管理

## 元数据

| 项目 | 内容 |
|------|------|
| 用途 | 在论文/KB节点之间创建有语义的关系边，构建知识图谱 |
| 输入 | 源节点 ID/路径 + 目标节点 ID/路径 + 边类型 |
| 输出 | 边创建/列出确认 |
| 副作用 | **写** `kb_index.db/edges` 表（需确认）；删除边也需确认 |
| 需要确认 | 创建和删除操作需要确认 |

## 触发条件

**会触发：**
- "把 Flash Attention 2 论文关联到 KB 的 Flash Attention 节点"
- "这篇 Mixtral 论文 depends_on 稀疏激活节点"
- "列出 MoE 节点所有关系边"
- "帮我看看知识图谱里的边"
- "建一条 compares_with 边：FA2 对比 FA1"

**不触发：**
- "导入这篇论文" → ingest-paper
- "讨论 Flash Attention 2" → discuss-paper
- "MoE 的原理是什么" → ask-kb

## 边类型参考

| 边类型 | 语义 | 示例 |
|--------|------|------|
| `related_to` | 内容相关，无强方向 | FlashAttention 论文 ↔ KV Cache 节点 |
| `depends_on` | 理解 src 需要先理解 dst | GRPO 依赖 PPO 的基础知识 |
| `compares_with` | 两个节点做对比讨论 | MoE vs Dense model 节点 |
| `derived_from` | src 的结论/方法来自 dst | Flash Attention 2 衍生自 Flash Attention 1 |
| `updated_by` | dst 修正了 src 的某个说法 | 某节点摘要被新论文的结果更新 |
| `cites` | src 明确引用了 dst | GRPO 论文引用 PPO 论文 |

## 执行流程

### 第一步：确认源节点和目标节点

**对于 KB 节点：** 使用节点的 kb_path（如 `LLM Knowledge Base > Inference Optimization > Flash Attention`）

**对于论文：** 使用 paper_id（16 位 hex），可先用 `--list-papers` 查看

### 第二步：预览并确认边

```
🔗 关系边预览

  源: [paper] Flash Attention 2 (2307.08691)
  类型: derived_from
  目标: [kb_node] LLM Knowledge Base > Inference Optimization > Flash Attention
  备注: FA2 改进了 FA1 的线程并行方案

---
确认建立此边？
```

### 第三步：执行

```bash
# 建立一条边
python ${CLAUDE_SKILL_DIR}/scripts/link_paper.py \
  --kb <kb_id> \
  --add-edge \
  --src-id "<paper_id_or_kb_path>" \
  --src-type "paper|kb_node" \
  --dst-id "<paper_id_or_kb_path>" \
  --dst-type "paper|kb_node" \
  --edge-type related_to \
  [--note "<备注>"]

# 列出某节点的所有边
python ${CLAUDE_SKILL_DIR}/scripts/link_paper.py \
  --kb <kb_id> \
  --list-edges \
  --node-id "<kb_path_or_paper_id>"

# 删除一条边
python ${CLAUDE_SKILL_DIR}/scripts/link_paper.py \
  --kb <kb_id> \
  --delete-edge <edge_id>

# 列出所有已导入论文（辅助查 paper_id）
python ${CLAUDE_SKILL_DIR}/scripts/link_paper.py \
  --kb <kb_id> \
  --list-papers
```

### 第四步：操作后提示

建立边后提示：
- "边已建立。运行 `python tools/export_graph.py` 可更新图谱导出文件。"
- "可以用 graph-review 查看整体图谱状态。"

## 错误处理

| 错误 | 处理方式 |
|------|---------|
| edge_type 不合法 | 列出可用边类型，要求用户重选 |
| paper_id 找不到 | 运行 `--list-papers` 后重新确认 |
| 边已存在（同 src+dst+type）| 提示"该边已存在，无需重复添加" |
| 删除不存在的 edge_id | 提示 edge_id 无效 |
