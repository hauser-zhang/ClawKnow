---
name: sync-wiki
description: >
  将本地知识树结构同步创建到飞书知识库中。
  当用户明确要求"同步到飞书"、"推送到知识库"、"上传到飞书"时触发。
  因为此操作会在飞书中创建页面，属于不可轻易撤销的写操作，需要用户手动确认触发。
disable-model-invocation: true
allowed-tools: Read, Bash(python *)
---

# 同步知识库到飞书

将 `data/knowledge_tree.json` 中的知识树递归创建为飞书 wiki 节点。

## 前置检查

执行前务必确认：

1. `data/knowledge_tree.json` 存在（通过 plan-wiki 生成）
2. `.env` 中飞书凭证已正确配置
3. 飞书 Bot 已被添加为知识库空间成员（仅有 API 权限不够！）

如果任一条件不满足，给出明确的修复指引。

## 执行同步

```bash
python ${CLAUDE_SKILL_DIR}/scripts/sync_to_feishu.py
```

## 同步完成后

1. 展示同步结果：共创建了多少个节点
2. 提醒用户 `knowledge_tree.json` 已更新（每个节点新增了 `node_token` 和 `obj_token`）
3. 提醒用户可以在飞书中查看刚创建的知识库

## 注意事项

- **幂等性**：当前实现不是幂等的，重复运行会创建重复节点。
  同步前需确认用户确实想要创建新节点。
- **权限错误**：如果遇到 99991672 错误码，说明 Bot 未被添加为空间成员。
  指引用户：知识库设置 → 成员管理 → 添加应用。
- **速率限制**：大量节点时可能触发飞书 API 限流，脚本已内置基本重试。
