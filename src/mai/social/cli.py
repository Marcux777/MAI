from __future__ import annotations

import argparse
from pathlib import Path

from mai.core.config import get_settings
from mai.core.logging import configure_logging
from mai.db.session import session_scope
from mai.social.goodreads import GoodreadsSyncOptions, sync_goodreads_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Integracoes sociais (Goodreads, etc.)")
    sub = parser.add_subparsers(dest="provider", required=True)

    goodreads = sub.add_parser("goodreads", help="Sincroniza CSV exportado do Goodreads")
    goodreads_sub = goodreads.add_subparsers(dest="command", required=True)

    gr_import = goodreads_sub.add_parser("import", help="Importa CSV do Goodreads")
    gr_import.add_argument("csv", type=Path, help="Arquivo CSV exportado do Goodreads")
    gr_import.add_argument("--dry-run", action="store_true", help="Simula a importacao sem gravar no banco")
    gr_import.add_argument("--skip-missing", action="store_true", help="Nao cria edicoes faltantes")
    gr_import.add_argument("--no-read-status", dest="apply_read_status", action="store_false")
    gr_import.add_argument("--force-read-status", action="store_true")
    gr_import.add_argument("--no-rating", dest="apply_rating", action="store_false")
    gr_import.add_argument("--overwrite-rating", action="store_true")
    gr_import.add_argument("--no-tags", dest="apply_tags", action="store_false")
    gr_import.add_argument("--include-bookshelves", action="store_true")
    gr_import.add_argument("--tag-prefix", type=str, default=None)
    gr_import.add_argument("--no-identifiers", dest="apply_identifiers", action="store_false")

    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.debug)

    if args.provider == "goodreads" and args.command == "import":
        if not args.csv.exists():
            raise SystemExit(f"Arquivo nao encontrado: {args.csv}")

        options = GoodreadsSyncOptions(
            create_missing=not args.skip_missing,
            apply_read_status=bool(args.apply_read_status),
            force_read_status=bool(args.force_read_status),
            apply_rating=bool(args.apply_rating),
            overwrite_rating=bool(args.overwrite_rating),
            apply_tags=bool(args.apply_tags),
            include_bookshelves=bool(args.include_bookshelves),
            tag_prefix=args.tag_prefix,
            apply_identifiers=bool(args.apply_identifiers),
            dry_run=bool(args.dry_run),
        )

        with session_scope() as session:
            result = sync_goodreads_csv(session, args.csv, options)
            if options.dry_run:
                session.rollback()

        summary = result.as_dict()
        status = "dry-run" if options.dry_run else "importado"
        print(f"Goodreads {status}: {summary}")
        if result.warnings:
            print("Avisos:")
            for warning in result.warnings:
                print(f"- {warning}")
        if result.errors:
            print("Erros:")
            for error in result.errors:
                print(f"- {error}")


if __name__ == "__main__":  # pragma: no cover
    main()
