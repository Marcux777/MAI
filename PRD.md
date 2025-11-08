# PRD — MAI (Gerenciador Local de Livros)

## 1. Resumo Executivo
MAI é um gerenciador local-first para coleções pessoais de ebooks. Ele detecta novos arquivos, identifica cada obra com alta confiança, enriquece metadados via provedores públicos (Open Library, Google Books, BookBrainz) e oferece busca instantânea através de SQLite + FTS5. A experiência principal passa a ser um **aplicativo desktop nativo em Qt (PySide6)**, estilo Calibre: janela própria, banco embutido e IPC interno, sem servidor HTTP/localhost exposto para o usuário final. A API FastAPI continua disponível como modo desenvolvedor/testes, mas o binário final roda totalmente offline, conversando direto com os serviços Python.

## 2. Objetivos e Métricas de Sucesso
- **Cobertura de identificação**: ≥90% dos arquivos com ISBN válido ou match automático (score ≥0.85).
- **Latência de busca**: <150 ms (p95) para consultas simples usando FTS5 em até 50 mil registros.
- **Tempo de ingestão**: <10 s por arquivo EPUB/PDF (incluindo extração, hashing e enriquecimento assíncrono quando online).
- **Integridade**: 0 duplicidades confirmadas (mesmo SHA-256) após ingestão.
- **Satisfação de revisão**: ≤10% dos itens caindo em fila manual (score entre 0.65–0.84) após tuning do pipeline.
- **Validação beta**: piloto com ≥100 livros reais antes do MVP, medindo taxa de acerto, reviews manuais e feedback de usabilidade do painel.

## 3. Personas e Casos de Uso
- **Colecionador (Marcus)**: mantém diretórios com centenas de livros, quer organização automática, enriquecimento confiável e renomeação consistente sem depender de nuvem.
- **Pesquisador (Lia)**: precisa buscar rapidamente por autor/tema/idioma, exportar listas e integrar com leitores via OPDS.
- **Automatizador (Renato)**: utiliza API REST para disparar importações, anexar notas e sincronizar com outras ferramentas locais.

Casos principais:
1. Importar pastas existentes e identificar cada arquivo com o melhor match disponível.
2. Revisar manualmente candidatos com score intermediário, aprovando ou ajustando metadados.
3. Pesquisar o catálogo por título/autor/tag e abrir detalhes com arquivos associados.
4. Sincronizar biblioteca com e-readers via OPDS ou exportações.

## 4. Escopo
**Incluído**
- Watcher configurável + import manual.
- Extração de metadados de EPUB/PDF/MOBI.
- Identificação baseada em ISBN + matching heurístico.
- Plugins para Open Library, Google Books, BookBrainz (Goodreads apenas via chave legada ou CSV do usuário).
- Banco SQLite normalizado + FTS5.
- **App desktop nativo Qt (PySide6)**: biblioteca virtualizada, detalhe dockable, revisão, organizer e métricas tudo em uma janela.
- API REST local apenas para modo desenvolvedor/integrações.
- OPDS 1.2 (Fase B+).
- Operação single-user/local; preferências e caminhos são globais para a máquina.

**Excluído / Futuro**
- Análise ou remoção de DRM.
- Sincronização em nuvem ou multiusuário distribuído (avaliar pós-v1 se serão bibliotecas independentes por usuário ou compartilhadas com ACL).
- Compra/consulta a catálogos pagos, exceto via plugin opcional (ISBNdb).
- Integração direta com Calibre/BibTeX/RIS/Zotero (export/import avançados ficam para pós-v1).
- Plugins pagos adicionais (ISBN.org, ISBNdb) somente após validar o fluxo básico.

## 5. Requisitos Funcionais
1. **Ingestão**
   - Watchdog observa diretórios configurados; import manual via CLI/API dispara o mesmo pipeline.
   - Para cada arquivo: detectar formato, calcular SHA-256, coletar tamanho/mime e verificar duplicidades.
   - A cada revarredura, recalcular SHA-256 e `last_seen`; divergência indica arquivo alterado/corrompido e gera alerta.
