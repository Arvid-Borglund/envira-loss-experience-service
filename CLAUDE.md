# CLAUDE.md: working instructions for the Envira loss-experience case

Repository-specific instructions used with Claude Code during the two-hour case. Included in the submission as the brief asks. No private or employer configuration lives here.

## What we are building

Read `docs/BRIEF.md` first. It is the specification, and its definitions are binding:

- Incurred loss: settled claims cost what was paid; open claims cost paid plus reserved; declined and withdrawn claims cost nothing.
- Earned premium: the full annual premium, no pro-rata.
- Loss ratio: incurred loss divided by earned premium, both in DKK.
- Underwriting year: the calendar year of the policy's inception date.
- A claim belongs to a policy. Where the data makes that ambiguous or impossible, the chosen policy is stated in DECISIONS.md.
- Currency: every amount is converted to DKK with the month-end rate of the month chosen for it (premium: inception month; claim: loss month). A missing rate is never zero: the row is excluded and counted.

Priority: a correct, runnable single-portfolio endpoint first. Then the data-quality report, the comparison across portfolios, tests, README and Dockerfile. Other backlog items only if they add clear value in the remaining time.

## Stack

- Python 3.12 managed by uv (`uv sync`, `uv run`).
- FastAPI and uvicorn for the API, pandas for loading and aggregation, pytest for tests.
- One package `lossexp/` with clear boundaries: `data.py` (load, clean, quality counts), `fx.py` (currency conversion), `metrics.py` (incurred loss, earned premium, loss ratio per group), `service.py` (join layer shared by the API and any CLI), `api.py` (FastAPI app).
- Everything precomputed in memory at startup. No database: the volumes are small and the brief does not score performance.
- Started from the scaffold of a previous two-hour case (pyproject, this file's layout, Dockerfile, CI workflow, test layout). DECISIONS.md says so.

## Data handling rules

- Treat the CSVs as source data. Profile before implementing: key uniqueness, referential integrity (claim to policy to asset to portfolio), value ranges and impossible values, date order, currency coverage in the FX table.
- Every exclusion rule is explicit, applied in one place (`data.py`), counted, logged at startup and exposed by the data-quality endpoint. Nothing is dropped silently and nothing is duplicated silently.
- Never let load order silently decide between conflicting rows.
- Business definitions and constants live in `metrics.py` and are passed through, never repeated in other layers.

## Verification rules

- Establish that a number is right independently of the implementation: a script that recomputes the loss experience for a few portfolios with plain csv and Decimal, no pandas, diffed against the API.
- Tests on the business logic with hand-built inputs: status to incurred mapping, FX month selection and a missing rate, a claim outside its policy term, duplicate and orphan rows, a loss ratio with zero premium.
- Plausibility checks: EUR converts at about 7.46, loss ratios land in a commercially sane range, the largest claim is compared with the sum insured.
- Run the tests and call the endpoint before claiming something works.

## Working method

- Commit small and often, with messages that say why.
- Keep the implementation small. Reject generated code that adds abstraction, configuration or features the brief did not ask for.
- Record every assumption in DECISIONS.md as it is made, not at the end.
- Time-box: check the clock at 30, 60 and 90 minutes and cut scope, not quality.
- Subagents may be used for parallel work (data profiling, independent verification, docs), each with a bounded task and a written result. The main session integrates and reviews every diff.

## Submission checklist

- README: how to run locally and with Docker, where to unzip the data, example requests.
- DECISIONS.md with Started and Stopped, then exactly the three headings from the brief, 10 to 20 lines, naming the AI tools used, one thing verified, changed or rejected, and the template we started from.
- `data/` is not committed. Nothing private or employer-specific in the repository.
