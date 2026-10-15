# Tazama

*Tazama tena*: "look again". A second look for the waiting room.

A human-supervised agentic clinical triage research prototype for the Agentic AI for Africa Healthcare Challenge.

## Architecture principles

- LangGraph coordinates an explicit, auditable workflow.
- MCP exposes versioned tools with typed contracts.
- The official `mcp-server-time` package supplies UTC workflow provenance over MCP.
- Clinical triage scoring is deterministic and protocol-driven.
- An optional local Ollama task selects from pre-approved evidence explanations; it cannot
  generate clinical claims or assign priority.
- A demonstration-only attestation records an asserted clinician identifier and disposition.
  It is not authentication, authorisation, or production clinical sign-off, and it does not
  update a queue or priority.
- All demonstration cases use synthetic data.

## Safety status

The deterministic scoring engine is integrated into the MCP/LangGraph review workflow but has
not been clinically validated.

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

## Observation API

The API retrieves and records persisted synthetic observations without scoring,
interpretation, or workflow execution:

```text
GET /api/v1/health
GET /api/v1/cases/{case_id}/observations
POST /api/v1/cases/{case_id}/observations
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
including timestamps and structured measurements. A POSTed `baseline` creates the synthetic
case timeline; later `recheck` observations must have strictly increasing timestamps. Saving an
observation does not run scoring or analysis. Responses contain no demographics, computed
priority, diagnosis, or inferred clinical status.

For local Next.js development, set the dashboard's server-side API base URL to
`http://127.0.0.1:8000` and request
`/api/v1/cases/<encoded-case-id>/observations`. Handle 404 as “no observations recorded” and 503
as backend configuration/storage unavailable. Browser CORS is intentionally not enabled; use a
Next.js server component or same-origin proxy. No authentication is implemented, so the service
must only be used with synthetic data in a trusted development environment.

## Synthetic demonstration

Run the synthetic demonstration (requires a running Ollama service and the configured model,
default `llama3.2:3b`):

```bash
uv run python -m tazama.demo
```

The demo uses synthetic data, leaves the review pending, records a demo identity attestation,
and never changes clinical priority.

## MCP tool-call audit

Every MCP invocation in the workflow is recorded locally in the append-only SQLite
`mcp_tool_calls` table. Each row contains an invocation ID, workflow run ID, server and tool,
UTC start/completion times, sanitised JSON input and output (or structured error), status, and
duration in milliseconds. Secret-like fields are redacted; no external logging service is used.

Application code can inspect a run in chronological order with
`MCPToolCallRepository(database).get_by_workflow_run(workflow_run_id)`. For a local demo database,
the equivalent direct query is:

```sql
SELECT * FROM mcp_tool_calls
WHERE workflow_run_id = 'RUN-ID'
ORDER BY started_at, invocation_id;
```

## Borrowed MCP server

Tazama calls the official Time MCP server's `get_current_time` tool over stdio with the
timezone fixed to UTC. The result, or an explicit unavailable status, is stored only as
workflow provenance in review evidence. It cannot affect observation chronology,
reassessment timing, clinical scoring or priority, and failure does not block review.

The server is pinned as `mcp-server-time==2026.10.10`. Using the maintained official server
beats writing a local clock wrapper because it provides a reusable MCP contract, validated IANA
timezone handling and independent protocol interoperability.

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
