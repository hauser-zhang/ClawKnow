"""Read docs/ and generate a knowledge tree structure using Claude API."""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import config, workspace  # noqa: E402

PLAN_PROMPT = """\
你是一个知识库架构师。请分析以下文档内容，生成一个结构化的知识库树。

要求：
1. 顶层是一个总览节点，包含所有大方向的知识分类
2. 每个大方向展开为子节点，子节点可以有多级层次（如：后训练 > RLHF > GRPO）
3. 每个叶子节点必须有 summary 字段（一两句话概括要点）
4. 层级以 2-3 级为主，最深不超过 4 级
5. 只输出 JSON，不要其他文字

输出格式：
{
  "title": "知识库名称",
  "children": [
    {
      "title": "分类名",
      "children": [
        {"title": "知识点", "summary": "简要描述"}
      ]
    }
  ]
}

文档内容：
"""


def load_docs(docs_dir: Path) -> str:
    """Read all doc files from docs_dir and concatenate."""
    if not docs_dir.exists():
        print(f"ERROR: docs directory not found: {docs_dir}")
        sys.exit(1)

    parts = []
    for f in sorted(docs_dir.iterdir()):
        if f.suffix in (".md", ".txt", ".rst"):
            parts.append(f"# {f.name}\n\n{f.read_text(encoding='utf-8')}")

    if not parts:
        print(f"ERROR: No .md/.txt/.rst files found in {docs_dir}.")
        sys.exit(1)

    return "\n\n---\n\n".join(parts)


def generate_tree(content: str) -> dict:
    """Call Claude API to generate a knowledge tree from content."""
    import anthropic

    if not config.ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set in .env")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": PLAN_PROMPT + content}],
    )
    text = resp.content[0].text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def tree_to_outline(node: dict, depth: int = 0) -> str:
    """Render tree as a readable markdown outline."""
    indent = "  " * depth
    line = f"{indent}- **{node['title']}**"
    if node.get("summary"):
        line += f": {node['summary']}"
    lines = [line]
    for child in node.get("children", []):
        lines.append(tree_to_outline(child, depth + 1))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan knowledge tree structure from docs")
    parser.add_argument(
        "--kb",
        default=workspace.DEFAULT_KB_ID,
        metavar="KB_ID",
        help=f"Workspace ID (default: {workspace.DEFAULT_KB_ID})",
    )
    args = parser.parse_args()

    tree_path = workspace.get_tree_path(PROJECT_ROOT, args.kb)
    docs_dir = workspace.get_docs_dir(PROJECT_ROOT, args.kb)

    content = load_docs(docs_dir)
    print(f"[kb={args.kb}] Read {content.count('# ')} document(s) from {docs_dir}. Analyzing...")

    tree = generate_tree(content)

    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nGenerated knowledge tree:\n")
    print(tree_to_outline(tree))
    print(f"\nSaved to {tree_path}")


if __name__ == "__main__":
    main()
