# Processo de release

A MAI usa **Semantic Versioning** (`X.Y.Z`) e mantém mudanças em `CHANGELOG.md` (Keep a Changelog).

## Versionamento (SemVer)

- **MAJOR** (`X`) para breaking changes.
- **MINOR** (`Y`) para features compatíveis (sem quebrar).
- **PATCH** (`Z`) para fixes compatíveis (sem quebrar).
- Pre-releases usam hífen (ex.: `0.2.0-rc.1`) e tags seguem o mesmo padrão (`v0.2.0-rc.1`).

## Passos para publicar um release

1. Abra um PR com:
   - Bump de versão em `pyproject.toml` e `src/mai/__init__.py`
   - Atualização do `CHANGELOG.md` (mova itens de `[Unreleased]` para uma nova seção)
2. Garanta que o CI está verde.
3. Faça merge na `main`.
4. Crie e envie a tag:
   - `git tag vX.Y.Z`
   - `git push origin vX.Y.Z`
5. Um GitHub Action publica o release a partir da tag e usa a seção correspondente do `CHANGELOG.md` como notas.

## Observações

- O workflow valida:
  - Tag bate com `pyproject.toml` e `src/mai/__init__.py`
  - `CHANGELOG.md` tem uma seção para a versão
