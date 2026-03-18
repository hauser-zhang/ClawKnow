---
name: interview
description: >
  记录面试/笔试/机试经历，逐题讨论最佳答案，关联知识库节点，支持同步到飞书。
  触发：用户提到"面试"、"笔试"、"机试"、"面经"、"八股文"、"今天面了"、"面试题"、
  "XX 公司面试"、"帮我看看面试记录"、"面试准备"。
  不触发：仅讨论某技术概念无面试背景（→ ask-kb）；
  "归档"（→ archive）；"同步到飞书知识树"（→ sync-wiki）。
  写操作：保存面试记录 JSON（需确认）；同步到飞书（需确认）。
allowed-tools: Read, Bash(python *), WebSearch
---

# 面试知识管理

## 元数据

| 项目 | 内容 |
|------|------|
| 用途 | 记录面试题 → 讨论答案 → 关联知识库 → 保存 / 同步飞书 |
| 输入 | 用户描述的面试经历或面试题目 |
| 输出 | 面试记录 JSON 文件；飞书面试页面（按需）|
| 副作用 | **写** `workspaces/<kb_id>/interviews/` 下的 JSON 文件；飞书写操作（按需）|
| 需要确认 | 保存前确认；同步飞书前确认 |

## 触发条件

**会触发：**
- "我今天面试了字节的大模型岗"
- "帮我回顾一下这次笔试题"
- "整理一下我的面经"
- "帮我看看之前面试都考了些什么"
- "八股文复习"

**不触发：**
- "解释一下 MoE" — 无面试背景 → ask-kb
- "归档一下" → archive
- "同步知识库到飞书" → sync-wiki

## 场景一：记录刚结束的面试

### 步骤 1：收集基本信息

如对话中未提及，主动询问：
- 公司名称
- 日期（默认今天）
- 类型：面试 / 笔试 / 机试
- 岗位（可选）

### 步骤 2：逐题讨论

对每道题：
1. 用户描述题目
2. 判断题目类型（八股 / 算法 / 系统设计 / 项目 / 其他）
3. 对于八股/技术题：先检索知识库
   ```bash
   python ${CLAUDE_SKILL_DIR}/../ask-kb/scripts/search_kb.py "<关键词>"
   ```
4. 给出参考答案；知识库不够时联网搜索补充
5. 确认最终答案，记录到题目列表

### 步骤 3：预览并确认保存

所有题目讨论完成后，展示预览：

```
📋 面试记录预览

  公司：字节跳动
  日期：2026-03-18
  类型：面试
  岗位：大模型算法工程师
  题目数：3 题（八股 2 题，算法 1 题）

  题目列表：
  1. [八股] MoE 的工作原理和路由机制
  2. [算法] 实现 LRU Cache
  3. [八股] RLHF 的训练流程

---
确认保存？（输入"确认"保存记录，或说明需要修改的内容）
```

### 步骤 4：保存记录

用户确认后，构造 JSON 并通过 stdin 传入脚本：

```bash
# 默认 workspace
python ${CLAUDE_SKILL_DIR}/scripts/manage_interview.py save

# 指定 workspace
python ${CLAUDE_SKILL_DIR}/scripts/manage_interview.py save --kb <kb_id>
```

JSON 格式参见 `references/record_schema.md`。

## 场景二：查看历史记录 / 面试准备

### 步骤 1：列出历史记录

```bash
python ${CLAUDE_SKILL_DIR}/scripts/manage_interview.py list
# 指定 workspace：
python ${CLAUDE_SKILL_DIR}/scripts/manage_interview.py list --kb <kb_id>
```

### 步骤 2：分析高频考点

统计各类别题目频率，找出薄弱环节，给出复习建议：
- 结合知识库（哪些知识点被考到但没有记录）
- 指出"算法题考了 N 次，知识库中尚无算法专题"等洞察

## 场景三：同步面试记录到飞书

### 步骤 1：预览并确认

```
⚠️  飞书同步操作

  将在飞书创建"面试记录"父节点，并为每条记录创建子页面。
  此操作不可逆，重复运行会创建重复节点。

  待同步记录：N 条
  目标空间：<FEISHU_WIKI_SPACE_ID>

---
确认同步？（输入"确认同步"继续）
```

### 步骤 2：执行同步

```bash
python ${CLAUDE_SKILL_DIR}/scripts/manage_interview.py sync
# 指定 workspace：
python ${CLAUDE_SKILL_DIR}/scripts/manage_interview.py sync --kb <kb_id>
```

## 错误处理

| 错误 | 处理方式 |
|------|---------|
| 知识库不存在 | 仍可记录面试，kb_path 留空 |
| 飞书凭证未配置 | 提示配置 `.env`；仍可本地保存 |
| 错误码 99991672 | Bot 未加为飞书空间成员 |

## 参考

- 记录 JSON 格式 → `references/record_schema.md`
- 数据存储位置 → `workspaces/<kb_id>/interviews/YYYYMMDD_HHMMSS_<company>.json`
