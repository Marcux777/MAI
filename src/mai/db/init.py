from __future__ import annotations

import argparse
from pathlib import Path

from mai.core.config import get_settings
from mai.core.logging import logger
from mai.db.session import get_engine


def apply_schema(schema_path: Path | None = None) -> None:
    settings = get_settings()
    path = schema_path or settings.schema_path
    sql = path.read_text(encoding="utf-8")
    engine = get_engine()
    raw = engine.raw_connection()
    try:
        raw.executescript(sql)
        raw.commit()
    finally:
        raw.close()
    logger.info("Schema aplicado a %s", settings.db_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inicializa o banco SQLite da MAI")
    parser.add_argument("--schema", type=Path, default=None, help="Caminho para o arquivo schema.sql")
    args = parser.parse_args()
    apply_schema(args.schema)


if __name__ == "__main__":
    main()
