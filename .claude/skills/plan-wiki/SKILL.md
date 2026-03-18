---
name: plan-wiki
description: >
  分析用户提供的文档内容，自动规划飞书知识库的树形结构。
  当用户提供了学习文档、要求整理知识体系、讨论知识库如何组织分类、
  或者说"帮我规划一下知识库"、"整理一下这些内容"时自动触发。
  即使用户没有明确说"知识库"，只要涉及到将文档内容进行结构化整理，也应该触发。
allowed-tools: Read, Glob, Bash(python *)
---

# 知识库结构规划

你正在帮助用户将学习文档规划为结构化的飞书知识库。

## 完整流程

### 第一步：读取文档

1. 用 Glob 找到 `docs/` 下所有文件（`.md`, `.txt`, `.rst`）
2. 用 Read 逐个读取内容
3. 如果 `docs/` 为空，提示用户先放入文档

### 第二步：分析并生成知识树

运行规划脚本：

```bash
python ${CLAUDE_SKILL_DIR}/scripts/plan_structure.py
```

脚本会调用 Claude API 分析文档内容，输出结构化的知识树 JSON。

如果脚本因环境问题无法运行，你也可以直接在对话中分析文档内容，
按照下面的 JSON 格式手动生成知识树，然后写入 `data/knowledge_tree.json`。

### 第三步：展示并确认

将知识树以 Markdown 大纲形式展示给用户，例如：

```
- LLM 知识库
  - 预训练
    - Tokenizer: 分词器原理与 BPE/WordPiece/Unigram 对比
    - 数据工程: 预训练数据清洗、去重、质量过滤
  - 后训练
    - SFT: 监督微调的数据构造与训练策略
    - RLHF
      - PPO: 近端策略优化算法
      - GRPO: 组相对策略优化
```

然后问用户：
- 结构是否合理？需要增删哪些分类？
- 层级深度是否合适？
- 是否有遗漏的知识点？

### 第四步：保存

用户确认后，将最终的知识树写入 `data/knowledge_tree.json`。

## 知识树 JSON 格式

```json
{
  "title": "LLM 知识库",
  "children": [
    {
      "title": "预训练",
      "children": [
        {"title": "Tokenizer", "summary": "BPE/WordPiece/Unigram 分词算法原理与对比"},
        {"title": "数据工程", "summary": "预训练数据清洗、去重、质量过滤流程"}
      ]
    },
    {
      "title": "后训练",
      "children": [
        {"title": "SFT", "summary": "监督微调的数据格式与训练策略"},
        {
          "title": "RLHF",
          "children": [
            {"title": "PPO", "summary": "近端策略优化算法原理"},
            {"title": "GRPO", "summary": "组相对策略优化，DeepSeek 提出"}
          ]
        }
      ]
    }
  ]
}
```

**节点字段说明：**
- `title`（必需）：节点标题
- `summary`（叶子节点必需）：知识点摘要，一两句话概括核心内容
- `children`（可选）：子节点数组
- `node_token` / `obj_token`：同步飞书后自动生成，规划阶段不需要

## 规划原则

1. **层次清晰**：2-3 级为主，最深不超过 4 级
2. **分类合理**：参考 LLM 领域常见知识体系
   - 预训练（数据、模型架构、训练方法）
   - 后训练（SFT、RLHF/DPO/GRPO、对齐）
   - 模型架构（Transformer、MoE、SSM）
   - 推理优化（KV Cache、量化、推测解码）
   - 应用（RAG、Agent、多模态、评估）
3. **粒度适中**：每个叶子节点是一个可以独立成文的知识点
4. **可扩展**：结构便于后续添加新的知识点和子分类
