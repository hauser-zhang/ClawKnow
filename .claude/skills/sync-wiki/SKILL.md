---
name: sync-wiki
description: >
  将本地 knowledge_tree.json 幂等同步到飞书 wiki 节点树。
  触发：用户明确说"同步到飞书"、"推送到知识库"、"上传到飞书"，或手动执行 /sync-wiki。
  不触发：仅问知识库内容；仅规划结构；自动触发（此技能仅限手动确认后执行）。
  写操作：在飞书创建/更新 wiki 节点，更新本地 feishu_map.json 和 knowledge_tree.json。
disable-model-invocation: true
allowed-tools: Read, Bash(python *)
---

# 同步知识库到飞书（幂等版）

## 元数据

| 项目 | 内容 |
|------|------|
| 用途 | 将本地知识树幂等同步为飞书 wiki 页面层级，支持正文内容渲染 |
| 输入 | `workspaces/<kb_id>/knowledge_tree.json`（由 plan-wiki 生成）|
| 输出 | 控制台打印 create/update/skip 差异报告 |
| 副作用 | **飞书写操作**：创建/更新 wiki 节点及文档内容；**本地写**：`feishu_map.json`、`knowledge_tree.json` 中的 token |
| 需要确认 | 是 — 先展示 dry-run 预览，用户确认后再执行 `--apply` |

## 触发条件

**会触发（须含明确同步意图）：**
- "同步到飞书"
- "把知识库推送上去"
- "上传到飞书知识库"
- `/sync-wiki`

**不触发：**
- 仅讨论知识库内容
- 仅查询节点结构
- 自动触发（该技能 `disable-model-invocation: true`，仅手动）

## 执行流程

### 第一步：前置检查

逐项确认：

1. `workspaces/<kb_id>/knowledge_tree.json` 存在（否则提示先运行 plan-wiki）
2. `.env` 中飞书凭证已配置，或 `kb.yaml` 中 `feishu_space_id` 已填写
3. 飞书 Bot 已被添加为知识库空间成员

> **重要**：仅有 API 权限不够，Bot 必须显式加为空间成员。
> 操作路径：飞书知识库设置 → 成员管理 → 添加应用。

### 第二步：Dry-run 预览（默认行为）

读取知识树，与 `feishu_map.json` 比对，展示差异后等待确认：

```bash
python ${CLAUDE_SKILL_DIR}/scripts/sync_to_feishu.py [--kb <kb_id>]
```

输出示例：
```
[DRY-RUN] kb=default  space=XXXX

  tree: 42 node(s) — 15 create, 3 update, 24 skip
  (pass --apply to execute)

  [+] create          LLM知识库 > MoE架构
  [~] update_content  LLM知识库 > Transformer > 注意力机制
  [·] skip            LLM知识库 > 预训练 > 数据处理
```

### 第三步：用户确认

展示预览后，向用户说明：
- `create` = 新节点将被创建（飞书会新增页面）
- `update_content` = 已有节点内容将被覆盖更新（仅文档正文，不改标题）
- `skip` = 内容未变，不做任何操作

**仅在用户输入"确认同步"或等效确认后才执行 `--apply`。**

### 第四步：执行同步

```bash
# 默认 workspace，应用同步
python ${CLAUDE_SKILL_DIR}/scripts/sync_to_feishu.py --apply

# 指定 workspace
python ${CLAUDE_SKILL_DIR}/scripts/sync_to_feishu.py --kb <kb_id> --apply

# 同时同步面试记录
python ${CLAUDE_SKILL_DIR}/scripts/sync_to_feishu.py --kb <kb_id> --apply --interviews
```

### 第五步：同步完成后

1. 展示同步报告（created / updated / skipped / failed 数量）
2. 告知 `feishu_map.json` 已更新（记录本次同步的映射）
3. 告知 `knowledge_tree.json` 已更新（node_token/obj_token 回填）
4. 如有 failed，展示错误列表，建议用户检查后重新运行（幂等，安全）

## 恢复模式（历史节点对接）

如果飞书上已有节点但本地 `feishu_map.json` 为空（例如首次使用幂等版），先运行恢复：

```bash
# 只扫描，不写文件
python ${CLAUDE_SKILL_DIR}/scripts/sync_to_feishu.py --recover

# 扫描并保存映射
python ${CLAUDE_SKILL_DIR}/scripts/sync_to_feishu.py --recover --apply
```

恢复逻辑：BFS 遍历远程飞书空间，将标题路径与本地树匹配，写入 `feishu_map.json`，
后续 sync 会跳过已有节点，不产生重复。

## 预览/确认协议

```
⚠️  同步操作将写入飞书，请确认以下信息：

  workspace  : <kb_id>
  space      : <FEISHU_WIKI_SPACE_ID>
  将创建节点 : N 个
  将更新内容 : M 个
  跳过不变   : K 个

  幂等性：feishu_map.json 跟踪已同步节点，重复运行不会创建重复节点。
  确认请输入"确认同步"，取消请输入"取消"。
```

## 错误处理

| 错误 | 处理方式 |
|------|---------|
| `knowledge_tree.json` 不存在 | 提示先运行 plan-wiki |
| `feishu_map.json` 损坏 | 自动忽略并从头开始（运行前建议先 `--recover`）|
| 错误码 99991672 | Bot 未加为空间成员 → 给出操作路径 |
| 错误码 99991663 | 凭证错误 → 检查 `.env` |
| API 限流 / 单节点失败 | 自动重试（最多 3 次，指数退避）；失败节点跳过后继续；报告末尾列出所有失败项 |
| 局部失败后重新运行 | 幂等，已成功节点会被 skip，只重试失败项 |

## 幂等性保证

- `feishu_map.json` 记录每个本地路径 → `(node_token, obj_token, content_hash)` 的映射
- 每次运行计算 diff：路径已在 map 且 `content_hash` 未变 → `skip`
- 路径在 map 但内容变了 → `update_content`（只更新文档正文，不重建节点）
- 路径不在 map → `create`
- 每次成功的 create/update 后立即保存 map，中途中断可安全重跑
