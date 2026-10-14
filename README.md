# Tazama

*Tazama tena*: "look again". A second look for the waiting room.

A human-supervised agentic clinical triage research prototype for the Agentic AI for Africa Healthcare Challenge.

## Architecture principles

- LangGraph coordinates an explicit, auditable workflow.
- MCP exposes versioned tools with typed contracts.
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

Run the synthetic demonstration (requires a running Ollama service and the configured model,
default `llama3.2:3b`):

```bash
uv run python -m tazama.demo
```

The demo uses synthetic data, leaves the review pending, records a demo identity attestation,
and never changes clinical priority.

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
