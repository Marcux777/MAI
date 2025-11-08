from __future__ import annotations

import argparse
from pathlib import Path

from mai.core.config import get_settings
from mai.core.logging import configure_logging
from mai.db.session import session_scope
from mai.organizer.service import (
    preview_manifest,
    apply_manifest,
    rollback_manifest,
    load_manifest_details,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ferramentas do organizador MAI")
    sub = parser.add_subparsers(dest="command", required=True)

    preview_cmd = sub.add_parser("preview", help="Gera manifest de organização")
    preview_cmd.add_argument("--root", type=Path, required=False, help="Diretório destino")
    preview_cmd.add_argument("--template", type=str, help="Template opcional")
    preview_cmd.add_argument("--editions", nargs="*", type=int, help="IDs específicos de edição")
    preview_cmd.add_argument("--sample", type=int, default=20, help="Qtde de operações para listar")

    apply_cmd = sub.add_parser("apply", help="Aplica um manifesto existente")
    apply_cmd.add_argument("manifest_id", type=int)
    apply_cmd.add_argument("--status", nargs="*", help="Filtra status a aplicar (planned,failed)")

    rollback_cmd = sub.add_parser("rollback", help="Reverte um manifesto aplicado")
    rollback_cmd.add_argument("manifest_id", type=int)

    inspect_cmd = sub.add_parser("inspect", help="Lista operações de um manifesto")
    inspect_cmd.add_argument("manifest_id", type=int)
    inspect_cmd.add_argument("--status", help="Filtra por status")
    inspect_cmd.add_argument("--limit", type=int, default=20)
    inspect_cmd.add_argument("--offset", type=int, default=0)

    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.debug)

    if args.command == "preview":
        if args.root:
            root = args.root
        elif settings.watch_paths:
            root = Path(settings.watch_paths[0])
        else:
            root = Path.cwd()
        template = args.template or settings.organizer_template
        edition_ids = args.editions if args.editions else None

        with session_scope() as session:
            result = preview_manifest(
                session,
                root=root,
                template=template,
                edition_ids=edition_ids,
                sample_limit=args.sample,
            )
            session.commit()
            manifest_id = result.manifest.id
            summary = dict(result.summary)
            ops = [
                {
                    "status": op.status,
                    "src_path": op.src_path,
                    "dst_path": op.dst_path,
                    "reason": op.reason or "",
                }
                for op in result.sample_ops
            ]
        print(f"Manifesto #{manifest_id} salvo")
        print(f"Resumo: {summary}")
        for op in ops:
            print(f"[{op['status']}] {op['src_path']} -> {op['dst_path']} ({op['reason']})")
    elif args.command == "apply":
        with session_scope() as session:
            summary = apply_manifest(session, args.manifest_id, settings, statuses=args.status)
            session.commit()
        print(f"Manifesto #{args.manifest_id} aplicado: {summary}")
    elif args.command == "rollback":
        with session_scope() as session:
            summary = rollback_manifest(session, args.manifest_id, settings)
            session.commit()
        print(f"Manifesto #{args.manifest_id} revertido: {summary}")
    elif args.command == "inspect":
        with session_scope() as session:
            manifest, summary, ops = load_manifest_details(
                session,
                args.manifest_id,
                statuses=[args.status] if args.status else None,
                limit=args.limit,
                offset=args.offset,
            )
            manifest_data = {
                "id": manifest.id,
                "status": manifest.status,
                "template": manifest.template,
            }
            ops_data = [
                {
                    "id": op.id,
                    "status": op.status,
                    "src_path": op.src_path,
                    "dst_path": op.dst_path,
                    "reason": op.reason or "",
                }
                for op in ops
            ]
        print(
            f"Manifesto #{manifest_data['id']} status={manifest_data['status']} template={manifest_data['template']}"
        )
        print(f"Resumo: {summary}")
        for op in ops_data:
            print(f"#{op['id']} [{op['status']}] {op['src_path']} -> {op['dst_path']} ({op['reason']})")


if __name__ == "__main__":  # pragma: no cover
    main()
