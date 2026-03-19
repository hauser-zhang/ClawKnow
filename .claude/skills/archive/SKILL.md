---
name: archive
description: >
  将当前对话中产生的新知识要点归档到本地知识树的指定节点。
  触发：用户明确说"归档"、"保存到知识库"、"存一下"、"记录下来"、"加到知识库里"。
  不触发：仅讨论内容（无归档意图）；提问技术问题（→ ask-kb）；同步飞书（→ sync-wiki）。
  写操作：向 workspaces/<kb_id>/kb_index.db 写入类型化记忆记录，并用记忆内容重新生成 knowledge_tree.json 中该节点的 summary。
allowed-tools: Read, Bash(python *)
---

# 归档讨论到知识库

## 元数据

| 项目 | 内容 |
|------|------|
| 用途 | 提炼对话要点 → 分类为记忆记录 → 用户确认 → 写入并重新生成节点摘要 |
| 输入 | 当前对话内容；`workspaces/<kb_id>/knowledge_tree.json` |
| 输出 | 确认消息（归档路径 + 写入的记忆条目数 + 新摘要行数）|
| 副作用 | **写** `kb_index.db` 的 `memories` 表；**重新生成**（非追加）`knowledge_tree.json` 中节点的 `summary` |
| 需要确认 | 是 — 展示类型化预览后等用户确认 |

## 触发条件

**会触发：**
- "归档一下"
- "保存到知识库"
- "把这些存进去"
- "记录下来"
- "加到知识库里"

**不触发：**
- "帮我解释一下 GRPO" → ask-kb
- "同步到飞书" → sync-wiki
- "规划知识库" → plan-wiki
- "记录面试题" → interview

## 记忆类型参考

| 类型 | 英文标识 | 含义 | 示例 |
|------|---------|------|------|
| 概念 | `concept` | 核心定义或原理 | "MoE 通过 Gate 网络将 FFN 替换为稀疏激活的多个专家子网络" |
| 事实 | `fact` | 可验证的具体数据/行为 | "Mixtral 8×7B 每次激活 2/8 个专家，推理 FLOPs 与 13B Dense 相当" |
| 洞察 | `insight` | 对比、权衡或经验结论 | "Expert Capacity 设置过小会导致 token dropping，需要实验调整" |
| 来源 | `source_note` | 论文/文章/项目引用 | "Paper: Switch Transformers (Fedus et al., 2021)" |
| 待解答 | `question` | 尚未验证的问题 | "Load Balancing Loss 系数 α 过大对训练稳定性的具体影响？" |
| 决策 | `decision` | 项目/实践决定 | "本项目 MoE 暂不使用 Expert Capacity，先跑全量验证" |

**置信度**：`high`（已验证）/ `medium`（有依据）/ `low`（猜测/待验证）

## 执行流程

### 第一步：提炼知识要点并分类

回顾当前对话，识别值得长期存储的内容，为每条要点指定：
- **类型**（从上表六种类型中选择）
- **置信度**（high / medium / low）
- **来源引用**（如有具体论文/链接，记入 source_note 或放 --source 参数）

提炼 3–8 条要点，每条不超过两句话。去掉闲聊、提问过程和重复描述。

### 第二步：定位目标节点

读取 `workspaces/<kb_id>/knowledge_tree.json`，判断内容应归入哪个节点：

| 情况 | 处理方式 |
|------|---------|
| 匹配现有节点 | 将记忆写入该节点 |
| 需要新的子节点 | 直接编辑 JSON 新增节点后再归档 |
| 需要顶层新分类 | 建议用户确认后添加到根节点 |

### 第三步：预览并确认

向用户展示类型化归档预览，**等待确认后才写入**：

```
📥 归档预览 — 模型架构 > MoE 混合专家

记忆条目 (3):
  #1 [concept] MoE 通过 Gate 网络将 FFN 替换为稀疏激活的多个专家子网络 (置信度: high)
  #2 [fact]    Mixtral 8×7B 每次激活 2/8 专家，推理 FLOPs 与 13B Dense 模型相当 (置信度: high, 来源: Mixtral论文)
  #3 [question] Load Balancing Loss 系数 α 过大对训练稳定性的具体影响？(置信度: low)

归档后节点摘要将重新生成（非追加）。
---
确认归档？（输入"确认"继续，或说明需要修改的内容）
```

### 第四步：执行归档

用户确认后，将所有记忆条目打包为 JSON 数组，调用脚本**一次**：

```bash
# 批量归档（推荐，一次调用写入所有条目）
python ${CLAUDE_SKILL_DIR}/scripts/archive_to_kb.py \
  --kb <kb_id> \
  "<节点路径>" \
  --batch '<json_array>'

# 单条归档（简单场景）
python ${CLAUDE_SKILL_DIR}/scripts/archive_to_kb.py \
  --kb <kb_id> \
  "<节点路径>" \
  --type <type> \
  --content "<内容>" \
  --confidence <level> \
  [--source "<引用>"]

# 仅重新生成摘要（不新增记忆）
python ${CLAUDE_SKILL_DIR}/scripts/archive_to_kb.py \
  --kb <kb_id> \
  "<节点路径>" \
  --regen-only
```

`--batch` 参数接受 JSON 数组，每个对象支持字段：
```json
[
  {"type": "concept", "content": "...", "confidence": "high", "source_refs": ["论文名"]},
  {"type": "fact",    "content": "...", "confidence": "medium"}
]
```

路径用 `>` 分隔，如 `"模型架构>MoE"`。

### 第五步：归档后提示

- 确认写入的记忆条数和节点路径
- 如节点已有 `obj_token`（已同步到飞书），提醒：
  > "该节点已同步到飞书，本次修改仅在本地生效。如需同步，运行 /sync-wiki。"
- 如需要新建节点，提醒先编辑 `knowledge_tree.json`，再归档

## 摘要重新生成规则

归档后脚本自动调用 `retrieval.regen_node_summary()`，按类型顺序重建 `summary`：

```
[概念] ...
[事实] ...
[洞察] ...
[来源] ...
[待解答] ...
[决策] ...
```

**不再使用 `---` 追加格式**。新摘要完全由所有记忆记录驱动，可重复再生。

## 错误处理

| 错误 | 处理方式 |
|------|---------|
| `knowledge_tree.json` 不存在 | 提示先运行 plan-wiki 建立知识树 |
| 节点路径不存在 | 显示可用顶层节点列表；建议确认路径或新建节点 |
| `--batch` JSON 格式错误 | 脚本打印具体 JSON 解析错误，重新组织内容后重试 |
| 内容为空 | 要求用户指定要归档的内容 |
