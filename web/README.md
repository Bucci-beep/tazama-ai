# Tazama dashboard

Next.js dashboard for the Tazama synthetic-data research prototype. It checks
backend health, records baseline and reassessment observations, and retrieves
persisted timelines without performing scoring or clinical interpretation.

## Run locally

From the repository root, start the API. `TAZAMA_DB_PATH` must point to an
existing initialized SQLite database:

```bash
TAZAMA_DB_PATH=/absolute/path/to/tazama.db \
  uv run uvicorn tazama.api.app:app --reload
```

In a second terminal, start the dashboard:

```bash
cd web
npm install
npm run dev
```

Open <http://localhost:3000>. The dashboard connects to
`http://127.0.0.1:8000` by default. Set `TAZAMA_API_URL` before starting Next.js
when the API is hosted elsewhere:

```bash
TAZAMA_API_URL=http://127.0.0.1:8000 npm run dev
```

## Verification

```bash
npm run lint
npm run build
```

Only synthetic case identifiers and data are permitted. This software is not
for clinical use.
