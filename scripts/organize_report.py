#!/usr/bin/env python
"""Cliente simples para listar manifestos via API local."""
from __future__ import annotations

import argparse
import sys

import httpx
from rich.console import Console
from rich.table import Table


def main() -> None:
    parser = argparse.ArgumentParser(description="Mostra detalhes de um manifesto via API MAI")
    parser.add_argument("manifest_id", type=int)
    parser.add_argument("--base-url", default="http://localhost:8000", help="URL base da API (default: http://localhost:8000)")
    parser.add_argument("--status", help="Filtra por status (planned,done,skipped,failed,reverted)")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()

    url = f"{args.base_url.rstrip('/')}/organize/{args.manifest_id}"
    params = {"limit": args.limit, "offset": args.offset}
    if args.status:
        params["status"] = args.status

    try:
        resp = httpx.get(url, params=params, timeout=10)
        resp.raise_for_status()
    except httpx.HTTPError as exc:  # pragma: no cover - CLI runtime
        console = Console()
        console.print(f"[red]Falha ao consultar {url}: {exc}")
        sys.exit(1)

    data = resp.json()
    console = Console()
    console.print(f"Manifesto #{data['manifest_id']} — status={data['status']} — template={data['template']}")
    console.print(f"Resumo: {data['summary']}")

    table = Table(title="Operações", show_lines=False)
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("Status")
    table.add_column("Origem", overflow="fold")
    table.add_column("Destino", overflow="fold")
    table.add_column("Motivo")

    for op in data.get("ops", []):
        table.add_row(
            str(op["id"]),
            op["status"],
            op["src_path"],
            op["dst_path"],
            op.get("reason") or "",
        )

    console.print(table)


if __name__ == "__main__":  # pragma: no cover
    main()
