---
name: ingest-paper
description: >
  导入一篇学术论文到知识库，填写结构化元数据（标题、摘要、方法、核心主张、局限性、
  开放问题），支持从 URL/arXiv/DOI 获取基本信息后由 Claude 补全分析字段。
  触发：用户说"导入论文"、"读一篇论文"、"把这篇论文加进来"、"ingst paper"、
  "ingest paper"，或给出一个 arXiv/DOI/PDF 链接并说要加到知识库中。
  不触发：仅讨论论文内容无导入意图（→ discuss-paper）；普通问答（→ ask-kb）；归档（→ archive）。
  写操作：保存 workspaces/<kb_id>/papers/<paper_id>.json；更新 kb_index.db 的 fts_papers 表。
allowed-tools: Read, Bash(python *), WebFetch, WebSearch
---

# 导入学术论文

## 元数据

| 项目 | 内容 |
|------|------|
| 用途 | 解析论文信息 → Claude 分析填充摘要/方法/主张 → 保存结构化 JSON + 更新 FTS 索引 |
| 输入 | 论文 URL / arXiv ID / DOI / 用户粘贴的摘要文本 |
| 输出 | 论文导入确认（paper_id + 标题 + 状态） |
| 副作用 | **写** `workspaces/<kb_id>/papers/<paper_id>.json`；**写** `kb_index.db/fts_papers` |
| 需要确认 | 是 — 展示解析结果预览后等用户确认 |

## 触发条件

**会触发：**
- "帮我导入这篇论文 arxiv.org/abs/2401.xxxxx"
- "把 Attention Is All You Need 加到知识库"
- "ingest paper：Flash Attention 2"
- "这篇论文我想存进来：[粘贴摘要]"

**不触发：**
- "解释一下 Flash Attention 的原理" → ask-kb
- "我想讨论一下 MoE 论文" → discuss-paper（如已导入）
- "归档一下" → archive
- "同步到飞书" → sync-wiki

## 论文数据模型

```json
{
  "paper_id": "sha256-derived-id",
  "title": "string",
  "authors": ["string"],
  "year": 2024,
  "doi": "10.xxx/yyy",
  "arxiv_id": "2401.xxxxx",
  "venue": "NeurIPS 2024",
  "url": "https://...",
  "abstract_summary": "string — Claude 对摘要的精炼总结（2-4 句话）",
  "method_summary": "string — 核心方法/贡献的技术要点（3-6 句话）",
  "key_claims": ["string — 每条是一个可验证的核心主张"],
  "limitations": ["string — 论文自述或明显的局限性"],
  "open_questions": ["string — 读后产生的开放问题"],
  "related_kb_nodes": ["KB 节点路径"],
  "user_insights": [],
  "status": "reading",
  "added_at": "ISO-8601",
  "updated_at": null
}
```

## 执行流程

### 第一步：获取论文信息

**如果用户提供了 URL/arXiv ID/DOI：**
- arXiv ID → `https://arxiv.org/abs/<id>` 用 WebFetch 获取摘要页面
- DOI → 尝试 `https://doi.org/<doi>` 获取元数据
- 普通 URL → WebFetch 获取页面内容

**如果用户粘贴了摘要：**
- 直接从文本提取标题、作者、年份信息

### 第二步：Claude 分析填充字段

Claude 自身完成分析（无需调外部模型 API）：
- `abstract_summary`：提炼摘要核心（2-4 句话，精准）
- `method_summary`：技术方法要点（3-6 句话，可以包含公式描述）
- `key_claims`：2-5 条可验证的主要声明
- `limitations`：显著局限性（未提则留空列表）
- `open_questions`：读后产生的值得追问的问题
- `related_kb_nodes`：对照知识树，填写关联的 KB 路径

### 第三步：预览并确认

展示论文卡片预览：

```
📄 论文导入预览

标题：Flash Attention 2: Faster Attention with Better Parallelism and Work Partitioning
作者：Tri Dao (2023)
状态：reading
DOI/arXiv：2307.08691

摘要总结：
  Flash Attention 2 改进了原版的线程并行策略和工作分配，在 A100 上实现接近理论峰值
  的 FLOP 利用率，比 Flash Attention 1 快 2-3x...

方法要点：
  - 重新设计了前向/反向 CUDA Kernel 的线程块分配方式...

核心主张 (3 条)：
  - FA2 在 A100 上达到 72% FLOPs 利用率（FA1 仅 25%）...

关联 KB 节点：
  - LLM Knowledge Base > Inference Optimization > Flash Attention

---
确认导入？（输入"确认"保存，或说明需要修改的字段）
```

### 第四步：保存

```bash
python ${CLAUDE_SKILL_DIR}/scripts/ingest_paper.py \
  --kb <kb_id> \
  --data '<json_string>'
```

`--data` 参数接受完整论文 JSON 字符串。脚本保存 JSON 文件并更新 FTS 索引。

### 第五步：导入后提示

- 确认保存路径：`workspaces/<kb_id>/papers/<paper_id>.json`
- 提示后续操作：
  > "论文已导入。可以说'讨论一下这篇论文'深入阅读，或说'关联 KB 节点'建立知识图谱边。"

## 错误处理

| 错误 | 处理方式 |
|------|---------|
| URL 无法访问 | 提示用户粘贴摘要文本后手动填充 |
| JSON 格式错误 | 脚本打印具体错误，重新生成 JSON 后重试 |
| `knowledge_tree.json` 不存在 | 关联节点留空，导入后提示建立知识树 |
| 论文已存在（相同 DOI/arXiv ID） | 提示是否覆盖更新 |
