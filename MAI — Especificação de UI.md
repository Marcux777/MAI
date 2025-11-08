# MAI — Especificação de UI (v1)

> Objetivo: definir **UI local-first** para ingestão, identificação, edição, organização e auditoria do acervo, com foco em **performance**, **segurança** e **controle**.

---

## 1) Princípios e stack

* **Direção de produto**: velocidade > brilho. Evitar mágica opaca. Mostrar origem dos dados e permitir override fácil.
* **Stack**: **Qt Widgets (PySide6)** com `QMainWindow` + docks, `QTableView/QAbstractItemModel`, `QSplitter`, `QTabWidget`, `QThreadPool` para tarefas, temas claro/escuro via palettes. Nada de servidor HTTP embutido.
* **Runtime**: `QApplication` único, comunicação direta com serviços Python (Signals/Slots). API FastAPI só para modo desenvolvedor.
* **Arquitetura**: módulos Qt → serviços (`LibraryService`, `RevisionService`, `OrganizerService`, etc.) → camada de persistência SQLite. Eventos assíncronos via `pyqtSignal`/`QThread`.
* **A11y**: foco visível, atalhos globais (`QShortcut`), padrões nativos de acessibilidade (Qt Accessibility). Sem dependências web externas.

---

## 2) Layout geral

* **Topbar** (fixa):

  * Campo de **busca global** (FTS) com sugestões; input de consulta estruturada.
  * Botões: *Scan*, *Revisão*, *Organizer*, *Tarefas*, *Métricas*, *Config*.
  * Indicadores: estado do **Watcher** (ON/OFF), fila de tarefas (contador), status de rede (online/offline).
* **Sidebar** (colapsável à esquerda): Facetas e filtros (autor, idioma, ano, série, tags, formato, has:file, provedores). Chips de filtros ativos.
* **Conteúdo** (principal): Lista/Grade da biblioteca com paginação/infinite scroll (virtualizada).
* **Right Drawer** (detalhe): abre sobre a lista para edição rápida; modo tela cheia opcional.
* **Notificações**: `QSystemTrayIcon` + `QMessageBox` para feedback (sucesso/erro/aviso) e painel de logs lateral.

**Breakpoints**: sm ≥ 640, md ≥ 768, lg ≥ 1024, xl ≥ 1280. Layout responsivo; prioridade desktop.

---

## 3) Navegação e estados

* **Áreas do app** (selecionadas via `QToolBar`/`QStackedWidget`): Biblioteca (default), Revisão, Organizer, Import/Watcher, Tarefas, Métricas, Config.
* **Estados**: seleção (multi, `QItemSelectionModel`), filtros ativos (mantidos em `QSortFilterProxyModel` + `QSettings`), consulta atual, paginação/infinite scroll, drawer/dock aberto, tema (palette claro/escuro), colunas visíveis, ordem dos provedores.

---

## 4) Telas — requisitos e UX

### 4.1 Biblioteca (lista/grade)

* **Componentes**:

  * Barra secundária (`QToolBar`): contador de resultados, ordenação (Título, Autor, Ano, Data de adição), toggle Lista/Grade, seleção em massa.
  * `QTableView` com `QAbstractTableModel` + `QSortFilterProxyModel` para 100k+ itens (scroll liso). Grade opcional com `QListView` + `QStyledItemDelegate` (thumbnails).
* **Colunas padrão (lista)**: Capa, Título, Autores, Ano, Série, Idioma, Editora, Tags, Formato, Indicadores (capa/identificado/provedor), Data de adição.
* **Ações em linha**: `QMenu` de contexto (abrir detalhe, editar tags inline, marcar para revisão, abrir na pasta, copiar caminho).
* **Multi‑seleção (Shift/Ctrl)**: aplicar tags, mover para série, abrir Organizer Preview apenas desses itens.
* **Empty states**: widgets dedicados (limpar filtros / importar Beta Pack).
* **Performance**: carregamento incremental (fetch em lotes) + `QTimer` para debounce de busca.

### 4.2 Detalhe (drawer)

