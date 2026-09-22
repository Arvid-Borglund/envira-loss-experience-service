# Envira practical test

## Loss-experience service

**Two hours of your time, followed by a 30-minute call with us.**

Thanks for getting this far. This task is meant to resemble a real morning at Envira: real-shaped data, more possible work than fits in the time, and decisions to make about what actually matters.

`SCORING.md`, sent with this brief, sets out exactly how we assess what you send. Read it first — it is short, and it will tell you where to spend the two hours.

## Before you start

**Use the AI tooling you normally use.** We expect you to. Every engineer here works this way, and a test that pretended otherwise would tell us very little. You remain responsible for everything you submit.

If your normal setup uses repository-specific AI instructions such as `CLAUDE.md`, `AGENTS.md` or `.cursorrules`, include the ones you actually used. Do not include private or employer-specific global configuration.

**You may start from a project template you already have.** A scaffold you have used before — a service skeleton, a Dockerfile, a test layout — is fine and normal. Say in `DECISIONS.md` what you started from, so we read the two hours correctly.

**Work for a maximum of two hours.** Choose any two-hour block before the submission deadline. Record your start and stop time in `DECISIONS.md`. This is honour-based; the live walkthrough matters more to us than policing the clock.

**Keep a real git history.** Commit as you go rather than squashing everything into one final commit. We read the history as context, not as a stopwatch.

**There is more in this brief than fits in two hours. That is deliberate.** Your priority is a correct, runnable loss-experience endpoint for a single portfolio. After that, choose what is worth adding. A small solution that works and is well understood will beat a large half-working one.

**If something is ambiguous or looks wrong, use your judgement.** Make a reasonable assumption, implement what you think is right, and state the assumption briefly. You may also ask us a question during the exercise.

---

## The problem

Envira prices climate risk for Danish insurers and banks. Before we can price anything, an underwriter needs to know how a book of business has actually performed: which portfolios and which perils are losing money, and by how much.

You have a book of policies, the claims made against them, and the assets they cover. We would like a small service that reports loss experience.

---

## The data: `./data`

| file | rows | what it is |
|---|---:|---|
| `assets.csv` | 4,200 | insured properties: id, portfolio, region, type, construction year, sum insured |
| `policies.csv` | ~11,600 | one row per policy term: id, asset, peril, inception and expiry, annual premium, currency |
| `claims.csv` | ~4,500 | claims against those policies: loss and reported dates, amounts paid and reserved, currency, status |
| `fx_rates.csv` | 168 | month-end exchange rates into DKK |

Two things worth knowing before you start:

- **Not everything is denominated in the same currency.** Premiums and claims are recorded in the currency they were transacted in, and these are not always the same for the same policy.
- **The files have not been cleaned for you.** They are synthetic, and they contain the kinds of quality problems real books of business contain. Treat them as source data rather than assuming every row is valid, unique, or references something that exists.

---

## Definitions

- **Incurred loss**: what a claim has cost so far. For a settled claim this is the amount paid. For an open claim it is the amount paid plus the amount still reserved. Claims that were withdrawn or declined cost nothing.
- **Earned premium**: for this exercise, treat a policy's full annual premium as earned. No pro-rata.
- **Loss ratio**: incurred loss divided by earned premium, in DKK.
- **Underwriting year**: the calendar year in which a policy incepted.
- **A claim belongs to a policy.** If the data makes that relationship ambiguous or impossible, make and document a reasonable assumption.

---

## What we would like

Start with the first item. Everything after that is a backlog. Decide how far to go.

1. **Core:** `GET /portfolios/{portfolio_id}/loss-experience` returning, for each peril, the policy count, earned premium, incurred loss, loss ratio, claim count, and the largest single claim. All monetary figures in DKK.
2. `GET /portfolios/loss-experience` comparing all portfolios, with a useful ordering. There is deliberately no prescribed single "performance score"; choose a sensible ranking and document it.
3. A data-quality endpoint or report: what did you have to exclude, and why.
4. Filtering by underwriting year, region, or asset type.
5. A simple page where a non-technical user can pick a portfolio and see the answer.
6. A `Dockerfile`, and a compose file if useful, so the service can be started on a known port with a simple command.
7. Tests.
8. Load the data into a database on startup rather than reading CSV files on every request.

You are not expected to finish all eight items.

---

## What to send us

**A link to a public GitHub repository** with the work, however far you got. Send us the URL.

We read the commit history as part of the review, so push the history you actually made rather than one squashed commit. Do not commit anything private: no credentials, no employer-specific configuration. You are welcome to make the repository private or delete it once the process is over.

**Do not commit the `data/` directory** — add it to `.gitignore`. Instead, say in the README where to unzip the data so that we can run your service against it.

**`DECISIONS.md`**, starting with:

```text
Started: YYYY-MM-DD HH:MM TZ
Stopped: YYYY-MM-DD HH:MM TZ
```

and then exactly these three headings:

- **What I built**
- **What I deliberately did not build, and why**
- **What I would do first with another day**

Keep it short, ideally 10 to 20 lines. Somewhere in those sections, briefly mention which AI tools you used and one thing you specifically verified, changed or rejected rather than simply accepting generated output.

---

## The call

Thirty minutes, screen shared. You will show us the service running, we will ask about parts of the code, and we will ask you to make one small change while we watch.

Use your normal working setup for the call: editor, terminal and AI tools included.

There is no trick to prepare for. We want to see how you understand, verify and change what you built.
