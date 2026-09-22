Started: 2026-09-22 15:02 CEST
Stopped: TBD

## What I built

- Backlog items 1 to 7: the single-portfolio endpoint, the comparison of all portfolios ranked by loss ratio, a data-quality endpoint, filters by underwriting year, region and asset type, a page, a Dockerfile with compose and 45 tests, plus a standard-library verifier and a two-job CI. Everything is loaded, cleaned and kept in memory at startup, in 0.15 s.
- Started from the scaffold of my previous two-hour case (pyproject, CLAUDE.md layout, Dockerfile, CI workflow, test layout), as the brief allows. All business logic is new.
- The data problems that change the answer, each applied once in data.py, counted and served at /data-quality: 25 spellings of the five perils normalised (1321 rows); claim dates in two formats, ISO and DD-MM-YYYY (day-first verified: 343 rows have a day above 12, and reported >= loss holds for every row after parsing); 260 orphan claims against policy ids that do not exist, excluded; 310 claims whose loss date precedes their policy's inception, excluded, 83 of which have another term of the same asset and peril covering the loss; 245 negative paid amounts, excluded; 667 settled claims still carrying a reserve, kept with the reserve ignored (2.1 M DKK); claim and policy currency differ for 748 claims, each amount converted with its own currency.
- Currency: premiums at the inception month's rate, claims at the loss month's; a missing rate excludes and counts the row (none missing here). Ranking: loss ratio descending, then incurred loss. Claim counts include declined and withdrawn claims, which cost nothing; policy counts count terms.
- AI tooling: Claude Code with Fable 5.1. The main session profiled the data, fixed the cleaning policy and a module contract, then ran five subagents in git worktrees (core, tests, verifier, packaging, page) and reviewed and merged every branch.
- Verified and changed: my pre-implementation profile put PF-03, PF-07 and PF-11 at a loss ratio around 2, and that expectation went into the tests. The service gave 0.91, 0.73 and 0.76. Chasing the gap showed the profile had skipped currency conversion, and those three portfolios carry about 77 % of their premium in EUR, so their premium was 7.4 times too small. The tests were corrected, not the service; the verifier then matched the service on all 12 portfolios, field for field.

## What I deliberately did not build, and why

- A database: 11,560 policies and 4,509 claims build into an index in 0.15 s. A database would add operations without adding correctness, and infrastructure before a correct core is the wrong order.
- Re-attribution of the 83 claims to the term that covers their loss date: 2,012 renewal terms overlap, so attribution by date is ambiguous for six of them and needs a rule the brief does not give.
- A weighted performance score: any weighting is a pricing decision, so the ranking uses the loss ratio the brief defines.

## What I would do first with another day

- Settle the two exclusion policies with the underwriters, with the sensitivity in hand: including the pre-inception claims raises the worst ratios by 4 to 7 points, netting negative amounts lowers them by 1 to 5, and neither changes the ranking.
- Then re-attribute the 83 claims by date, with a documented tie-break for the six inside two overlapping terms.
