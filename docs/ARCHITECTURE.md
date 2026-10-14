# Tazama — Architecture

## Project status

Tazama is a research prototype for human-supervised
clinical triage workflow support.

The prototype uses synthetic patient data only.

It is not clinically validated and must not be used to make
real patient care decisions.

## Core architectural principles

1. Deterministic components own clinical decision logic.
2. LLMs cannot assign clinical triage priorities.
3. Missing observations must not be fabricated or imputed.
4. Unavailable clinical scoring requires human assessment.
5. Clinical decisions and queue updates require independent
   authorisation.
6. All consequential workflow transitions must be auditable.

## Current implementation

### Observation validation

- Pydantic request and response contracts
- Versioned schemas
- Missing observation reporting
- No clinical readiness determination

### SATS scoring boundary

- Deterministic scoring interface
- Protocol-driven TEWS and priority calculation through MCP
- Nurse-assessed signs are explicit input; `None` means not assessed
- Returns `minimum_only` or abstains when evidence is incomplete
- Produces a proposal for review and never changes a clinical priority

### MCP integration

- MCP SDK 1.x
- stdio transport
- Local subprocess communication
- Registered tools:
  - validate_observations
  - calculate_sats
  - compare_with_history
  - determine_priority
  - submit_review_request
  - record_demo_attestation

### Testing

- Unit tests
- Clinical safety boundary tests
- Real MCP client/server integration tests

### Review workflow

- submit_review_request MCP tool
- Persistent review requests
- Idempotency protection
- Audit events
- Append-only, demo-only attestation with an asserted identity
- No authenticated approval or queue mutation

### LangGraph orchestration

- Typed workflow state
- Conditional routing
- Controlled MCP tool invocation
- Calls history comparison and deterministic priority tools before persisting review evidence
- Treats MCP failures as unavailable evidence, never as a negative clinical finding

### Local LLM

- Ollama
- Optional local model selects relevant statements from a fixed, pre-approved explanation set
- Structured output is validated and selections outside the grounded set are rejected
- Model failure does not alter deterministic evidence or prevent human review
- The synthetic command uses `llama3.2:3b` by default; runtime/model availability is external

### Evidence and evaluation

- Protocol data and provenance
- Synthetic clinical scenarios
- Safety and failure-mode evaluation
- Human review of clinical assumptions

## Team responsibilities

### Denis

- System architecture
- MCP tool implementation
- LangGraph orchestration
- Local LLM integration
- Review and audit workflow

### Daud

- Clinical evidence analysis
- SATS protocol verification
- Synthetic dataset design
- Evaluation methodology
- Statistical analysis

## Deployment restrictions

This implementation is a research demonstration.

No real patient information may be entered into the prototype.

No production clinical deployment is authorised.

The demo clinician identifier is asserted input only. Real-world approval remains blocked on
authentication, authorisation, clinical governance, and clinical validation.
