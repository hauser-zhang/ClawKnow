"""Migrate legacy single-KB layout (v0) to workspace layout (v1).

Before (v0):
    data/knowledge_tree.json
    data/interviews/*.json

After (v1):
    workspaces/default/kb.yaml
    workspaces/default/knowledge_tree.json
    workspaces/default/interviews/*.json

Safe to run multiple times — existing files are never overwritten.
"""

import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import workspace  # noqa: E402


def main() -> None:
    old_tree = PROJECT_ROOT / "data" / "knowledge_tree.json"
    old_interviews = PROJECT_ROOT / "data" / "interviews"

    print("Migrating legacy layout to workspaces/default/ ...")

    # Ensure default workspace exists
    ws_dir = workspace.init_workspace(
        PROJECT_ROOT,
        workspace.DEFAULT_KB_ID,
        name="LLM 知识库",
        description="Migrated from legacy single-KB layout",
    )
    print(f"  Workspace: {ws_dir.relative_to(PROJECT_ROOT)}")

    # --- knowledge_tree.json ---
    new_tree = workspace.get_tree_path(PROJECT_ROOT, workspace.DEFAULT_KB_ID)
    if old_tree.exists():
        if new_tree.exists():
            print(f"  SKIP  knowledge_tree.json (already exists in workspace)")
        else:
            shutil.copy2(old_tree, new_tree)
            print(f"  COPY  {old_tree.relative_to(PROJECT_ROOT)}"
                  f" -> {new_tree.relative_to(PROJECT_ROOT)}")
    else:
        print(f"  SKIP  data/knowledge_tree.json not found (nothing to migrate)")

    # --- interviews ---
    new_interviews = workspace.get_interviews_dir(PROJECT_ROOT, workspace.DEFAULT_KB_ID)
    if old_interviews.exists():
        copied = 0
        for f in sorted(old_interviews.glob("*.json")):
            dest = new_interviews / f.name
            if dest.exists():
                print(f"  SKIP  interviews/{f.name} (already exists)")
            else:
                shutil.copy2(f, dest)
                print(f"  COPY  interviews/{f.name}")
                copied += 1
        if copied == 0 and not list(old_interviews.glob("*.json")):
            print(f"  SKIP  data/interviews/ is empty")
    else:
        print(f"  SKIP  data/interviews/ not found (nothing to migrate)")

    print("\nMigration complete.")
    print("Tip: you can delete data/ once you have verified workspaces/default/ looks correct.")
    print("     Update .gitignore if you have not already.")


if __name__ == "__main__":
    main()
