# Tazama

*Tazama tena*: "look again". A second look for the waiting room.

A human-supervised agentic clinical triage research prototype for the Agentic AI for Africa Healthcare Challenge.

## Architecture principles

- LangGraph coordinates an explicit, auditable workflow.
- MCP exposes versioned tools with typed contracts.
- Clinical triage scoring is deterministic and protocol-driven.
- The local LLM explains evidence but cannot assign clinical priority.
- Queue updates require explicit clinician approval.
- All demonstration cases use synthetic data.

## Safety status

The clinical scoring engine has not yet been validated or integrated.

**Not for clinical use. Do not enter real patient information.**

## Local development

Python 3.12 and uv are required.

Install dependencies:

```bash
uv sync
```

Run tests:

```bash
uv run pytest
```

## Read-only API

The API exposes persisted synthetic observations without scoring, interpretation, workflow
execution, or database writes:

```text
GET /api/v1/health
GET /api/v1/cases/{case_id}/observations
```

Configure the same existing SQLite file used by the backend, then start the service:

```bash
export TAZAMA_DB_PATH=/absolute/path/to/tazama.sqlite3
uv run uvicorn tazama.api.app:app --reload
```

The service does not initialize or migrate the database. A missing configuration, missing file,
invalid SQLite file, or database without the observations schema returns HTTP 503. A valid case
with no persisted observations returns HTTP 404.

The observation response contains the case ID and chronological `ObservationRecord` values,
including timestamps and structured measurements. It contains no demographics, computed
priority, diagnosis, or inferred clinical status.

For local Next.js development, set the dashboard's server-side API base URL to
`http://127.0.0.1:8000` and request
`/api/v1/cases/<encoded-case-id>/observations`. Handle 404 as “no observations recorded” and 503
as backend configuration/storage unavailable. Browser CORS is intentionally not enabled; use a
Next.js server component or same-origin proxy. No authentication is implemented, so the service
must only be used with synthetic data in a trusted development environment.

## Licensing

This repository contains two separately licensed works.

| Part | Licence |
| --- | --- |
| Source code (`src/`, `tests/`) | Apache-2.0 |
| SATS protocol data (`data/protocol/`) | CC BY-NC-SA 3.0 |

The clinical thresholds are not written in the code or in any prompt. They are read at run time
from a data file under `data/protocol/`.

That data file is transcribed by hand from the Adult SATS Chart published by the Emergency
Medicine Society of South Africa (EMSSA). The chart is licensed CC BY-NC-SA 3.0, which is not an
OSI-approved licence, so the data file is kept apart from the code and keeps its own licence.

- Source: Adult SATS Chart (Adult-SATS-2015.pdf), EMSSA.
- Licence: https://creativecommons.org/licenses/by-nc-sa/3.0/
- Changes: values transcribed into JSON; parameter names adapted to the Tazama contract. No
  thresholds were altered.
- The data file is for non-commercial use and any adaptation must be shared under the same licence.
