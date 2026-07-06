from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "MAI"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    debug: bool = False

    db_path: Path = Path("var/data/mai.db")
    schema_path: Path = Path("db/schema.sql")
    upload_dir: Path = Path("var/uploads")

    watch_paths: List[Path] = []
    google_books_key: str | None = None
    provider_timeout: float = 15.0
    organizer_template: str = "{author_last}/{title}.{ext}"
    admin_username: str = "mai"
    admin_password: str = "mai"
    task_workers: int = 1

    # OCR (PDF escaneado)
    pdf_ocr_enabled: bool = False
    pdf_ocr_lang: str = "eng"
    pdf_ocr_max_pages: int = 3
    pdf_ocr_dpi: int = 200
    pdf_ocr_timeout_seconds: float = 10.0
    pdf_ocr_trigger_text_chars: int = 40

    # Estimativas de leitura (ebooks)
    ebook_chars_per_page: int = 2400
    reading_pages_per_hour: float = 40.0

    # UI (Qt)
    qt_theme: str | None = "dark_teal.xml"

    class Config:
        env_prefix = "MAI_"
        env_file = ".env"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    return settings
