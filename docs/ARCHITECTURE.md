# Tazama: Architecture

Tazama ("a second look for the waiting room") is a research prototype for
human-supervised clinical triage workflow support. It re-checks waiting patients'
observations, proposes a priority, and asks a nurse to review it.

The prototype uses synthetic patient data only. It is not clinically validated and
must not be used to make real patient care decisions.

## Core principles

1. Deterministic code owns every clinical rule. No thresholds appear in prompts or in
   the language model.
2. The language model never assigns a priority, diagnoses, prescribes or moves a queue.
3. Missing or off-chart observations are never imputed. The system reports "at least X"
   or abstains.
4. A proposal is only a proposal. Nothing is approved, and no queue changes, without a
   named clinician's decision.
5. Every consequential workflow transition is recorded in an append-only audit trail.
6. Inference runs locally on an open-weights model. No patient data leaves the machine.

## System overview

    Synthetic observations (SQLite)
              |
              v
    LangGraph workflow (open-source orchestration)
      validate_input -> capture_time_context -> load_and_compare -> assess_priority
        -> explain_evidence -> submit_review -> await_clinician_review
              |                    |                       |
              | borrowed MCP       | Tazama MCP (stdio)    | local model
              v                    v                       v
    Official Time MCP       deterministic tools     bounded Ollama task
    (UTC provenance only)
              |
              v
    SQLite: review requests, evidence, append-only audit and attestations
              |
              v
    Read-only FastAPI  ->  Next.js dashboard (read-only)

The workflow stops at `await_clinician_review`. The model is given no tools and no
approval authority.

## Components

### Clinical core (`src/tazama/clinical/`)
- `tews.py` scores the Triage Early Warning Score from protocol data.
- `scoring.py` returns either a scored result or an explicit "unavailable" result.
- `priority.py` combines the TEWS band with nurse-assessed discriminator signs.
- `history.py` compares a new reading with earlier ones.
- Protocol data lives in `data/protocol/` (SATS adult chart, version `2015-chart-1`).
  It is attributed and licensed CC BY-NC-SA 3.0. The code is Apache-2.0.

### Signs and results
- `signs=None` means the nurse has not assessed signs. `[]` means assessed, none found.
- Result statuses: `complete`, `minimum_only` ("at least X", signs not assessed) and
  `abstained` (missing or off-chart data).
- An off-chart or missing value never produces a lower priority by default.

### MCP server (`src/tazama/mcp/`)
FastMCP (SDK 1.x) over stdio. Custom tools:

| Tool | Kind | Purpose |
| --- | --- | --- |
| `validate_observations` | read | Reports missing fields. No clinical readiness verdict. |
| `calculate_sats` | read | Deterministic TEWS. Abstains rather than guessing. |
| `compare_with_history` | read | Compares readings. Unavailable history is never reassuring. |
| `determine_priority` | read | Deterministic priority proposal from TEWS and signs. |
| `submit_review_request` | **action** | Persists a pending review request with its evidence. Idempotent. Only "pending". |
| `record_demo_attestation` | **action, gated** | Registered only when `TAZAMA_ENABLE_DEMO_ATTESTATION=1`. Demo only. |

### Borrowed MCP server (`mcp-server-time`)
- Official third-party server from the Model Context Protocol project, pinned to
  `2026.10.10` and called over stdio.
- `get_current_time` is called with `UTC` after successful workflow input validation.
- Successful output or explicit tool failure is stored under `workflow_provenance` in
  review evidence.
- Provenance is nonclinical and excluded from the deterministic idempotency fingerprint.
  A different timestamp on retry preserves the first pending review and its evidence.
- The call has a bounded timeout and failure is nonblocking. It never supplies observation
  timestamps, deadlines, scores or priorities.
- The maintained server is preferred to a local clock wrapper for its reusable MCP contract,
  IANA timezone validation and independent interoperability.

