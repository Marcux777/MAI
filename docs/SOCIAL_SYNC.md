# Social sync (Goodreads CSV)

This repository now supports a minimal, offline-friendly social sync via the Goodreads CSV export.
Because Goodreads API access is restricted and rate-limited, the current integration focuses on
manual CSV imports instead of direct API calls.

## What it does

- Reads the Goodreads "Export Library" CSV file.
- Updates MAI read status based on the exclusive shelf:
  - `read` -> `read`
  - `to-read` / `currently-reading` -> `unread`
- Optionally imports shelves as tags (with an optional prefix).
- Optionally stores identifiers (GOODREADS + ISBN13) to help future matching.
- Can create missing editions (metadata-only) when no match is found.

## CLI

```
mai-social goodreads import /path/to/goodreads_library_export.csv \
  --include-bookshelves \
  --tag-prefix goodreads \
  --overwrite-rating
```

Useful flags:
- `--dry-run`: simulate without writing to the DB.
- `--skip-missing`: do not create missing editions.
- `--no-read-status` / `--force-read-status`: control how read status is applied.
- `--no-tags` / `--include-bookshelves`: control shelf tags.
- `--no-rating` / `--overwrite-rating`: control rating updates.
- `--no-identifiers`: skip adding GOODREADS / ISBN13 identifiers.

## API

`POST /social/goodreads/import` with a multipart `file` upload and optional query params
matching the CLI flags (e.g. `dry_run=true&include_bookshelves=true`).

## Future integrations

- Open Library reading logs (public shelves + ratings).
- The StoryGraph API (subject to availability and auth flow).
- Bi-directional sync once API access and rate limits are viable.

Notes:
- The integration intentionally avoids direct Goodreads API calls today due to access limits.
- The Calibre plugin for Goodreads also warns about API rate limitations; CSV import is a
  safer default for MAI.
