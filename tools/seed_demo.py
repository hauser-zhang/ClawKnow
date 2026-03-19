"""Seed a demo workspace with sample data for retrieval testing.

Creates:
  workspaces/demo/kb.yaml               (workspace config)
  workspaces/demo/knowledge_tree.json   (sample KB tree)
  workspaces/demo/kb_index.db           (FTS5 index, built from the above)

Also indexes docs/demo_llm_notes.md if it exists.

Usage:
  python tools/seed_demo.py

Then test retrieval:
  python .claude/skills/ask-kb/scripts/search_kb.py --kb demo "注意力机制"
  python .claude/skills/ask-kb/scripts/search_kb.py --kb demo "MoE 路由"
  python .claude/skills/ask-kb/scripts/search_kb.py --kb demo "Flash Attention"
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import retrieval, workspace  # noqa: E402

# ---------------------------------------------------------------------------
# Demo knowledge tree (mirrors docs/demo_llm_notes.md structure)
# ---------------------------------------------------------------------------
DEMO_TREE: dict = {
    "title": "LLM 演示知识库",
    "summary": "用于演示 ClawKnow FTS5 检索功能的示例知识库",
    "children": [
        {
            "title": "模型架构",
            "summary": "大语言模型的核心架构设计",
            "children": [
                {
                    "title": "Transformer",
                    "summary": (
                        "Transformer 由 Vaswani 等人 2017 年提出，完全依赖注意力机制，"
                        "摒弃 RNN/CNN。核心组件：多头自注意力、FFN、残差连接、层归一化。"
                    ),
                    "children": [],
                },
                {
                    "title": "注意力机制",
                    "summary": (
                        "Scaled Dot-Product Attention: softmax(QK^T/√d_k)V。"
                        "多头注意力将 Q/K/V 投影到 h 个子空间后拼接。"
                        "KV Cache 缓存推理时的 Key/Value 避免重复计算，"
                        "内存占用 = 2 × L × d_model × seq_len × precision。"
                    ),
                    "children": [],
                },
                {
                    "title": "MoE 混合专家",
                    "summary": (
                        "将 FFN 层替换为多个专家子网络，每个 token 只激活 Top-K 专家（稀疏激活）。"
                        "路由：Gate 网络输出 softmax logit，取 TopK 加权求和。"
                        "训练需要 Load Balancing Loss 防止专家崩溃。"
                        "代表：Mixtral 8×7B（2/8 激活）、DeepSeek-MoE。"
                    ),
                    "children": [],
                },
                {
                    "title": "Flash Attention",
                    "summary": (
                        "分块计算注意力，不显式写入 N×N 注意力矩阵到 HBM。"
                        "显存复杂度从 O(N²) 降至 O(N)，速度提升 2-4x。"
                        "Flash Attention 2 优化线程块并行，是推理框架标配。"
                    ),
                    "children": [],
                },
            ],
        },
        {
            "title": "后训练对齐",
            "summary": "Pre-training 之后的对齐训练方法",
            "children": [
                {
                    "title": "SFT 监督微调",
                    "summary": (
                        "在指令-回复对上进行标准监督训练。"
                        "数据质量远比数量重要：数千条高质量数据优于大量低质量数据。"
                    ),
                    "children": [],
                },
                {
                    "title": "RLHF",
                    "summary": (
                        "基于人类反馈的强化学习。三阶段：SFT → 奖励模型训练（chosen/rejected 对）→ "
                        "PPO 强化学习（KL 惩罚防止偏离参考策略）。"
                        "目标：J(θ) = E[r_φ(x,y) - β·KL(π_θ‖π_ref)]。"
                    ),
                    "children": [],
                },
                {
                    "title": "GRPO",
                    "summary": (
                        "Group Relative Policy Optimization，DeepSeek-R1 使用的轻量化 RLHF 变体。"
                        "无需独立奖励模型，对同问题采样 G 个回复，以组内相对奖励归一化替代绝对奖励。"
                        "优势：消除奖励模型偏差，适合数学/代码等有明确答案的任务。"
                    ),
                    "children": [],
                },
            ],
        },
    ],
}

# ---------------------------------------------------------------------------
# Demo memories (simulating content archived via the archive skill)
# ---------------------------------------------------------------------------
DEMO_MEMORIES = [
    {
        "kb_path": "LLM 演示知识库 > 模型架构 > MoE 混合专家",
        "content": (
            "[2026-03-18] 补充：\n"
            "- MoE 路由中 Expert Capacity 是防止某个专家过载的上限，超出则丢弃（token dropping）\n"
            "- DeepSeekMoE 引入 Fine-grained expert segmentation，将专家拆得更细，提升利用率"
        ),
        "archived_at": "2026-03-18T10:00:00+00:00",
    },
    {
        "kb_path": "LLM 演示知识库 > 后训练对齐 > GRPO",
        "content": (
            "[2026-03-18] 补充：\n"
            "- GRPO 训练时不需要 Critic 网络，相比 PPO 显著降低显存和计算开销\n"
            "- 组内奖励标准化公式：A_i = (r_i - mean) / std，使得不同难度题目的梯度量级一致"
        ),
        "archived_at": "2026-03-18T11:00:00+00:00",
    },
]


def main() -> None:
    """Create the demo workspace and build its FTS5 index."""
    kb_id = "demo"

    # 1. Create workspace directory + kb.yaml
    ws_dir = workspace.init_workspace(
        PROJECT_ROOT,
        kb_id,
        name="LLM 演示知识库",
        description="Demo workspace for ClawKnow FTS5 retrieval testing",
    )
    print(f"[OK] Workspace created: {ws_dir}")

    # 2. Write knowledge_tree.json
    tree_path = workspace.get_tree_path(PROJECT_ROOT, kb_id)
    tree_path.write_text(
        json.dumps(DEMO_TREE, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[OK] Knowledge tree written: {tree_path}")

    # 3. Build FTS5 index
    db_path = workspace.get_index_path(PROJECT_ROOT, kb_id)
    conn = retrieval.open_db(db_path)

    raw = tree_path.read_text(encoding="utf-8")
    n_nodes = retrieval.index_tree(conn, DEMO_TREE, retrieval.compute_hash(raw))
    print(f"[OK] Indexed {n_nodes} KB nodes into fts_nodes")

    # 4. Index demo doc (if present)
    demo_doc = PROJECT_ROOT / "docs" / "demo_llm_notes.md"
    if demo_doc.exists():
        content = demo_doc.read_text(encoding="utf-8")
        n_chunks = retrieval.index_source(conn, str(demo_doc), "LLM 学习笔记示例", content)
        print(f"[OK] Indexed {n_chunks} chunks from {demo_doc.name}")
    else:
        print("  (docs/demo_llm_notes.md not found — skipping chunk indexing)")

    # 5. Index demo memories
    for mem in DEMO_MEMORIES:
        retrieval.index_memory(
            conn,
            mem["kb_path"],
            mem["content"],
            mem["archived_at"],
        )
    print(f"[OK] Indexed {len(DEMO_MEMORIES)} demo memories into fts_memories")

    conn.close()
    print(f"\nIndex location: {db_path}")
    print("\nTry these queries:")
    print(f"  python .claude/skills/ask-kb/scripts/search_kb.py --kb {kb_id} 注意力机制")
    print(f"  python .claude/skills/ask-kb/scripts/search_kb.py --kb {kb_id} MoE 路由")
    print(f"  python .claude/skills/ask-kb/scripts/search_kb.py --kb {kb_id} GRPO 奖励")


if __name__ == "__main__":
    main()
