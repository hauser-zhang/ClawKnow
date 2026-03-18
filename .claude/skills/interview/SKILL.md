---
name: interview
description: >
  管理面试、笔试、机试的记录，讨论面试题目的最佳回答，并关联知识库中的知识点。
  当用户提到"面试"、"笔试"、"机试"、"面经"、"八股文"、"八股"、"算法题"、
  "面试准备"、"XX 公司面试"、"今天面了"、"面试题"、"手撕代码"时自动触发。
  支持创建面试记录、逐题讨论最佳答案、关联知识库节点、同步到飞书。
allowed-tools: Read, Bash(python *), WebSearch
---

# 面试知识管理

帮助用户记录面试经历、讨论题目答案，并关联到知识库。

## 场景一：用户刚面完试，要记录

**对话示例**：
> "我今天面试了字节的大模型岗，有几道题想讨论一下"

**流程**：

1. 收集基本信息（如对话中未提及则主动询问）：
   - 公司名称
   - 日期（默认今天）
   - 类型：面试 / 笔试 / 机试
   - 岗位（如有）

2. 逐个讨论面试题目：
   - 用户描述遇到的问题
   - 讨论分析，给出参考答案
   - 对于八股题，先检索知识库（用 ask-kb 的 search_kb.py）
   - 知识库没有或不够时联网搜索补充
   - 确认最终答案

3. 每道题记录为：
   ```json
   {
     "question": "问题描述",
     "category": "八股 / 算法 / 系统设计 / 项目 / 其他",
     "answer": "讨论后确认的最佳答案",
     "kb_path": ["模型架构", "MoE"]
   }
   ```
   其中 `kb_path` 是知识库中对应知识点的路径（如无对应则留空列表）。

4. 所有题目讨论完成后，保存记录：
   ```bash
   # 默认 workspace
   python ${CLAUDE_SKILL_DIR}/scripts/manage_interview.py save

   # 指定 workspace
   python ${CLAUDE_SKILL_DIR}/scripts/manage_interview.py save --kb <kb_id>
   ```
   通过 stdin 传入 JSON 数据。

## 场景二：用户想准备面试

**对话示例**：
> "帮我看看之前面试都考了些什么"

**流程**：

1. 列出历史记录：
   ```bash
   python ${CLAUDE_SKILL_DIR}/scripts/manage_interview.py list
   # 或指定 workspace：
   python ${CLAUDE_SKILL_DIR}/scripts/manage_interview.py list --kb <kb_id>
   ```
2. 展示各次面试的题目统计（八股 N 题、算法 N 题等）
3. 分析高频考点，给出复习建议
4. 关联到知识库中的薄弱环节

## 场景三：同步面试记录到飞书

当用户要求同步时：
```bash
python ${CLAUDE_SKILL_DIR}/scripts/manage_interview.py sync
# 或指定 workspace：
python ${CLAUDE_SKILL_DIR}/scripts/manage_interview.py sync --kb <kb_id>
```

会在飞书知识库中创建"面试记录"父节点，每次面试一个子页面。

## 面试记录 JSON 格式

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
      "answer": "MoE 通过路由网络将输入分配给不同专家...",
      "kb_path": ["模型架构", "MoE"]
    },
    {
      "question": "实现 LRU Cache",
      "category": "算法",
      "answer": "使用 OrderedDict 或双向链表+哈希表...",
      "kb_path": []
    }
  ]
}
```

## 存储位置

- 面试记录保存在 `workspaces/<kb_id>/interviews/` 目录（默认 kb_id = `default`）
- 每条记录一个 JSON 文件
- 命名格式：`YYYYMMDD_HHMMSS_公司名.json`
