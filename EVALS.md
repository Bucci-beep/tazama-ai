# Evaluations

These evaluations cover the **deterministic triage layer**: the TEWS scorer, the sign lists and
the priority combiner. All cases are synthetic. They check that the code follows the rules
printed on the Adult SATS chart, and that it abstains when it cannot. They are not a clinical
validation, and they do not measure real-world accuracy.

Run them with:

```bash
uv run pytest tests/evals tests/test_applicability_gate.py -v
```

## Method

- Expected outcomes were written from the chart rules before the code was run.
- Each case gives vital signs and the signs a nurse has ticked, and states the expected status
  and priority.
- Every case also checks one safety invariant: a result that is not "complete" never carries a
  final priority.
- The cases E01 to F01 run with the nurse having confirmed that the adult chart applies
  (`adult_chart_applies = yes`), so that they test the chart itself. Applicability is tested
  separately, below.

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

## Applicability gate

The adult chart is used only when a nurse confirms that it applies to the patient. Tazama never
infers this. Anything other than an explicit "yes" makes scoring abstain. These cases are in
`tests/test_applicability_gate.py`. Their expected results were written from the clinical design
before the gate was implemented.

| ID | Case | Expected |
| --- | --- | --- |
| D | Applicability not assessed, otherwise scorable vitals | abstain: no TEWS total, no priority, no minimum |
| E | Nurse recorded that the adult chart does not apply | abstain, same as D |
| F | Record stored before the field existed | treated as not assessed: abstain, and the stored record is not rewritten |
| G | Emergency sign identified, applicability not confirmed (also with "no") | abstain: no priority and no minimum, even for an emergency sign |
| H | Earlier reading confirmed, latest reading not assessed | the latest reading abstains |
| H, reverse | Earlier reading not assessed, latest reading confirmed | the latest reading is scored normally |

Checks on every blocked case:
- The TEWS result has no total and no parameter scores, and says why.
- The reason says that human clinical assessment is required and that the result is not a routine
  or low-risk one.
- The reason tells the nurse that if an emergency sign or any immediate danger is present, they
  should not wait for Tazama and should escalate under their local emergency protocol.

The same tests also check the validation warning, the scoring tool and the priority tool. The
suite also exercises the actual reassessment API endpoint and workflow with injected test tools,
so that neither first triage nor a reassessment can bypass the gate. Real MCP stdio integration
is tested separately.

## Results

| Suite | Total | Pass | Expected failure |
| --- | --- | --- | --- |
| Triage cases (E01 to E14, F01) | 15 | 14 | 1 (F01) |
| Applicability gate | 26 | 26 | 0 |

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

- The bounded Ollama explanation-selection task is covered by contract tests, but model quality,
  runtime availability and run-to-run behavior are not clinical validation.
- Real patients, real clinical accuracy, or any claim of efficacy.
- Slow drift inside a single TEWS band (for example heart rate rising from 60 to 98, which
  stays at score 0). History comparison reports the difference, but nothing raises a flag.
- Whether a nurse ticks the right signs.
- Whether a nurse's applicability answer is right. Tazama does not check the patient's age or
  height.
- Plausibility of values beyond structure (type, finite numbers, allowed values). No clinical
  reference ranges are applied; any would need clinical sign-off before they were added.