2. **Extração local**
   - EPUB: ler `content.opf` (Dublin Core) usando EbookLib; coletar título, autores, idioma, identificadores e pistas de capa.
   - PDF: usar PyMuPDF para XMP/Document.info.
   - MOBI/AZW: usar `python-mobi` (quando possível) ou fallback via `kindlegen`/exiftool para título/autor/ISBN; se falhar, manter somente metadados locais.
3. **Identificador**
   - Validar/converter ISBN10→13; normalizar strings (remover acentos/stopwords, heurística de autor) e gerar query padrão.
   - Calcular score (ISBN exato=1.0; título/autor com pesos 0.35 cada; ano/publisher/idioma ±0.05; penalidades para conflitos).
   - Score ≥0.85 aceita automaticamente; 0.65–0.84 vai para fila de revisão; abaixo disso permanece com metadados locais.
4. **Enriquecimento**
   - Consultar provedores via `get_by_isbn` e `search` com limite configurável e backoff exponencial.
   - Persistir `provider_hit` com payload bruto, score e data; cache expira após 180 dias ou quando uma edição sofrer merge/manual override (invalida hits relacionados).
   - Diferenciar falhas por provedor: se um provider responder e outro falhar, registrar parcialmente e reprocessar em background.
5. **Banco e Busca**
   - Modelo com `work`, `edition`, `author`, `identifier`, `file`, `series`, `tags`, `provider_hit`, `task`.
   - FTS5 (`search`) atualizado por triggers (ver `db/schema.sql`).
   - O campo `series_entry.position` permanece `REAL` para admitir valores fracionários (ex.: 2.5 em spin-offs/mangás).
6. **Organizador**
   - Renomear/mover arquivos para estrutura configurável (ex.: `Autor/Serie/NN - Título (Ano) [ISBN][Formato].ext`).
   - Antes de aplicar, gerar manifest/dry-run (`path_before`, `path_after`, `timestamp`) para permitir rollback do último lote.
7. **API & UI**
   - FastAPI expose: `GET /books`, `GET /books/{id}`, `POST /import/scan`, `POST /providers/fetch`, `POST /files/attach`, endpoints para fila de revisão e tags.
   - UI desktop/web: grade do catálogo, painel de revisão, editor de metadados, preferências.
8. **OPDS (opcional)**
   - Servir feed OPDS 1.2 autenticado localmente.

## 6. Requisitos Não Funcionais
- **Local-first**: todo dado e cache ficam em disco local; funcionamento offline obrigatório (providers só enriquecem quando houver rede).
- **Desempenho**: ingestão sequencial <10 s/arquivo; busca <150 ms p95; filas assíncronas para chamadas externas.
- **Confiabilidade**: banco com foreign keys on, backups simples (arquivo SQLite) e rotinas de `VACUUM/ANALYZE` opcionais.
- **Observabilidade**: logging estruturado (JSON) com métricas mínimas (`scan_latency_ms`, `provider_error_total{provider=}`, `fts_query_ms`, `db_size_mb`, `organizer_ops_total`), exportadas para stdout/arquivo.
- **Segurança**: nunca remover DRM; proteger diretórios padrão; API exposta apenas em localhost por padrão.
- **Testabilidade**: suíte com testes unitários (ISBN, normalização, scoring), mocks dos provedores e fixtures de catálogo.
- **Resiliência**: pipeline continua com metadados locais se todos os providers falharem; falhas parciais são registradas e recolocadas na fila com backoff exponencial.
- **Migrações**: versionar schema via Alembic (semver), testar cada migration com dump sintético de 100k edições + snapshot real; upgrades são roll-forward (rollback = restore do arquivo antes da migração).
- **Rate limit e prioridade**: definir budget por provedor (ex.: Open Library ≤60 req/min, Google Books ≤1k/dia) e fila priorizando `get_by_isbn` antes de `search` textual.

