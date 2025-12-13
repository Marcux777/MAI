# Arquitetura

O MAI é um gerenciador **local-first**: o estado do produto vive em SQLite (com FTS5) e os componentes (API, UI e CLIs) operam sobre esse banco local.

## Visão geral (subsistemas)

- **Ingestão**: varre diretórios ou recebe upload via API; calcula `sha256`; extrai metadados do arquivo; busca candidatos em providers; reconcilia e persiste.
- **Watcher**: monitora diretórios (watchdog) e dispara ingestão em background.
- **Identificação + scoring**: normaliza título/autores, valida ISBN, pontua candidatos e decide auto-aceitar vs. revisão.
- **Providers**: Open Library / Google Books / BookBrainz (e extensões futuras) com chamadas time-bounded.
- **Persistência + busca**: SQLite + SQLAlchemy; indexação FTS5 para busca rápida.
- **Organizador**: gera manifesto (preview) com caminhos “canônicos”, aplica (move/rename) e permite rollback.
- **Review**: fila de revisão manual para casos não auto-aceitos.
- **API**: FastAPI expõe endpoints para catálogo, import, organização, revisão e OPDS.
- **UI (Qt)**: app desktop PySide6 consumindo serviços locais e/ou API.
- **OPDS (opcional)**: feed e download de arquivos para e-readers.

## Fluxo principal (end-to-end)

1. **Detecção**: `mai-import`/`/import/scan`/watcher detecta arquivos suportados.
2. **Fingerprint**: calcula `sha256` (dedup e rastreio).
3. **Extração**: lê metadados locais (EPUB/PDF/…).
4. **Normalização**: limpa/normaliza dados (título/autores/idioma/ISBN).
5. **Identificação**: consulta providers (por ISBN ou busca textual).
6. **Scoring**: ranqueia candidatos e decide auto-aceitar ou encaminhar para revisão.
7. **Persistência**: grava `work/edition/author/identifier/file/provider_hit/...`.
8. **Indexação**: atualiza FTS5 para busca (`search`).
9. **Organização**: (opcional) `preview/apply/rollback` para padronizar paths físicos.
10. **Revisão**: (opcional) resolve candidatos para completar metadados.

## Mapeamento do código (alto nível)

- `src/mai/ingest/*`: pipeline, providers e serviços de watcher.
- `src/mai/db/*`: sessão, models e indexação FTS.
- `src/mai/organizer/*`: manifesto e operações de filesystem.
- `src/mai/review/*`: fila/serviços de revisão.
- `src/mai/api/*`: rotas FastAPI.
- `src/mai_qt/*`: UI desktop PySide6.

Entrypoints:

- `mai-api`, `mai-init-db`, `mai-import`, `mai-organize`, `mai-qt` (definidos em `pyproject.toml`).

## Banco de dados e FTS5

- Schema: `db/schema.sql` (inclui tabela virtual `search` com FTS5 e triggers).
- Localização padrão: `var/data/mai.db` (configurável via `MAI_DB_PATH`).

## Configuração e runtime

- Config: variáveis `MAI_*` via `.env` (ver `.env.example`).
- Diretórios de runtime: `var/`, `tmp/`, `tmpdb/` (não commit).