### Orchestration (`src/tazama/orchestration/`)
LangGraph with typed state and conditional routing. MCP failures are treated as
"evidence unavailable", never as a negative clinical finding. Retrying the workflow does
not create a duplicate review request.

### Local model (`orchestration/explanation.py`)
- Ollama with an open-weights model (default `llama3.2:3b`, set by
  `TAZAMA_OLLAMA_MODEL`).
- The model receives the deterministic evidence and a fixed set of pre-approved
  explanation statements, and returns only the IDs of the ones that apply.
- Output is validated. IDs outside the set are rejected. The model writes no free text
  that reaches the nurse.
- If the model fails or is unavailable, the deterministic evidence is unchanged and the
  review request is still created.

### Storage and audit (`src/tazama/storage/`, `src/tazama/audit/`)
- SQLite stores observations, recheck schedules, review requests with their
  deterministic evidence, and audit events.
- Audit events and attestations are append-only, enforced by database triggers.
- Review requests are created as "pending" only.
- `mcp_tool_calls` is a separate append-only audit table. It records one completed row per MCP
  invocation: UUID invocation ID, workflow run ID, MCP server identity, tool name, UTC start and
  completion timestamps, sanitised input JSON, sanitised output JSON or structured error JSON,
  status (`success`, `tool_error`, `validation_error`, or `transport_error`), and duration in
  milliseconds. Secret-like keys are redacted before persistence.
- `MCPToolCallRepository.get_by_workflow_run()` returns a run's calls ordered by start time and
  invocation ID. Logging remains local; it neither changes deterministic evidence nor sends
  clinical information to an observability service.
- An audit-write failure is distinct from MCP execution. Successful validated tool results remain
  usable and the workflow exposes `mcp_audit_errors`; failed MCP calls remain failures and are
  annotated when their error record could not be persisted.

### Approval gate
- A clinician decision is a separate, explicit action from proposing a priority.
- In this prototype the decision is a demo attestation with an asserted identity
  (`asserted_demo_identity`). It is not authentication. It never changes a priority or a
  queue.
- The synthetic demo records its attestation as `DEMO-CLINICIAN-001`, labelled as
  simulated.
- Real approval stays blocked on authentication, authorisation, clinical governance and
  clinical validation.

### Synthetic API (`src/tazama/api/`)
FastAPI over the configured local SQLite database:
- `GET /api/v1/health`
- `GET /api/v1/cases/{case_id}/observations` (404 if none, 503 if the database is
  misconfigured)
- `POST /api/v1/cases/{case_id}/observations` persists synthetic observations without scoring.
- `POST /api/v1/cases/{case_id}/reassess` preflights the persisted timeline, then invokes the
  existing LangGraph workflow. Its typed response includes deterministic evidence, tool errors,
  pending review state, nonclinical provenance, and MCP audit coverage errors. The workflow run ID
  correlates the response with `mcp_tool_calls` rows. The endpoint cannot approve reviews or change
  clinical priority or queue state.

### Dashboard (`web/`)
Next.js, read-only. It shows persisted observations, backend status and a safety notice.
It has no approve, edit or queue controls.

## Evidence and evaluation
- `EVALS.md` and `tests/evals/` hold 14 passing cases and one documented unfixed failure
  (F01: a sign the nurse omits is not detected). It is left unfixed on purpose, because
  fixing it would need the model to infer signs and so to influence priority.
- Safety-boundary tests check that scoring never invents a priority.
- Integration tests run a real MCP client against the real server over stdio.

## Known gaps
- The API does not yet expose pending review requests or a review's stored evidence, so
  the dashboard shows observations only.
- The default demo case has no nurse-assessed signs, so its priority is "at least
  routine" rather than a complete proposal.
- The model's task is deliberately narrow (selecting among pre-approved statements).
- Approval is a demo attestation only.

## Deployment restrictions
This is a research demonstration. No real patient information may be entered. No
production clinical deployment is authorised.
