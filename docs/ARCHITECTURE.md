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
- Verified SATS protocol not yet integrated
- Returns an explicit unavailable result
- Never assigns a clinical priority
- Directs the case toward human clinical assessment

### MCP integration

- MCP SDK 1.x
- stdio transport
- Local subprocess communication
- Two registered tools:
  - validate_observations
  - calculate_sats

### Testing

- Unit tests
- Clinical safety boundary tests
- Real MCP client/server integration tests

## Planned components

### Review workflow

- submit_review_request MCP tool
- Persistent review requests
- Idempotency protection
- Audit events
- Explicit human approval boundary

### LangGraph orchestration

- Typed workflow state
- Conditional routing
- Controlled MCP tool invocation
- Human-in-the-loop interruption and resumption

### Local LLM

- Ollama
- Local model for explanations
- No independent clinical scoring authority

### Evidence and evaluation

- Verified SATS protocol and provenance
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
