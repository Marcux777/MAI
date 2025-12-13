# Roadmap

Este roadmap transforma as fases A/B/C do MAI em marcos rastreáveis (Milestones) e trilhas de trabalho (Epics + Issues).

## Milestones sugeridos

### Milestone A — MVP (fluxo ponta a ponta)

Objetivo: ingestão → identificação → persistência → busca → organização funcionando end-to-end.

Critérios de aceite (mínimo):

- Importar (scan/upload) pelo menos EPUB e PDF
- `sha256` e deduplicação básica por hash
- Persistência em SQLite + indexação FTS5
- Busca por texto (FTS) e listagem/detalhe via API
- Organizador: `preview` + `apply` + `rollback`
- UI mínima (biblioteca e detalhe) ou API estável para consumo
- CI verde em `main`

### Milestone B — Revisão e automação

Objetivo: operar acervos reais com conforto (review, cache, OPDS, thumbnails, async).

- Painel/fila de revisão para scores intermediários + merge/correções
- Cache de providers com auditoria (`provider_hit`)
- OPDS opcional (feed + download)
- Thumbnails locais
- Processamento assíncrono/filas (quando fizer sentido)

### Milestone C — Integrações e features avançadas

Objetivo: integrações, refinamentos e qualidade de vida.

- Import Goodreads CSV
- Providers adicionais (ISBNdb etc.)
- Séries/tags “inteligentes”
- i18n
- analytics/métricas

## Epics (trilhas por subsistema)

Abra epics como Issues (use o template **Epic**) e quebre em issues menores:

- Epic: Ingestão & Watcher
- Epic: Extração de metadados (EPUB/PDF/MOBI)
- Epic: Normalização & validação ISBN
- Epic: Providers + reconciliador (search/get_by_isbn, backoff/rate-limit)
- Epic: Banco + FTS5 + migrações
- Epic: Organizador (manifestos + rollback)
- Epic: API (contratos/endpoints)
- Epic: UI (Qt) e fluxo de revisão
- Epic: OPDS (Milestone B)

## Como acompanhar no GitHub

Recomendação:

- Crie Milestones A/B/C e associe issues.
- Crie um Project v2 (ex.: “MAI — Roadmap”) com campos `Status/Type/Area/Priority` e views (Board/Table/Roadmap).
- Use labels `type:*`, `area:*`, `prio:*` para triagem rápida (ver `.github/labels.yml`).

