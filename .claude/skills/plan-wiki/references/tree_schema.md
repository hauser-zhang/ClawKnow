# 知识树 JSON Schema

## 节点字段

| 字段 | 类型 | 是否必需 | 说明 |
|------|------|---------|------|
| `title` | string | 必需 | 节点标题 |
| `summary` | string | 叶子节点必需 | 知识点摘要，一两句话 |
| `children` | array | 可选 | 子节点列表；叶子节点省略此字段 |
| `node_token` | string | 系统生成 | 同步飞书后自动写入，规划阶段不需要 |
| `obj_token` | string | 系统生成 | 同步飞书后自动写入，规划阶段不需要 |

## 最小示例

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

## 规划原则

1. **层次**：2–3 级为主，最深不超过 4 级
2. **粒度**：每个叶子节点是一个可以独立成文的知识点
3. **可扩展**：结构便于后续添加新的知识点和子分类

## LLM 领域常见分类参考

- 预训练（数据工程、模型架构、训练技巧）
- 后训练（SFT、RLHF / DPO / GRPO、对齐）
- 模型架构（Transformer、MoE、SSM/Mamba）
- 推理优化（KV Cache、量化、推测解码）
- 应用（RAG、Agent、多模态、评估）
