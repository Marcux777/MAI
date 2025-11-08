# MAI — Gerenciador Local de Livros

MAI é um catálogo local-first focado em identificação confiável, busca rápida e enriquecimento automático de metadados para coleções pessoais de ebooks. O objetivo é manter 100% dos dados em SQLite, indexados com FTS5, expondo tanto uma API REST quanto uma UI local/OPDS para consumo em e-readers.

## Objetivos principais
- Ingestão autônoma de arquivos (EPUB/PDF/MOBI) com impressão digital SHA-256.
- Identificação e validação robusta (ISBN10/13, título/autor normalizados, score de confiança).
- Enriquecimento incremental a partir de múltiplas fontes abertas (Open Library, Google Books, BookBrainz; Goodreads somente para quem possui chave legada).
- Organização física dos arquivos segundo convenções configuráveis.
- Busca em tempo real via SQLite FTS5, com filtros por autor, idioma, tag e ano.

## Arquitetura Local-First
| Camada            | Função                                                                                                                                          |
|-------------------|-------------------------------------------------------------------------------------------------------------------------------------------------|
| Watcher + Import  | `watchdog` monitora diretórios, dispara extração de metadados (EbookLib, PyMuPDF) e calcula `sha256`.                                            |
| Identificador     | Normaliza título/autor, valida ISBN, gera score de matching e decide quando consultar provedores.                                               |
| Plugins (Providers)| Open Library, Google Books, BookBrainz, Goodreads legado, ISBNdb opcional. Interface unificada (`search`, `get_by_isbn`).                        |
| Enriquecimento    | Consolida dados retornados, aplica regras de priorização e persiste `payload_json` no cache (`provider_hit`).                                    |
| Banco + Busca     | SQLite normalizado + tabela virtual `search` (FTS5) para consulta prefixada/stemming.                                                            |
| Organizador       | Move arquivos para árvore canônica `Autor/Serie/NN - Título (Ano) [ISBN][Formato].ext`.                                                         |
| API & UI          | FastAPI + SQLAlchemy (REST), UI desktop/web com painel de revisão, editor de metadados e monitor de tarefas.                                    |
| OPDS (opcional)   | Feed OPDS 1.2 para sincronizar com leitores compatíveis.                                                                                        |

## Fluxo de ingestão
1. **Detecção**: watcher encontra arquivo novo, registra caminho e calcula `sha256`.
2. **Extração**: módulos específicos leem Dublin Core (EPUB) ou XMP (PDF) e retornam metadados brutos.
3. **Normalização**: limpeza de acentos/pontuação, lower-case, remoção de stopwords, heurísticas de autor (sobrenome dominante).
4. **Identificação**:
   - ISBN válido → consulta direta via `get_by_isbn` nos provedores.
   - Sem ISBN → busca textual (`search`) com título + autor + ano.
5. **Scoring**: aplica pesos (ISBN exacto=1.0, título≥0.92 Jaro-Winkler=0.35, autor=0.35, ano/publisher/idioma ±0.05, penalidades por conflito).
6. **Persistência**: cria/atualiza `work`, `edition`, `author`, `identifier`, `file`, `provider_hit`, popula `search` (FTS5) e salva thumbnails.
7. **Organização**: renomeia/move arquivos e agenda otimizações (`ANALYZE`, `fts5 optimize`).
8. **Revisão manual** (score 0.65–0.84) através da UI para merges e correções.

## Banco de Dados
- Script completo em `db/schema.sql`.
- Principais entidades: `work`, `edition`, `author`, `work_author`, `identifier`, `file`, `provider_hit`, `series`, `series_entry`, `tag`, `book_tag`, `task`.
- Busca full-text via `search` (FTS5) cobrindo título, autores, séries, editora e tags.
- `provider_hit` armazena o payload bruto e um score para auditoria/caching (30 dias recomendado).

