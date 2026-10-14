# Evaluations

These evaluations cover the **deterministic triage layer**: the TEWS scorer, the sign lists and
the priority combiner. All cases are synthetic. They check that the code follows the rules
printed on the Adult SATS chart, and that it abstains when it cannot. They are not a clinical
validation, and they do not measure real-world accuracy.

Run them with:

```bash
uv run pytest tests/evals -v
```

## Method

- Expected outcomes were written from the chart rules before the code was run.
- Each case gives vital signs and the signs a nurse has ticked, and states the expected status
  and priority.
- Every case also checks one safety invariant: a result that is not "complete" never carries a
  final priority.

Statuses: `complete` (a final priority), `minimum_only` ("at least X", no final priority) and
`abstained` (nothing usable).

## Cases

| ID | Case | Expected |
| --- | --- | --- |
| E01 | Normal vitals, no signs | routine |
| E02 | Emergency sign, no vitals taken | emergency |
| E03 | Chest pain ticked, normal vitals | very urgent |
| E04 | Moderate pain ticked, normal vitals | urgent |
| E05 | TEWS 3, no signs | urgent |
| E06 | TEWS 5, no signs | very urgent |
| E07 | TEWS 7, no signs | emergency |
| E08 | Urgent sign but TEWS 5 | very urgent (higher band wins) |
| E09 | Heart rate missing | abstain (not imputed) |
| E10 | Respiratory rate 14.5, between chart bands | abstain |
| E11 | Unknown sign id | abstain |
| E12 | Signs not assessed yet | minimum only (routine), no final priority |
| E13 | Temperature 38.4 (in band), RR 15 | routine |
| E14 | Temperature 38.5 (over band), RR 15 | urgent |
| F01 | Chest pain present but the nurse did not tick it | see below |

## Results

| Total | Pass | Expected failure |
| --- | --- | --- |
| 15 | 14 | 1 (F01) |

## Unfixed failure: F01, an omitted sign is not detected

**What happens.** A patient has chest pain, which the chart lists as a very urgent sign, and
normal vital signs. The nurse does not tick "Chest pain". Tazama sees no signs and normal
vitals, and returns **routine**. The correct priority is **very urgent**.

**Why it happens.** Tazama only combines signs a nurse identifies. It does not detect signs.
It cannot notice one that nobody entered.

**Why we have not fixed it.** The only fix is to let the language model read the nurse's
free-text complaint and infer the signs. That would break the rule that the model never assigns
clinical priority, and it would need real clinical validation first. We chose to keep the
safety rule and document the gap.

**What reduces the risk today.**
- Until a nurse confirms the sign check, Tazama gives "priority at least X" and never a final
  priority (case E12).
- The result lists exactly which signs it used, so a reviewer can see what was and was not
  considered.
- The nurse approves every outcome. Tazama does not move the queue by itself.

**How it is tracked.** F01 is marked as an expected failure in the test suite. The suite stays
green and the failure stays visible. If someone makes it pass, the suite fails, so the change
cannot go unnoticed.

**What a safe fix could look like.** Ask the nurse about each high-risk sign one by one, with a
clinician reviewing the design. It should not be a model guessing from text.

## Not covered

- The language-model agent: tool choice, recovery from bad data and run-to-run variation. These
  need the agent loop and are not measured here.
- Real patients, real clinical accuracy, or any claim of efficacy.
- Slow drift inside a single TEWS band (for example heart rate rising from 60 to 98, which
  stays at score 0). History comparison reports the difference, but nothing raises a flag.
- Whether a nurse ticks the right signs.