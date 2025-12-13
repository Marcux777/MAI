# Processo

Este documento descreve como organizar trabalho no MAI (Issues/PRs/DoD), sem burocracia.

## Fonte única de verdade

- **Trabalho**: sempre vira Issue (bug/feature/epic).
- **Integração**: sempre via PR.
- **Status oficial**: Project + Milestones no GitHub.

## Issues

- Abra issues usando os templates:
  - Bug: `.github/ISSUE_TEMPLATE/bug_report.yml`
  - Feature: `.github/ISSUE_TEMPLATE/feature_request.yml`
  - Epic: `.github/ISSUE_TEMPLATE/epic.yml`
- Use labels para triagem rápida:
  - `type:*`, `area:*`, `prio:*`, `status:*` (ver `.github/labels.yml`).

### Triage (ritual leve)

1. Issue nova entra como `prio: p2` e `Status=Todo` no Project.
2. Na triagem, defina `Type/Area/Priority` e associe Milestone.
3. Se estiver bloqueada, aplique `status: blocked` com o motivo (e link da dependência).

## Pull Requests

- Use `.github/pull_request_template.md`.
- `main` deve ficar sempre verde (CI passando).
- Preferência por PRs pequenos, revisáveis e com descrição/testes claros.

## Definition of Done (DoD)

O DoD por tipo de issue está em `CONTRIBUTING.md` (inclui checks de CI, testes quando aplicável e consistência do fluxo de ingestão/organização).

## Releases

O processo de release (SemVer + `CHANGELOG.md` + tag `vX.Y.Z`) está em `RELEASING.md`.

## Comandos úteis

- Subir API via Docker: `make up`
- Rodar testes: `pytest -q`
- (Opcional) Ruff: `ruff check .` e `ruff format .`

