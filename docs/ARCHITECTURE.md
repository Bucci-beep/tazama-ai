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
      validate_input -> load_and_compare -> assess_priority
        -> explain_evidence -> submit_review -> await_clinician_review
              |                       |
              | MCP (stdio)           | local model (Ollama)
              v                       v
    Tazama MCP server          selects pre-approved explanation IDs only
    (deterministic tools)
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

### Approval gate
- A clinician decision is a separate, explicit action from proposing a priority.
- In this prototype the decision is a demo attestation with an asserted identity
  (`asserted_demo_identity`). It is not authentication. It never changes a priority or a
  queue.
- The synthetic demo records its attestation as `DEMO-CLINICIAN-001`, labelled as
  simulated.
- Real approval stays blocked on authentication, authorisation, clinical governance and
  clinical validation.

### Read-only API (`src/tazama/api/`)
FastAPI, GET only, on a read-only database connection:
- `GET /api/v1/health`
- `GET /api/v1/cases/{case_id}/observations` (404 if none, 503 if the database is
  misconfigured)

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
- No third-party ("borrowed") MCP server is wired in yet.
- The API does not yet expose pending review requests or a review's stored evidence, so
  the dashboard shows observations only.
- The default demo case has no nurse-assessed signs, so its priority is "at least
  routine" rather than a complete proposal.
- The model's task is deliberately narrow (selecting among pre-approved statements).
- Approval is a demo attestation only.

## Deployment restrictions
This is a research demonstration. No real patient information may be entered. No
production clinical deployment is authorised.