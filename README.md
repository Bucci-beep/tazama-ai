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

Prerequisites:

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Node.js 20 or newer with npm

Install the pinned Python dependencies once:


```bash
uv sync
```

Then start the FastAPI backend and Next.js dashboard together with one command:

```bash
uv run python -m tazama.local_dev
```

The launcher creates or updates the schema at `.local/tazama.sqlite3`, which is excluded from Git.
Initialization is idempotent: existing observations, reviews, audit records, and other database
contents are preserved and no scenarios are seeded. If `web/node_modules` is absent, the launcher
runs `npm ci` using the committed lockfile.

When both readiness checks pass, open:

- Dashboard: <http://127.0.0.1:3000>
- FastAPI: <http://127.0.0.1:8000>
- Health check: <http://127.0.0.1:8000/api/v1/health>

Press Ctrl+C once to stop both services. Termination signals are forwarded to both child process
groups, with a bounded forced shutdown if a child does not exit. The launcher never kills a process
already using port 3000 or 8000; it fails before startup and asks you to free the occupied port.

Ollama is optional. Deterministic reassessment works without it and reports explanations as
unavailable. To use the existing bounded explanation selector, start Ollama separately and set a
model already installed on your machine before launching; no model is downloaded automatically:

```bash
TAZAMA_OLLAMA_MODEL=llama3.2:3b uv run python -m tazama.local_dev
```

Troubleshooting:

- Missing `uv` or Python packages: install uv, then run `uv sync`.
- Missing Node/npm: install Node.js 20 or newer, then retry.
- Frontend dependency failure: run `cd web && npm ci` and review npm's output.
- Port 3000 or 8000 occupied: stop the service using that port; the launcher will not terminate it.
- Startup timeout or child exit: review the backend/frontend output printed in the same terminal.
  Set `TAZAMA_STARTUP_TIMEOUT` to a larger number of seconds on slower machines.

This environment is for synthetic data and software research only. It is not clinically validated
or authorised for patient care.

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
POST /api/v1/cases/{case_id}/reassess
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

After loading a persisted case, the dashboard provides an explicit **Request reassessment** action.
It calls the FastAPI reassessment endpoint through a Next.js server action, sends only the case ID,
and displays deterministic evidence, limitations, pending-review confirmation, provenance, and MCP
audit warnings. Saving an observation never triggers reassessment automatically. Start the frontend
with `cd web && npm run dev`; use `npm run lint`, `npm run typecheck`, `npm test`, and `npm run build`
for frontend verification.

### Reassessment API

`POST /api/v1/cases/{case_id}/reassess` runs the existing LangGraph/MCP workflow over
already-persisted synthetic observations. It does not accept observation data, modify the
timeline, approve a review, or change a queue. A case with no observations returns 404 before
any MCP call or review submission.

Example response (fields abbreviated):

```json
{
  "case_id": "SYNTHETIC-DEMO-001",
  "workflow_run_id": "7ce3fd2d-7af3-4a84-a0aa-0b462253463e",
  "status": "awaiting_clinician_review",
  "observation_count": 2,
  "latest_observation_id": "SYNTHETIC-OBS-002",
  "comparison_status": "differences_found",
  "comparison_result": {"status": "differences_found", "changes": []},
  "comparison_error": null,
  "priority_status": "minimum_only",
  "priority_result": {"priority": null, "priority_at_least": "routine"},
  "priority_error": null,
  "explanation": null,
  "explanation_error": "NOT_CONFIGURED",
  "review_request_id": "review-uuid",
  "review_submission_status": "persisted",
  "review_submission_error": null,
  "workflow_provenance": {"time": {"status": "captured"}},
  "mcp_audit_errors": []
}
```

The result is a deterministic proposal awaiting clinician review, not a validated clinical
decision. Set `TAZAMA_OLLAMA_MODEL` to opt into the existing bounded local explanation selector;
if it is absent or unavailable, deterministic reassessment continues with an explicit explanation
error. Use `workflow_run_id` with `MCPToolCallRepository.get_by_workflow_run()` to inspect the
corresponding MCP audit trail. Any missing audit records are listed in `mcp_audit_errors`.

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
If SQLite cannot accept a record, the workflow preserves a completed MCP result but exposes the
affected tool under `mcp_audit_errors`; it does not claim that the missing record was persisted.

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