## 7. Arquitetura e Componentes
- **Watcher & Importer** (watchdog + CLI) → publica eventos de ingestão.
- **Extractor** (EbookLib, PyMuPDF) → fornece `LocalMetadata` + SHA-256.
- **Identifier & Matcher** (rapidfuzz) → controla consulta a providers e scoring.
- **Metadata Plugins** (Open Library, Google Books, BookBrainz, Goodreads legado, ISBNdb opcional) → interface unificada (DTO).
- **Persistence Layer** (SQLAlchemy + SQLite/FTS5) → aplica DDL de `db/schema.sql`.
- **File Organizer** → renomeia/move, gera thumbnails (Pillow) e sinaliza UI.
- **App Desktop Qt**: camada de apresentação em PySide6 com `QApplication`, `QMainWindow`, docks, `QTableView` virtualizada e widgets especializados (Revisão, Organizer, Import/Watcher, Tarefas, Métricas, Settings). Comunicação direta com services Python via chamadas internas/sinais Qt, sem HTTP.
- **API/Worker (modo dev)**: FastAPI permanece para integrações/automação (CLI, scripts, testes) mas não faz parte do fluxo usuário final.
- **OPDS Service** (fase futura) → reusa DB/FS e serializa feeds Atom.

## 8. Fluxos Críticos
1. **Ingestão automática**: watcher detecta arquivo → extração → hash/dup-check → identificação → persistência → indexação FTS; serviço emite sinais Qt para atualizar a tabela sem polling HTTP.
2. **Enriquecimento manual**: usuário abre o drawer Qt (abas Metadados/IDs/Arquivos/Provedores/Histórico), edita campos e aciona provedores; mudanças salvam direto no serviço Python e reindexam o FTS daquela edição.
3. **Busca**: campo global (`QLineEdit`) envia a query para `LibraryService.list_books()` → modelo (`QAbstractTableModel` + `QSortFilterProxyModel`) filtra/ordena em memória; sem roundtrip HTTP.
4. **Revisão de matches**: painel mestre/detalhe em Qt lista a fila 0.65–0.84; atalhos (J/K, 1/2/3, A) aplicam candidatos, atualizam DB/FTS e removem o item da fila instantaneamente.
5. **Organizer**: preview gera manifestos (tabela Qt com filtros), apply/rollback pausam o watcher, executam moves atômicos com barra de progresso e logs em tempo real; watcher retoma automaticamente.
6. **Modo Dev/API**: FastAPI continua disponível para automação, mas fica desabilitada no build final por padrão; só é exposta quando `MAI_API_DEV=1` (ex.: CI, scripts externos).

## 9. API (MVP)
- `GET /books`: parâmetros `q`, `author`, `language`, `year`, `tag`, `limit`, `offset`.
- `GET /books/{edition_id}`: inclui work, autores, arquivos, hits recentes.
- `POST /import/scan`: `{ "path": "...", "recursive": true }`.
- `POST /providers/fetch`: `{ "edition_id": 123, "providers": ["openlibrary"] }`.
- `POST /files/attach`: associa arquivo manual (`file_id`, `edition_id`).
- `GET /review-pending`: lista matches 0.65–0.84.
- `POST /review/resolve`: resolve candidato escolhido; atualiza score/log.
- `GET /opds/...`: disponível fase B.

## 10. Roadmap
- **Fase A (MVP Qt)**
  1. Consolidar serviços (ingest, identify, organizer) e garantir APIs Python estáveis.
  2. Implementar shell Qt (biblioteca + detalhe + busca + filtros) reutilizando `LibraryService` direto; suportar edição inline, tags, abrir na pasta.
  3. Integrar revisão e organizer nativos (preview/apply/rollback com progress bar), empacotar com PyInstaller para Windows/Linux/macOS.
