# 面试记录 JSON Schema

## 文件命名

`workspaces/<kb_id>/interviews/YYYYMMDD_HHMMSS_<company>.json`

## 字段定义

| 字段 | 类型 | 是否必需 | 说明 |
|------|------|---------|------|
| `company` | string | 必需 | 公司名称 |
| `date` | string | 必需 | `YYYY-MM-DD` 格式，默认今天 |
| `type` | string | 必需 | `面试` / `笔试` / `机试` |
| `position` | string | 可选 | 岗位名称 |
| `questions` | array | 必需 | 题目列表，至少一题 |

## 题目字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `question` | string | 题目描述 |
| `category` | string | `八股` / `算法` / `系统设计` / `项目` / `其他` |
| `answer` | string | 讨论后确认的最佳答案 |
| `kb_path` | array | 对应知识库节点路径，如 `["模型架构", "MoE"]`；无对应则 `[]` |

## 完整示例

```json
{
  "company": "字节跳动",
  "date": "2026-03-18",
  "type": "面试",
  "position": "大模型算法工程师",
  "questions": [
    {
      "question": "解释 MoE 的工作原理和路由机制",
      "category": "八股",
      "answer": "MoE 通过路由网络将输入分配给不同专家，每次前向传播只激活 Top-K 个专家。路由使用 softmax + TopK 选择，训练时需要辅助 load balancing loss 防止专家坍塌。",
      "kb_path": ["模型架构", "MoE"]
    },
    {
      "question": "实现 LRU Cache",
      "category": "算法",
      "answer": "使用 OrderedDict：get 时 move_to_end，put 时先检查容量，超出则 popitem(last=False)。时间复杂度 O(1)。",
      "kb_path": []
    }
  ]
}
```
