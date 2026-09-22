Started: 2026-09-22 15:02 CEST
Stopped: TBD

## What I built

## What I deliberately did not build, and why

## What I would do first with another day

<!-- draft notes for the orchestrator, delete before submission
- Started from the scaffold of a previous two-hour case (pyproject, CLAUDE.md layout, Dockerfile, CI, test layout), as the brief allows.
- Peril spellings normalised: 25 variants of 5 values.
- Two date formats, ISO and DD-MM-YYYY. Day-first verified: 343 rows have day > 12, and reported >= loss holds for every row after parsing.
- 260 orphan claims excluded: POL-9xxxxx ids that do not exist in policies.
- 310 claims with a loss date before the policy's inception excluded; 83 of them have another covering term. Re-attribution to that term is the first thing for another day.
- Negative paid amounts excluded: 262 rows, 245 after the earlier rules.
- 721 settled claims with a remaining reserve kept; the reserve is ignored per the definition.
- Claim and policy currency differ for about 860 claims; each amount is converted with its own currency.
- FX: premium at the inception month, claim at the loss month. A missing rate excludes the row and is counted (none missing in this data).
- Ranking of the all-portfolios endpoint: loss ratio desc.
- AI tooling: Claude Code with Fable 5.1, the main session orchestrating five subagents in git worktrees (core, tests, verifier, docs/docker/CI, page).
- One thing verified, changed or rejected: TBD.
-->