* **Abas**: `QTabWidget` com *Metadados*, *Identificadores*, *Arquivos*, *Provedores*, *Histórico*.
* **Metadados**: `QFormLayout` com validação (título, subtítulo, sinopse, autores/alias, idioma, páginas, série/ordem, editora/ano). Salvamento inline (Enter) e autosave (QTimer debounce).
* **Identificadores**: ISBN10/13 (validação instantânea), OLID, GBID, OCLC, ASIN. Botão "Consultar provedores".
* **Arquivos**: lista de arquivos ligados (multi‑formato), hash, tamanho, MIME, botão "Abrir no sistema".
* **Provedores**: `QTableView` comparando provider, título/autor/ano, score e diffs por campo; botões *Aceitar*/*Rejeitar* (atalhos 1/2/3).
* **Histórico**: lista (QTreeView) com mudanças, fonte vencedora por campo, botão para abrir payload JSON (exibe em `QPlainTextEdit`).

### 4.3 Revisão de matches

* **Objetivo**: esvaziar fila 0.65–0.84 de score.
* **Layout**: painel mestre‑detalhe. Esquerda: lista de itens com score, provedores top; Direita: comparador com **diff por campo** (antes × candidato escolhido) e mini‑previa de capa.
* **Ações**: *Aceitar* (aplica e reindexa), *Ignorar agora*, *Marcar como manual*, *Bloquear provedor para este item*.
* **Produtividade**: atalhos 1/2/3 para escolher candidato, `A` aceitar, `J/K` navegar.

### 4.4 Organizer

* **Sub‑abas**: *Preview*, *Apply*, *Rollback*, *Templates*.
* **Preview**: gera **manifest** com plano; sumariza: total, planned/skipped/collisions, estimativa de espaço, conflitos. Exibe tabela (src→dst, razão, status). Filtros por status.
* **Apply**: barra de progresso, contadores `done/failed/skipped`, logs em tempo real (WS). Pausa automática do Watcher.
* **Rollback**: lista manifests aplicados; botão *Reverter* com confirmação de risco.
* **Templates**: editor com placeholders disponíveis, validação e exemplo vivo.

### 4.5 Importação / Watcher

* **Scan**: selecionar diretório(s), recursivo, exclusões (glob). Botão *Rodar agora* → tarefa enfileirada.
* **Watcher**: tabela de paths monitorados, status, último evento, throughput. Botões *Start/Stop*. Banner de alerta para alto volume.
* **Logs**: últimos N eventos (arquivo detectado, metadado extraído, erro de parser, etc.).

### 4.6 Tarefas & Logs

* **Fila**: tipo, alvo (edition_id/path), estado (queued/running/done/failed), tentativa, duração, erro.
* **Controles**: cancelar tarefa, reexecutar, limpar concluídas.
* **Filtros**: por tipo (Ingest/Identify/Reindex/Organize), por status.

### 4.7 Configurações

* **Provedores**: chaves, ordem de consulta, TTL de cache, limites de concorrência.
* **FTS**: botões *Rebuild* e *Optimize* com progresso.
* **Organizer**: root, template padrão, estratégia de colisão (keep/overwrite/suffix).
* **Preferências de UI**: tema, densidade, colunas visíveis, tamanho da grade.
* **Backup**: export/import de banco (snapshot), export CSV/JSON do acervo.
* **Avançado**: porta do servidor, auth por token, diretórios de dados.

### 4.8 Métricas

* **Qualidade**: auto_accept_rate, review_queue_size, histograma de top_score.
* **Provedores**: cobertura por idioma/ano, latência média e p95, timeouts/429.
* **Organizer**: colisões, taxa de sucesso, rollbacks.
* **Busca**: latência p50/p95, tamanho do índice.
* **UI**: tempo de render da lista (opcional, local).

---

## 5) Pesquisa e filtros (UX)

* **Caixa de busca** aceita:

  * Texto livre (FTS, prefixo por padrão): `dostoievski crime*`.
  * Campos: `author:"Fiódor" year:>=1866 lang:ru has:file provider:openlibrary`.
  * Alias: `serie:`/`series:`, `pub:`/`publisher:`.
* **Sugestões**: `QCompleter` com últimos termos, autores e séries frequentes.
* **Chips**: representados por `QToolButton`/`QLabel` descartáveis; salvar *vistas* via `QSettings`.
* **Debounce**: `QTimer` (200–300 ms). Enter força busca imediata chamando `LibraryService.list_books`.

---

## 6) Componentes atômicos

* **BookRow (QStyledItemDelegate)**: thumbnail, campos principais, badges (capa/identificado/DRM), menu de contexto.
* **FacetFilter**: `QListWidget` com checkboxes + contador; busca interna (`QLineEdit` + `QSortFilterProxyModel`).
* **TagEditor**: `QLineEdit` + `QCompleter`, criação on-the-fly, validação.
* **AuthorPicker**: `QDialog` com busca local/remota, suporte a aliases.
* **SeriesControl**: formulário com spinbox (float) e reorder drag-and-drop.
* **DiffField**: `QPlainTextEdit` read-only com highlight (QSyntaxHighlighter).
* **PathPreview**: widget que renderiza template + valida caracteres proibidos.
* **TaskToast**: `QSystemTrayIcon`/dock log exibindo progresso/erro.
* **ConfirmDialog**: `QMessageBox` padronizado (com estilo destrutivo).

---

## 7) Estados, cache e eventos

* **Cache em memória**: `LibraryService` mantém último lote; `QAbstractTableModel` atualiza incrementalmente.
* **Eventos**: sinais Qt (`pyqtSignal`) emitidos pelos serviços (ingest detectado, identify done, organizer progress). Opcional: `QThread` que escuta fila e atualiza UI.
* **Undo/Redo**: implementar com `QUndoStack` para tags e campos editáveis.

---

## 8) Atalhos de teclado

* Global (`QShortcut`): `/` foca busca; `Ctrl+1…7` alterna módulos; `F1` abre ajuda.
* Lista: `↑/↓` navega; `Space` seleciona; `Enter` abre detalhe; `Ctrl+A` selecionar tudo; `Del` remove tag selecionada.
* Revisão: `1/2/3` escolher candidato; `A` aceitar; `J/K` navegar; `R` recarregar candidatos.
* Organizer: `P` preview; `Y` apply; `B` rollback.

---

## 9) Acessibilidade

* Qt Accessibility (exposto automaticamente para screen readers). Fornecer descrições (`setAccessibleName`).
* Contraste AA mínimo nos palettes claro/escuro.
* Navegação por teclado 100%; `Tab` order configurado em formulários.
* Mudanças críticas exibem mensagens narradas (via `QAccessible::updateAccessibility`).

---

## 10) Erros e notificações

* Taxonomia: info/sucesso/aviso/erro.
* `QSystemTrayIcon` + `QStatusBar` para alertas curtos; `QMessageBox` para bloqueantes.
* Provedor 429/timeout → banner no painel (widget `QLabel` amarelo) com retry/backoff.
* Falhas do Organizer → linha marcada na tabela + ícone + botão "Ver log".
* Erros de validação (ISBN) inline (`QValidator` + tooltip explicativo).

---

## 11) Performance

* `QTableView` + `QSortFilterProxyModel`: apenas linhas visíveis renderizadas.
* Debounce (`QTimer`) em filtros/busca; carregamento incremental (fetch em lotes).
* Operações pesadas em `QThreadPool`; nunca bloquear o thread principal.
* Thumbnails gerados localmente; cache em disco e `QPixmapCache`.
* Medir p95 de ações (ingest, busca, organizer) e registrar em log local.

---

## 12) Segurança

* Aplicativo nativo offline (sem exposição de porta). API dev só inicia quando configurada explicitamente.
* Proteção contra path traversal no Organizer (validação dupla: serviço + UI). Caminhos exibidos sempre normalizados.
* Store segura de credenciais (QSettings + sistema operacional).

---

## 13) Testes da UI

* **Unit** (pytest-qt): widgets/datatypes (DiffField, PathPreview, TagEditor).
* **Integração**: `pytest-qt` simulando ações (lista virtualizada, drawer + salvamento inline, fluxo de revisão/organizer).
* **E2E**: scripts PyInstaller rodando cenários completos (import beta pack → revisão → organizer → rollback → busca FTS).
* **A11y**: validar via ferramentas do Qt Accessibility + testes manuais com leitor de tela.

---

## 14) Design tokens

* **Tipografia**: sistema (Inter/SF/UI default), 14px base; 12/14/16/20/24/32.
* **Ritmo**: espaçamento 4px grid (4,8,12,16,24,32,48).
* **Raios**: 8/12/16.
* **Cores**: neutros (zinc/stone), realce azul para ação primária, laranja/âmbar para atenção, verde para sucesso, vermelho para erro. Tema escuro: elevar contrastes.

---

## 15) Exemplos de payloads (resumidos)

```json
GET /books?q=dostoievski&lang=ru&limit=50
{
  "items": [{
    "id": 123,
    "title": "Crime e Castigo",
    "authors": ["Fiódor Dostoiévski"],
    "year": 1866,
    "series": null,
    "language": "ru",
    "publisher": "",
    "tags": ["clássico"],
    "format": "EPUB",
    "cover": "/covers/123.jpg",
    "identified": true
  }],
  "total": 1
}
```

```json
POST /organize/preview
{
  "manifest_id": 17,
  "summary": {"total": 84, "planned": 80, "skipped": 3, "collisions": 1},
  "ops": [{
    "id": 1,
    "edition_id": 123,
    "src_path": "/lib/mix/CrimeeCastigo.epub",
    "dst_path": "/Books/Dostoiévski/Crime e Castigo (1866) [EPUB].epub",
    "status": "planned",
    "reason": "TEMPLATE"
  }]
}
```

---

## 16) Roadmap UI

* **Sprint 1**: Biblioteca (lista/grade), Drawer (Metadados/Arquivos), Busca/Facetas, Atalhos básicos.
* **Sprint 2**: Revisão (comparador + atalhos), Métricas (tabelas simples), WS toasts.
* **Sprint 3**: Organizer (preview/apply/rollback + templates) com progress bar e logs.
* **Sprint 4**: Import/Watcher, Settings completas, A11y e testes E2E.

---

## 17) Critérios de aceite por tela

* **Biblioteca**: render em <16ms por frame; rolagem fluida com 10k; seleção múltipla sem travar.
* **Revisão**: aceitar candidato atualiza item em <300ms e reindexa FTS; navegação J/K sem perda de foco.
* **Organizer**: apply move/copy atômico com barra de progresso e logs; rollback reverte 100% das ops *done*.
* **Settings**: alterar ordem de provedores reflete na próxima identificação sem reiniciar o app.

---

## 18) Wireframes (ASCII, orientação)

```
Topbar: [Busca________________________] [Scan] [Revisão] [Organizer] [Tarefas] [Métricas] [Config]  (Watcher: ON) (Queue: 3)

+-----------------------------------+---------------------------------------------+
| Sidebar (Facetas)                 | Biblioteca (Lista/Grade)                    |
| - Autor [ ] Dostoiévski (12)      | -----------------------------------------   |
| - Idioma [x] pt, [ ] en, [ ] ru   |  □  Capa  Título              Autor   Ano   |
| - Ano  1800—1900 slider           |  □  []    Crime e Castigo     F.D.   1866  |
| - Série ...                       |  □  []    ...                              |
+-----------------------------------+---------------------------------------------+

[Drawer: Detalhe]  Metadados | Identificadores | Arquivos | Provedores | Histórico
```

---

## 19) Observações finais

* Manter UI determinística: cada ação deve ter feedback claro (toast/log/badge).
* Sempre expor **fonte e score** quando houver escolha automática de metadados.
* Evitar estados escondidos: tudo que roda em background deve aparecer em **Tarefas**.
