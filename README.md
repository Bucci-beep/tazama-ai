
# Tazama

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

## Team responsibilities

- Denis: LangGraph, MCP, local LLM, audit and clinician review workflow.
- Daud: clinical evidence, SATS specification, scoring verification and evaluation cases.
