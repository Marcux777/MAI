# ADRs (Architecture Decision Records)

Use ADRs para registrar decisões técnicas importantes de forma curta e rastreável.

## Quando criar um ADR

- Escolha de tecnologia com trade-offs (ex.: “por que FTS5”, “por que PySide6”)
- Decisões de schema/migração que afetam compatibilidade
- Estratégias de cache, scoring, backoff, organização de arquivos

## Como criar

1. Copie `docs/adr/0000-template.md`
2. Substitua `0000` pelo próximo número sequencial (ex.: `0001-fts5-search.md`)
3. Escreva o contexto, a decisão e as consequências
4. Faça PR e linke a issue/epic relacionada

