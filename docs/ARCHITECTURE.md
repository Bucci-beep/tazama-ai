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
4. The adult chart is used only when a nurse has confirmed that it applies. Tazama never
   infers this. Otherwise it abstains, and tells the nurse not to wait for it.
5. A proposal is only a proposal. Nothing is approved, and no queue changes, without a
   named clinician's decision.
6. Every consequential workflow transition is recorded in an append-only audit trail.
7. Inference runs locally on an open-weights model. No patient data leaves the machine.

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
    FastAPI (synthetic data, no approval endpoints)  ->  Next.js dashboard

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

### Adult chart applicability
- Each observation carries `adult_chart_applies`: `yes`, `no` or `not_assessed`. Only a
  nurse sets it. Tazama never infers it from vital signs or notes. The dashboard selector
  has no preselected option, and an omitted value is `not_assessed`.
- Anything other than an explicit `yes` makes scoring abstain: no TEWS total, no
  priority and no "at least" minimum. This holds even if the nurse identified an
  emergency sign, because the adult chart and its sign lists may not suit the patient.
- The gate sits in `score_tews` and `determine_priority`, so it covers initial triage,
  reassessment and direct calls to the MCP tools. The latest observation decides: a later
  `yes` allows scoring again, and a later `not_assessed` stops it.
- Records stored before this field existed load as `not_assessed` and abstain. Nothing is
  rewritten in the database.
- The abstention reason says that human clinical assessment is required, that the result
  is not a routine or low-risk one, and that if an emergency sign or any immediate danger
  is present the nurse should not wait for Tazama and should escalate under the local
  emergency protocol. No priority is assigned.
- Plausibility checks are structural only (type, finite numbers, allowed values). No
  clinical range limits exist in code. If a clinical reviewer approves any, they belong in
  the protocol data, not in code.

### Signs and results
- `signs=None` means the nurse has not assessed signs. `[]` means assessed, none found.
- Result statuses: `complete`, `minimum_only` ("at least X", signs not assessed) and
  `abstained` (missing or off-chart data, or adult-chart applicability not confirmed).
- An off-chart or missing value never produces a lower priority by default.

### MCP server (`src/tazama/mcp/`)
FastMCP (SDK 1.x) over stdio. Custom tools:

| Tool | Kind | Purpose |
| --- | --- | --- |
| `validate_observations` | read | Reports missing fields and warns when adult-chart applicability is unconfirmed. No clinical readiness verdict. |
| `calculate_sats` | read | Deterministic TEWS. Abstains rather than guessing, including when applicability is unconfirmed. |
| `compare_with_history` | read | Compares readings. Unavailable history is never reassuring. |
| `determine_priority` | read | Deterministic priority proposal from TEWS and signs. Abstains when applicability is unconfirmed. |
| `submit_review_request` | **action** | Persists a pending review request with its evidence. Idempotent for unchanged evidence; changed evidence creates a new revision. Only "pending". |
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

- **Snapshot.** The workflow scores one snapshot of the latest observation. The review
  write is a compare-and-swap on the current review, so a stale or concurrent write is
  rejected instead of being silently mixed.
- **Deadlines.** Every MCP call has a deadline (`TAZAMA_MCP_TIMEOUT_SECONDS`, default 15).
  The explanation call has its own (`TAZAMA_OLLAMA_TIMEOUT_SECONDS`, default 30). A value
  that is invalid, not positive or not finite falls back to the default. A stalled model
  cannot delay the review.
- **Unconfirmed review submission.** If submitting a review times out, the workflow checks
  what was actually stored. It reports `persisted` only if the stored review matches the
  evidence. Otherwise it reports `unconfirmed`.

### Local model (`orchestration/explanation.py`)
- Ollama with an open-weights model (default `llama3.2:3b`, set by
  `TAZAMA_OLLAMA_MODEL`).
- The model receives the deterministic evidence and a fixed set of pre-approved
  explanation statements, and returns only the IDs of the ones that apply.
- Output is validated. IDs outside the set are rejected. The model writes no free text
  that reaches the nurse.
- If the model fails, times out or is unavailable, the deterministic evidence is
  unchanged and the review request is still created.

### Storage and audit (`src/tazama/storage/`, `src/tazama/audit/`)
- SQLite stores observations, recheck obligations, review requests with their
  deterministic evidence, and audit events.
- Audit events and attestations are append-only, enforced by database triggers.
- Review requests are created as "pending" only.
- Reviews are immutable revisions. If the same observation is reviewed again with changed
  evidence, a new row is written with the next revision number and a pointer to the one it
  supersedes. The earlier row is never edited. Unchanged evidence returns the existing
  review.
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
- `GET /api/v1/reassessments/due` lists stored reassessment obligations whose due time has
  passed. It is read-only and does not run the clinical workflow.

### Dashboard (`web/`)
Next.js. It lets a user record synthetic observations (including the nurse's adult-chart
applicability and assessed signs), request a reassessment, and view persisted timelines,
evidence, due reassessments and backend status, with a safety notice. It has no approve,
edit-priority or queue controls.

## Evidence and evaluation
- `EVALS.md` and `tests/evals/` hold 14 passing cases and one documented unfixed failure
  (F01: a sign the nurse omits is not detected). It is left unfixed on purpose, because
  fixing it would need the model to infer signs and so to influence priority. Those cases
  run with the nurse having confirmed that the adult chart applies.
- `data/demo/synthetic_cases_v1.json` holds three locked synthetic cases, tested in
  `tests/test_synthetic_demo_cases.py` against the real scoring and comparison code:
  A (stable: routine), B (observations changed: very urgent) and C (missing and off-chart
  data: abstains).
- `tests/test_applicability_gate.py` covers the applicability gate: unconfirmed and "no"
  abstain (including with an emergency sign), records stored without the field abstain, the
  latest observation decides in both directions, and the abstention text tells the nurse
  to escalate. It also runs through the real API and workflow.
- Safety-boundary tests check that scoring never invents a priority.
- Integration tests run a real MCP client against the real server over stdio.

## Known gaps
- Applicability is the nurse's judgement. Tazama does not check age or height, and the
  adult chart's age and height criteria are not encoded.
- Plausibility checks are structural only. No clinical reference ranges are applied; any
  would need clinical sign-off before they were added.
- Protocol data is transcribed from the published Adult SATS chart and was checked against
  it by the authors.
- The API has no endpoint that lists pending review requests; evidence is returned by the
  reassess response.
- Tazama does not decide when a patient is due for reassessment. Reassessment obligations
  store an explicit due time and policy reference given to them, and the API only lists
  those past due. No workflow step creates them yet, and no intervals are invented.
- Time is captured as provenance only.
- The model's task is deliberately narrow (selecting among pre-approved statements).
- Approval is a demo attestation only.
- F01 (see above) is a documented, unfixed limitation.

## Deployment restrictions
This is a research demonstration. No real patient information may be entered. No
production clinical deployment is authorised.