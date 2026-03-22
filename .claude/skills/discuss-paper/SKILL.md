---
name: discuss-paper
description: >
  围绕已导入的学术论文进行多轮深度讨论，提取理解要点并追加到 user_insights 字段，
  支持将洞察归档到关联的 KB 节点。
  触发：用户说"讨论一下这篇论文"、"我想读一下 XX 论文"、"explain the paper"、
  "跟我讲讲 Flash Attention 论文"，或者在 ingest-paper 之后说"开始讨论"。
  也触发：用户说"看一下我导入的论文"、"列出我的论文"、"paper 列表"。
  不触发：没有导入意图、纯概念提问（→ ask-kb）；导入新论文（→ ingest-paper）；归档（→ archive）。
  写操作：向 workspaces/<kb_id>/papers/<paper_id>.json 追加 user_insights 字段（需确认）。
allowed-tools: Read, Bash(python *), WebSearch
---

# 学术论文多轮讨论

## 元数据

| 项目 | 内容 |
|------|------|
| 用途 | 加载已导入论文 → 多轮讨论 → 提炼用户理解 → 追加 user_insights |
| 输入 | 论文标题关键词 / paper_id；或列出所有论文供选择 |
| 输出 | 结构化讨论回答（基于论文内容）+ 可选的 insights 写入 |
| 副作用 | **追加写** `papers/<paper_id>.json` 的 `user_insights` 字段（需确认）|
| 需要确认 | 写入 user_insights 时需要确认 |

## 触发条件

**会触发：**
- "我想讨论一下 Flash Attention 2 论文"
- "列出我导入的所有论文"
- "跟我讲讲这篇 GRPO 论文的方法"
- "paper list"
- "把这篇论文的核心方法解释一遍"

**不触发：**
- "导入 Flash Attention 2" → ingest-paper
- "MoE 和 Dense 模型有什么区别" → ask-kb（不需要导入论文）
- "归档一下" → archive

## 执行流程

### 第一步：定位论文

**如果用户指定了论文名称/关键词：**

```bash
python ${CLAUDE_SKILL_DIR}/scripts/discuss_paper.py \
  --kb <kb_id> \
  --search "<关键词>"
```

**如果用户想列出所有论文：**

```bash
python ${CLAUDE_SKILL_DIR}/scripts/discuss_paper.py \
  --kb <kb_id> \
  --list [--status reading]
```

**如果用户指定了 paper_id：**

```bash
python ${CLAUDE_SKILL_DIR}/scripts/discuss_paper.py \
  --kb <kb_id> \
  --show <paper_id>
```

### 第二步：加载并展示论文概要

读取论文 JSON，向用户展示结构化摘要：

```
📄 Flash Attention 2: Faster Attention with Better Parallelism
   作者: Tri Dao (2023)  |  状态: reading  |  arXiv: 2307.08691

摘要总结:
  Flash Attention 2 改进了线程并行策略...

方法要点:
  - 重新设计了前向/反向 CUDA Kernel...
  - ...

核心主张:
  1. A100 上达到 72% FLOPs 利用率...

局限性:
  - ...

开放问题:
  - ...

关联 KB 节点: LLM Knowledge Base > Inference Optimization > Flash Attention

---
你想从哪个角度讨论这篇论文？（方法细节 / 与其他工作对比 / 实现细节 / 局限性）
```

### 第三步：多轮讨论

Claude 根据论文内容回答用户问题，使用论文的 method_summary / key_claims / 关联 KB 节点信息。
重要补充点及时提示用户可以追加到 user_insights。

### 第四步：追加 user_insights（按需）

讨论产生了新理解时，Claude 提示：

> "本次讨论产生了一些理解要点，要追加到论文记录吗？"

用户确认后：

```bash
python ${CLAUDE_SKILL_DIR}/scripts/discuss_paper.py \
  --kb <kb_id> \
  --paper-id <paper_id> \
  --add-insight "<洞察内容>"
```

### 第五步：推荐后续操作

讨论结束后提示：
- "如需将本次讨论的知识点归档到知识树，直接说'归档'。"
- "如需关联论文与知识树节点，说'关联 KB'。"

## 错误处理

| 错误 | 处理方式 |
|------|---------|
| 没有找到论文 | 提示用户先运行 ingest-paper 导入 |
| 知识库为空 | 直接基于论文内容讨论，提示建立知识树 |
| paper_id 不匹配 | 列出所有论文供用户选择 |
