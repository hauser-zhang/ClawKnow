"""Loads environment variables from .env at project root."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_WIKI_SPACE_ID = os.getenv("FEISHU_WIKI_SPACE_ID", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


def check() -> list[str]:
    """Return names of missing required env vars."""
    missing = []
    for key in ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_WIKI_SPACE_ID"):
        if not os.getenv(key):
            missing.append(key)
    return missing
