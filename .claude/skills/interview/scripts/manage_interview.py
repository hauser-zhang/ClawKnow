"""Interview record management: save, list, sync to Feishu."""

import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(PROJECT_ROOT))

INTERVIEWS_DIR = PROJECT_ROOT / "data" / "interviews"


def cmd_save():
    """Read a JSON interview record from stdin and save to file."""
    INTERVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    data = json.load(sys.stdin)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    company = data.get("company", "unknown").replace(" ", "_")
    filename = f"{ts}_{company}.json"
    path = INTERVIEWS_DIR / filename

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {path.name}")
    print(f"Questions: {len(data.get('questions', []))}")


def cmd_list():
    """List all saved interview records."""
    if not INTERVIEWS_DIR.exists() or not list(INTERVIEWS_DIR.glob("*.json")):
        print("No interview records found.")
        return

    records = []
    for f in sorted(INTERVIEWS_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        records.append((f.name, data))

    print(f"Total: {len(records)} record(s)\n")
    for fname, r in records:
        q_count = len(r.get("questions", []))
        categories = {}
        for q in r.get("questions", []):
            cat = q.get("category", "other")
            categories[cat] = categories.get(cat, 0) + 1
        cat_str = ", ".join(f"{k}:{v}" for k, v in categories.items())
        print(f"  [{r.get('date', '?')}] {r.get('company', '?')} "
              f"({r.get('type', '?')}) - {q_count} Q ({cat_str})")


def cmd_sync():
    """Sync interview records to Feishu wiki."""
    from lib import config, feishu  # noqa: E402

    missing = config.check()
    if missing:
        print(f"ERROR: Missing env vars: {', '.join(missing)}")
        sys.exit(1)

    if not INTERVIEWS_DIR.exists() or not list(INTERVIEWS_DIR.glob("*.json")):
        print("No interview records to sync.")
        return

    # Create a parent node for interviews
    parent = feishu.create_node("面试记录")
    print(f"Created parent node: 面试记录 ({parent['node_token'][:8]}...)\n")

    for f in sorted(INTERVIEWS_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        title = f"{data.get('date', '?')} {data.get('company', '?')} {data.get('type', '面试')}"
        node = feishu.create_node(title, parent["node_token"])
        print(f"  + {title}")

    print("\nSync complete.")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("save", "list", "sync"):
        print("Usage: python manage_interview.py <save|list|sync>")
        print("  save  - read JSON from stdin, save to file")
        print("  list  - list all records")
        print("  sync  - sync records to Feishu wiki")
        sys.exit(1)

    {"save": cmd_save, "list": cmd_list, "sync": cmd_sync}[sys.argv[1]]()


if __name__ == "__main__":
    main()
