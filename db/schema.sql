PRAGMA foreign_keys = ON;

-- Obras e edições
CREATE TABLE IF NOT EXISTS work (
  id           INTEGER PRIMARY KEY,
  title        TEXT NOT NULL,
  sort_title   TEXT,
  language     TEXT,
  description  TEXT,
  created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS edition (
  id           INTEGER PRIMARY KEY,
  work_id      INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
  title        TEXT,
  subtitle     TEXT,
  publisher    TEXT,
  pub_year     INTEGER,
  pages        INTEGER,
  format       TEXT,
  language     TEXT,
  cover_path   TEXT,
  cover_url    TEXT,
  created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at   TEXT
);

-- Autores e relacionamento N:N
CREATE TABLE IF NOT EXISTS author (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  sort_name  TEXT
);

CREATE TABLE IF NOT EXISTS work_author (
  work_id    INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
  author_id  INTEGER NOT NULL REFERENCES author(id) ON DELETE CASCADE,
  role       TEXT DEFAULT 'author',
  PRIMARY KEY (work_id, author_id, role)
);

-- Identificadores externos (ISBN/OCLC/etc)
CREATE TABLE IF NOT EXISTS identifier (
  id          INTEGER PRIMARY KEY,
  edition_id  INTEGER NOT NULL REFERENCES edition(id) ON DELETE CASCADE,
  scheme      TEXT NOT NULL,
  value       TEXT NOT NULL,
  UNIQUE (scheme, value)
);

-- Arquivos físicos monitorados
CREATE TABLE IF NOT EXISTS file (
  id          INTEGER PRIMARY KEY,
  edition_id  INTEGER REFERENCES edition(id) ON DELETE SET NULL,
  path        TEXT NOT NULL UNIQUE,
  ext         TEXT,
  size_bytes  INTEGER,
  sha256      TEXT UNIQUE,
  mime        TEXT,
  drm         INTEGER DEFAULT 0,
  added_at    TEXT DEFAULT CURRENT_TIMESTAMP,
  last_seen   TEXT
);

-- Cache bruto dos provedores
CREATE TABLE IF NOT EXISTS provider_hit (
  id          INTEGER PRIMARY KEY,
  provider    TEXT NOT NULL,
  remote_id   TEXT,
  edition_id  INTEGER REFERENCES edition(id) ON DELETE SET NULL,
  payload_json TEXT NOT NULL,
  score       REAL,
  fetched_at  TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(provider, remote_id)
);

-- Séries e participação das obras
CREATE TABLE IF NOT EXISTS series (
  id    INTEGER PRIMARY KEY,
  name  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS series_entry (
  series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
  work_id   INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
  position  REAL,
  PRIMARY KEY (series_id, work_id)
);

-- Tags
CREATE TABLE IF NOT EXISTS tag (
  id   INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS book_tag (
  edition_id INTEGER NOT NULL REFERENCES edition(id) ON DELETE CASCADE,
  tag_id     INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
  PRIMARY KEY (edition_id, tag_id)
);

-- Tasks (assíncronas, filas, etc.)
CREATE TABLE IF NOT EXISTS task (
  id          INTEGER PRIMARY KEY,
  kind        TEXT NOT NULL,
  payload_json TEXT,
  status      TEXT NOT NULL DEFAULT 'pending',
  result_json TEXT,
  created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
  started_at  TEXT,
  finished_at TEXT
);

-- Full-text search (FTS5) para catálogo
CREATE VIRTUAL TABLE IF NOT EXISTS search
USING fts5(
  title,
  authors,
  series,
  publisher,
  tags,
  content='',
  tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS search_config (
  key   TEXT PRIMARY KEY,
  value TEXT
);

-- View para popular FTS
CREATE VIEW IF NOT EXISTS vw_edition_search AS
SELECT
  e.id AS edition_id,
  COALESCE(e.title, w.title) AS title,
  (SELECT GROUP_CONCAT(a.name, ', ')
     FROM work_author wa
     JOIN author a ON a.id = wa.author_id
    WHERE wa.work_id = w.id) AS authors,
  (SELECT GROUP_CONCAT(s.name, ', ')
     FROM series_entry se
     JOIN series s ON s.id = se.series_id
    WHERE se.work_id = w.id) AS series,
  e.publisher,
  (SELECT GROUP_CONCAT(t.name, ', ')
     FROM book_tag bt
     JOIN tag t ON t.id = bt.tag_id
    WHERE bt.edition_id = e.id) AS tags
FROM edition e
JOIN work w ON w.id = e.work_id;

-- Trigger para manter FTS sincronizado
CREATE TRIGGER IF NOT EXISTS trg_search_insert
AFTER INSERT ON edition BEGIN
  INSERT INTO search(rowid, title, authors, series, publisher, tags)
  SELECT NEW.id, title, authors, series, publisher, tags
    FROM vw_edition_search
   WHERE edition_id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_search_update
AFTER UPDATE ON edition BEGIN
  INSERT INTO search(search, rowid, title, authors, series, publisher, tags)
  VALUES('delete', OLD.id, NULL, NULL, NULL, NULL, NULL);
  INSERT INTO search(rowid, title, authors, series, publisher, tags)
  SELECT NEW.id, title, authors, series, publisher, tags
    FROM vw_edition_search
   WHERE edition_id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_search_delete
AFTER DELETE ON edition BEGIN
  INSERT INTO search(search, rowid, title, authors, series, publisher, tags)
  VALUES('delete', OLD.id, NULL, NULL, NULL, NULL, NULL);
END;

-- Resultados de identificação / métricas
CREATE TABLE IF NOT EXISTS identify_result (
  edition_id INTEGER PRIMARY KEY REFERENCES edition(id) ON DELETE CASCADE,
  auto_accepted INTEGER NOT NULL,
  chosen_provider TEXT,
  top_score REAL NOT NULL,
  candidates_json TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS match_event (
  id INTEGER PRIMARY KEY,
  edition_id INTEGER NOT NULL REFERENCES edition(id) ON DELETE CASCADE,
  stage TEXT NOT NULL,
  provider TEXT NOT NULL,
  candidate_rank INTEGER NOT NULL,
  score REAL NOT NULL,
  accepted INTEGER NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Manifesto de organização de arquivos
CREATE TABLE IF NOT EXISTS organize_manifest (
  id INTEGER PRIMARY KEY,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  template TEXT NOT NULL,
  root TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'preview',
  watcher_state TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS organize_op (
  id INTEGER PRIMARY KEY,
  manifest_id INTEGER NOT NULL REFERENCES organize_manifest(id) ON DELETE CASCADE,
  edition_id INTEGER NOT NULL REFERENCES edition(id) ON DELETE CASCADE,
  src_path TEXT NOT NULL,
  dst_path TEXT NOT NULL,
  reason TEXT,
  status TEXT NOT NULL DEFAULT 'planned',
  error TEXT,
  src_sha256 TEXT,
  dst_sha256 TEXT
);

CREATE INDEX IF NOT EXISTS idx_match_event_edition ON match_event(edition_id);
CREATE INDEX IF NOT EXISTS idx_org_manifest_status ON organize_manifest(status);
CREATE INDEX IF NOT EXISTS idx_org_op_manifest ON organize_op(manifest_id);
CREATE INDEX IF NOT EXISTS idx_org_op_status ON organize_op(status);