- **Fase B**
  1. Painel de tarefas/watcher com threads Qt, notificações, thumbnails locais.
  2. OPDS 1.2, BookBrainz plugin, import manual do CSV Goodreads.
  3. Settings avançadas (provedores, templates, caminhos), internacionalização básica e modo Dev/REST habilitável.
- **Fase C**
  1. Plugins pagos opcionais (ISBNdb), tags inteligentes, séries enriquecidas.
  2. Fluxo de backup/export e sincronização leve (ex.: export JSON/OPDS incremental).
  3. Automação de testes E2E (pytest-qt/Playwright) e empacotes assinados (AppImage/DMG/MSIX) com atualização automática.

**Timeline estimada**: Fase A (MVP) ~12 semanas (3 sprints de 4 semanas); Fase B adiciona ~8 semanas (2 sprints) após validação beta; Fase C depende de adoção, previsão inicial ~8 semanas extras.

## 11. Riscos e Mitigações
- **Goodreads API**: sem novas chaves desde 2020 → só usar se o usuário possuir credenciais legadas ou via import CSV.
- **Limites de API**: Open Library desencoraja bulk; usar dumps para importações massivas e cachear resultados.
- **Dependências nativas (PyMuPDF/Pillow)**: garantir bibliotecas de SO no Dockerfile (libjpeg, openjp2, etc.).
- **Arquivos corrompidos/DRM**: marcar erro, não tentar contornar.
- **Duplicidade de autores/obras**: definir heurísticas de normalização (sort_name) e rotinas de merge manual.

## 12. Telemetria e Indicadores
- Taxa de sucesso de identificação (auto vs manual vs falha).
- Latência média/p95 da ingestão e da busca.
- Contagem por provedor (erros, acertos, tempo médio).
- Número de arquivos organizados/pendentes.
- Uso de armazenamento (tamanho do DB, cache de capas).

## 13. Validação Beta e Dataset
- **Beta Pack (v0.1)**: conjunto curado de 100 arquivos reais (mix EPUB/PDF/MOBI, com/sem ISBN, séries e casos problemáticos). Usado antes de liberar o MVP para medir automaticamente taxa de acerto, duplicidades e fila manual.
- **Experimento Beta 0**: rodar ingestão completa no acervo do primeiro usuário piloto, aplicar painel de revisão e coletar feedback qualitativo sobre UX (tarefas observadas + formulário SUS).
- **Dataset público**: publicar versão anonimizada (quando possível) ou script gerador para repetir testes (garantindo licenças). Padronizar expected output para regressões.
- **Critérios de saída do MVP**: bater ≥85% de matches auto-aprovados no beta pack, ≤10% de revisão manual e zero perdas de arquivo após `organize`.
- **Lições beta**: registrar ao menos 3 riscos ou ajustes identificados após o piloto (ex.: heurísticas de score, UX do painel, desempenho do watcher) e atualizar backlog antes da próxima fase.

## 14. Referências
- README.md (arquitetura detalhada, pipeline, stack recomendada).
- `db/schema.sql` (DDL completo com triggers FTS5).
- `scripts/ingest_pipeline.py` (esqueleto de ingestão + provedores OL/GB).
- Documentação externa: Open Library API, Google Books API, BookBrainz WS, OPDS 1.2, SQLite FTS5, EbookLib, PyMuPDF.

## 15. Resumo de decisões
- UI principal = Qt Widgets (PySide6) com IPC interno; API FastAPI apenas para modo desenvolvedor.
- Empacotamento via PyInstaller/AppImage/DMG/MSIX; dados em `~/.mai/`.
- Serviços atuais (ingest, identify, organizer) seguem inalterados e expostos via classes Python.
- Futuro: considerar PWA/web apenas como complemento, nunca requisito para usuário final.
