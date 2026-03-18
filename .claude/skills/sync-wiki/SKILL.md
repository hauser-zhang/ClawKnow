---
name: sync-wiki
description: >
  将本地 knowledge_tree.json 同步创建为飞书 wiki 节点树。
  触发：用户明确说"同步到飞书"、"推送到知识库"、"上传到飞书"，或手动执行 /sync-wiki。
  不触发：仅问知识库内容；仅规划结构；自动触发（此技能仅限手动确认后执行）。
  写操作：在飞书创建 wiki 节点（不可轻易撤销），并更新本地 JSON 的 node_token/obj_token。
disable-model-invocation: true
allowed-tools: Read, Bash(python *)
---

# 同步知识库到飞书

## 元数据

| 项目 | 内容 |
|------|------|
| 用途 | 将本地知识树一次性同步创建为飞书 wiki 页面层级 |
| 输入 | `workspaces/<kb_id>/knowledge_tree.json`（由 plan-wiki 生成）|
| 输出 | 控制台打印已创建节点列表 |
| 副作用 | **飞书写操作**：创建 wiki 节点；**本地写**：更新 JSON 中的 node_token / obj_token |
| 需要确认 | 是 — 必须用户明确确认后才执行 |

## 触发条件

**会触发（须含明确同步意图）：**
- "同步到飞书"
- "把知识库推送上去"
- "上传到飞书知识库"
- `/sync-wiki`

**不触发：**
- 仅讨论知识库内容
- 仅查询节点结构
- 自动触发（该技能无自动触发，`disable-model-invocation: true`）

## 执行流程

### 第一步：前置检查

执行前逐项确认：

1. `workspaces/<kb_id>/knowledge_tree.json` 存在（否则提示先运行 plan-wiki）
2. `.env` 中飞书凭证已配置，或 `kb.yaml` 中 `feishu_space_id` 已填写
3. 飞书 Bot 已被添加为知识库空间成员

> **重要**：仅有 API 权限不够，Bot 必须显式加为空间成员。
> 操作路径：飞书知识库设置 → 成员管理 → 添加应用。

### 第二步：预览并确认

读取知识树，统计节点数，展示预览后等待确认：

```
⚠️  同步操作不可逆，请确认以下信息：

  workspace : default
  节点总数  : N 个
  目标空间  : <FEISHU_WIKI_SPACE_ID>

  注意：当前实现不是幂等的，重复运行会创建重复节点。
  确认已了解风险，输入"确认同步"继续，或输入"取消"退出。
```

**仅在用户输入"确认同步"或等效确认后才执行脚本。**

### 第三步：执行同步

```bash
# 默认 workspace
python ${CLAUDE_SKILL_DIR}/scripts/sync_to_feishu.py

# 指定 workspace
python ${CLAUDE_SKILL_DIR}/scripts/sync_to_feishu.py --kb <kb_id>
```

### 第四步：同步完成后

1. 展示已创建节点数量
2. 提醒用户 `knowledge_tree.json` 已更新（每个节点新增了 `node_token` 和 `obj_token`）
3. 提醒可以在飞书中查看刚创建的知识库结构

## 错误处理

| 错误 | 处理方式 |
|------|---------|
| `knowledge_tree.json` 不存在 | 提示先运行 plan-wiki |
| 错误码 99991672 | Bot 未加为空间成员 → 给出操作路径 |
| 错误码 99991663 | 凭证错误 → 检查 `.env` |
| API 限流 | 脚本已内置 0.3 s 间隔；若仍限流，等待后重试 |

## 注意事项

- **幂等性**：重复运行会在飞书创建重复节点，无法自动去重
- **局部失败**：节点创建失败不会回滚已创建的节点；可手动删除后重新同步
- **无法删除**：脚本不支持删除飞书节点；如需删除请在飞书界面手动操作