## Plugins de metadados
- **Open Library**: Search/Works/Editions + Covers; evite bulk fora dos dumps mensais.
- **Google Books**: endpoint `volumes` (busca e ISBN); thumbnails em `imageLinks`.
- **BookBrainz**: dados complementares de obras/séries.
- **Goodreads**: apenas para quem possui chave pré-2020 ou para import via CSV oficial.
- **ISBNdb**: opcional (pago) para informações comerciais.
Cada plugin retorna um DTO padronizado (`title`, `authors`, `year`, `publisher`, `ids`, `cover_url`) para simplificar o reconciliador.

## API Local
- `GET /books?q=...` (FTS + filtros: `author`, `language`, `year`, `tag`).
- `GET /books/{edition_id}` (detalhes completos + arquivos físicos + hits de provedores).
- `POST /import/scan` (varre diretórios configurados manualmente).
- `POST /providers/fetch` (força enriquecimento/reconsulta).
- `POST /files/attach` (associa arquivo existente a uma edição).
- `GET /opds/**` (opcional, catálogo OPDS 1.2).
- `POST /import/scan` / `POST|DELETE /import/watch` (já disponíveis na API) para disparar ingestões e controlar o watcher.
- `POST /organize/preview` (gera manifestos de organização com caminhos sugeridos e permite revisão antes de aplicar).
- `POST /organize/apply/{id}` e `POST /organize/rollback/{id}` controlam a aplicação e reversão dos manifestos.
- `GET /organize/{id}` lista detalhes/ops de um manifesto com filtros por status para aplicação incremental.

## Roadmap sugerido
1. **Fase A (MVP)**: scanner + extração EPUB/PDF, validação ISBN, plugins Open Library/Google Books, SQLite + FTS5, UI mínima, renomeação automática.
2. **Fase B**: painel de revisão/manual merge, cache inteligente, OPDS, thumbnails locais, filas de tarefas assíncronas.
3. **Fase C**: import Goodreads CSV, BookBrainz/ISBNdb, suporte a séries/tags inteligentes, internacionalização, analytics.

## Stack recomendada (Python)
- FastAPI + Uvicorn
- SQLAlchemy + Alembic + SQLite/FTS5
- Watchdog (ingestão), EbookLib (EPUB), PyMuPDF (PDF), Pillow (imagens)
- httpx (providers) + rapidfuzz (matching) + python-levenshtein opcional
- Rich / Textual (CLI) ou Electron/Tauri/Qt para UI desktop

## Boas práticas e limites
- Respeitar ToS/limites de cada API (Open Library desencoraja bulk via REST, use dumps mensais ao precisar de massa).
- Não remover DRM; somente arquivos legítimos.
- Cache por ISBN/título com expiração configurável; aplicar backoff exponencial em erros 429/5xx.
- Armazenar `payload_json` para auditoria e repetir decisões determinísticas.
- Log estruturado + métricas (taxa de acerto, tempo médio de ingestão, falhas por provedor).
- Testes unitários (ISBN, normalização, scoring), testes integrados com fixtures de payload e um catálogo de exemplo end-to-end.

---
Para detalhes de implementação veja `db/schema.sql` (DDL completo) e `scripts/ingest_pipeline.py` (esqueleto do scanner + provedores Open Library/Google Books).

- Gere um conjunto sintético de arquivos (PDF+EPUB) executando `python scripts/generate_beta_pack.py`; os arquivos ficam em `beta_pack/`.
- Importe o lote com `mai-import beta_pack` ou `POST /import/scan` para validar o pipeline completo antes de usar seu acervo real.
- Pré-visualize a organização resultante com `mai-organize preview --root <destino>` ou `POST /organize/preview`, aplique via `mai-organize apply <manifesto>` / `POST /organize/apply/{id}` e reverta com `mai-organize rollback <manifesto>` / `POST /organize/rollback/{id}` sempre que precisar desfazer.
- Para revisar manifestos via API sem rodar o backend manualmente, use `scripts/organize_report.py <manifest_id>` (requer API local ativa) e visualize as operações em formato de tabela.
- **App desktop Qt**: execute `pip install -e .` e depois `mai-qt` para abrir a interface nativa PySide6 (biblioteca, revisão, organizer, import, tarefas, métricas, settings) comunicando diretamente com os serviços Python, sem precisar de servidor HTTP.
