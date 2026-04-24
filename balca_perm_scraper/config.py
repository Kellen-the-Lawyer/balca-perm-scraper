from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    base_dir: Path = Path(__file__).resolve().parents[1]
    raw_dir: Path = base_dir / "data" / "raw"
    processed_dir: Path = base_dir / "data" / "processed"
    database_path: Path = processed_dir / "balca_perm.sqlite"
    user_agent: str = (
        "balca-perm-scraper/0.1 (+https://github.com/your-org/balca-perm-scraper)"
    )
    # Read-only query key extracted from the public DOL OALJ search page JS.
    # Set via environment variable; never commit the value directly.
    azure_query_key: str = field(
        default_factory=lambda: os.environ.get("DOL_AZURE_QUERY_KEY", "")
    )
    timeout_seconds: float = 30.0
    max_connections: int = 5
    sleep_seconds: float = 1.0
    pdf_sleep_seconds: float = 2.0
    pdf_sleep_jitter: float = 2.0
    page_size: int = 50

    def require_azure_query_key(self) -> str:
        if not self.azure_query_key:
            raise RuntimeError(
                "DOL_AZURE_QUERY_KEY is required for live OALJ Azure Search requests."
            )
        return self.azure_query_key


SETTINGS = Settings()
