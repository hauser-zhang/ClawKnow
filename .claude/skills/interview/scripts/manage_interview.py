"""Interview record management: save, list, sync to Feishu."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

from lib import workspace  # noqa: E402


def cmd_save(interviews_dir: Path, kb_id: str) -> None:
    """Read a JSON interview record from stdin and save to file."""
    interviews_dir.mkdir(parents=True, exist_ok=True)
    data = json.load(sys.stdin)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    company = data.get("company", "unknown").replace(" ", "_")
    filename = f"{ts}_{company}.json"
    path = interviews_dir / filename

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[kb={kb_id}] Saved: {path.name}")
    print(f"Questions: {len(data.get('questions', []))}")


def cmd_list(interviews_dir: Path, kb_id: str) -> None:
    """List all saved interview records."""
    if not interviews_dir.exists() or not list(interviews_dir.glob("*.json")):
        print(f"[kb={kb_id}] No interview records found.")
        return

    records = []
    for f in sorted(interviews_dir.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        records.append((f.name, data))

    print(f"[kb={kb_id}] Total: {len(records)} record(s)\n")
    for fname, r in records:
        q_count = len(r.get("questions", []))
        categories: dict[str, int] = {}
        for q in r.get("questions", []):
            cat = q.get("category", "other")
            categories[cat] = categories.get(cat, 0) + 1
        cat_str = ", ".join(f"{k}:{v}" for k, v in categories.items())
        print(f"  [{r.get('date', '?')}] {r.get('company', '?')} "
              f"({r.get('type', '?')}) - {q_count} Q ({cat_str})")


def cmd_sync(interviews_dir: Path, kb_id: str) -> None:
    """Sync interview records to Feishu wiki."""
    from lib import config, feishu  # noqa: E402

    # Apply workspace feishu_space_id override if present
    try:
        kb_cfg = workspace.load_kb_config(PROJECT_ROOT, kb_id)
        space_id_override = kb_cfg.get("feishu_space_id", "").strip()
        if space_id_override:
            config.FEISHU_WIKI_SPACE_ID = space_id_override
    except FileNotFoundError:
        pass

    missing = config.check()
    if missing:
        print(f"ERROR: Missing env vars: {', '.join(missing)}")
        sys.exit(1)

    if not interviews_dir.exists() or not list(interviews_dir.glob("*.json")):
        print(f"[kb={kb_id}] No interview records to sync.")
        return

    parent = feishu.create_node("面试记录")
    print(f"[kb={kb_id}] Created parent node: 面试记录 ({parent['node_token'][:8]}...)\n")

    for f in sorted(interviews_dir.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        title = f"{data.get('date', '?')} {data.get('company', '?')} {data.get('type', '面试')}"
        feishu.create_node(title, parent["node_token"])
        print(f"  + {title}")

    print("\nSync complete.")


def main() -> None:
    """Dispatch save / list / sync subcommands for interview records."""
    parser = argparse.ArgumentParser(description="Interview record manager")
    parser.add_argument("command", choices=["save", "list", "sync"])
    parser.add_argument(
        "--kb",
        default=workspace.DEFAULT_KB_ID,
        metavar="KB_ID",
        help=f"Workspace ID (default: {workspace.DEFAULT_KB_ID})",
    )
    args = parser.parse_args()

    interviews_dir = workspace.get_interviews_dir(PROJECT_ROOT, args.kb)

    dispatch = {
        "save": cmd_save,
        "list": cmd_list,
        "sync": cmd_sync,
    }
    dispatch[args.command](interviews_dir, args.kb)


if __name__ == "__main__":
    main()
