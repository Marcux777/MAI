# Contribuindo

Este projeto usa um fluxo simples, focado em manter a branch `main` sempre “verde” (build/test passando).

## Fluxo de branches (trunk-based leve)

- `main`: sempre estável (sem commits quebrados).
- Crie branches curtas (1 feature/fix por vez):
  - `feat/<slug-curto>`
  - `fix/<slug-curto>`
  - `chore/<slug-curto>`
- Integre via Pull Request (PR) sempre (evite push direto em `main`).

## Pull Requests

- Use o template de PR em `.github/pull_request_template.md`.
- Inclua:
  - Contexto/motivação (e link de issue/tarefa, se existir).
  - Como testar (comandos e passos).
  - Impacto/risco.
  - Nota rápida de performance quando tocar em ingestão/busca/organizer/DB.
- Preferência por PRs pequenos e revisáveis.

## Commits (Conventional Commits)

Adote **Conventional Commits** para manter histórico legível e facilitar changelog/release no futuro.

Formato recomendado:

- `<type>(<scope>): <descrição>`
- `<type>: <descrição>` (quando não fizer sentido definir scope)

Tipos sugeridos:

- `feat`, `fix`, `docs`, `chore`, `refactor`, `perf`, `test`, `ci`, `build`, `revert`

Scopes sugeridos (exemplos):

- `ingestion`, `providers`, `db`, `search`, `api`, `ui`, `opds`, `infra`

Exemplos:

- `feat(ingestion): add sha256 fingerprinting for new files`
- `fix(providers): handle 429 with exponential backoff`
- `docs(roadmap): detail phase A acceptance criteria`

Breaking changes:

- `feat(api)!: ...` ou footer `BREAKING CHANGE: ...`

### Dica (template de commit)

Há um template opcional em `.gitmessage`. Para habilitar:

- `git config commit.template .gitmessage`

## Issues (taxonomia e critérios)

Recomendação: habilite **Issues** no GitHub (Settings → General → Features → Issues) e use os templates:

- Bug Report: `.github/ISSUE_TEMPLATE/bug_report.yml`
- Feature Request: `.github/ISSUE_TEMPLATE/feature_request.yml`
- Epic: `.github/ISSUE_TEMPLATE/epic.yml`

### Labels

Use poucas labels, mas consistentes:

- `type:*`: `bug`, `feature`, `epic`, `chore`, `docs`, `tech-debt`
- `area:*`: `ingestion`, `providers`, `db`, `search`, `api`, `ui`, `opds`, `infra`
- `prio:*`: `p0`, `p1`, `p2`
- `status:*`: `blocked`

O arquivo `.github/labels.yml` define as labels. Para aplicar no GitHub:

- Rode o workflow manual `labels` (Actions → labels → Run workflow), ou
- Faça push alterando `.github/labels.yml` na `main` (o workflow roda automaticamente).

### Definition of Done (DoD)

**Bug/Feature “pronta” quando:**

- Passa CI (ex.: `ci / tests`)
- Tem teste quando aplicável (ou justificativa quando não)
- Atualiza doc mínima quando muda comportamento/contrato
- Foi revisada e aprovada via PR
- Não deixa o fluxo inconsistente (detecção → extração → normalização → identificação → scoring → persistência → organização → revisão)

**Epic “pronta” quando:**

- Checklist completa (issues linkadas fechadas)
- Não existem `status: blocked` pendentes
- Há um resumo final (o que mudou + como validar)

## Revisão

- Recomenda-se pelo menos 1 aprovação antes do merge.
- Se `CODEOWNERS` estiver habilitado (ver abaixo), áreas críticas pedem revisão automática.

## Checks (CI)

O workflow em `.github/workflows/ci.yml` roda `pytest -q` em `push`/`pull_request`.

Localmente:

- `pytest -q`
- (opcional) `ruff check .` e `ruff format .`

## CODEOWNERS

O arquivo `.github/CODEOWNERS` define owners por área e pode automatizar pedidos de revisão.

- Ajuste os usuários/times para valores reais do GitHub.
- Se for habilitar “Require review from Code Owners” nas proteções de branch, garanta que o arquivo esteja correto.

## Proteção da branch `main` (GitHub)

Essa configuração é feita no GitHub (Settings → Branches → Branch protection rules):

- Require a pull request before merging
- Require approvals (ex.: 1)
- Require status checks to pass before merging
  - Selecione o check do Actions (geralmente `ci / tests`)
- Require branches to be up to date before merging (recomendado)
- (opcional) Require review from Code Owners
- (opcional) Require conversation resolution
- (opcional) Include administrators

## Releases

Veja `RELEASING.md` para versionamento (SemVer), `CHANGELOG.md` e publicação de releases no GitHub.
