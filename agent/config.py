"""Central configuration – everything comes from environment variables / GitHub Secrets."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRAND_FILE = ROOT / "brand" / "brand.md"
QUEUE_FILE = ROOT / "content" / "queue.yaml"
MEDIA_DIR = ROOT / "media"
STATE_DIR = ROOT / "state"


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    ig_user_id: str
    ig_access_token: str
    anthropic_api_key: str
    model: str
    graph_version: str
    dry_run: bool
    enable_dms: bool
    media_base_url: str
    github_repo: str
    github_token: str
    timezone: str

    @classmethod
    def load(cls) -> "Config":
        repo = os.getenv("GITHUB_REPOSITORY", "oradam92-debug/bravo-circus-instagra")
        branch = os.getenv("MEDIA_BRANCH", "main")
        return cls(
            ig_user_id=os.getenv("IG_USER_ID", ""),
            ig_access_token=os.getenv("IG_ACCESS_TOKEN", ""),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
            graph_version=os.getenv("GRAPH_API_VERSION", "v25.0"),
            # Safe default: nothing is published until DRY_RUN is explicitly set to false.
            dry_run=_bool("DRY_RUN", True),
            enable_dms=_bool("ENABLE_DMS", False),
            media_base_url=os.getenv(
                "MEDIA_BASE_URL",
                f"https://raw.githubusercontent.com/{repo}/{branch}/media",
            ).rstrip("/"),
            github_repo=repo,
            github_token=os.getenv("GITHUB_TOKEN", ""),
            timezone=os.getenv("TIMEZONE", "Asia/Jerusalem"),
        )

    def require(self, *names: str) -> None:
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            raise SystemExit(f"Missing required settings: {', '.join(m.upper() for m in missing)}")
