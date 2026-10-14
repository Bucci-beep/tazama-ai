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
