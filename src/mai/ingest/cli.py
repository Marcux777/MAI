from __future__ import annotations

import argparse
from pathlib import Path

from mai.core.config import get_settings
from mai.core.logging import configure_logging, logger
from mai.ingest.pipeline import build_providers, ingest_paths, watch_directories


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingestão de arquivos MAI")
    parser.add_argument("paths", nargs="*", type=Path, help="Pastas ou arquivos para processar")
    parser.add_argument("--watch", action="store_true", help="Ativa modo watcher usando watchdog")
    parser.add_argument("--google-key", dest="google_key", default=None, help="Chave API do Google Books")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.debug)

    paths = args.paths or settings.watch_paths
    if not paths:
        raise SystemExit("Nenhum caminho informado. Passe paths ou configure MAI_WATCH_PATHS.")

    resolved = [path if path.is_absolute() else path.resolve() for path in paths]
    providers = build_providers(args.google_key or settings.google_books_key)

    if args.watch:
        watch_directories(resolved, providers)
    else:
        ingest_paths(resolved, providers)
    logger.info("Ingestão finalizada")


if __name__ == "__main__":  # pragma: no cover
    main()
