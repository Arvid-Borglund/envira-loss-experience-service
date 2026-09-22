# Envira loss-experience service

A small HTTP service that answers how a portfolio of insured assets has
performed: earned premium, incurred loss and the loss ratio, per peril and in
total, in DKK. The four CSV files (assets, policies, claims, FX rates) are
cleaned and precomputed in memory at startup, well under a second; the startup
log prints how many rows each data-quality rule touched, and the same summary
is served at `/data-quality`.

## Data

The data is not committed, on purpose (the brief forbids it). Unzip the four
files `assets.csv`, `policies.csv`, `claims.csv` and `fx_rates.csv` into
`data/` at the repository root, or set `LOSSEXP_DATA_DIR` to read them from
somewhere else. If the directory is missing, startup fails with a message that
points back here.

## Run locally

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

    uv sync
    uv run uvicorn lossexp.api:app --port 8000

## Run with Docker

The image contains the code only; the data is mounted read-only at run time.

    docker build -t envira-lossexp .
    docker run --rm -p 8000:8000 -v "$PWD/data:/app/data:ro" envira-lossexp

or, with compose (same image, port and mount, plus a healthcheck on `/health`):

    docker compose up --build

## Endpoints

| Method and path | What it returns |
|---|---|
| `GET /portfolios/{portfolio_id}/loss-experience` | Loss experience for one portfolio, per peril and in total. 404 for an unknown id, 400 for an invalid filter value. |
| `GET /portfolios/loss-experience` | The same measures for every portfolio, ranked worst loss ratio first. |
| `GET /data-quality` | What was normalised, excluded or noted at startup, with counts and DKK amounts. |
| `GET /health` | Liveness check. |
| `GET /` | A simple page where a non-technical user can pick a portfolio. |
| `GET /docs` | FastAPI's generated API documentation. |

Both loss-experience endpoints take the optional query filters
`underwriting_year` (2022-2024), `region` (`Hovedstaden`, `Midtjylland`,
`Nordjylland`, `Sjaelland`, `Syddanmark`) and `asset_type` (`agricultural`,
`commercial`, `industrial`, `public`, `residential`). Portfolio ids are
`PF-01` to `PF-12`; perils are `fire`, `flood`, `hail`, `storm`, `subsidence`.

    curl http://localhost:8000/portfolios/PF-03/loss-experience
    curl "http://localhost:8000/portfolios/PF-03/loss-experience?underwriting_year=2023&region=Sjaelland"
    curl "http://localhost:8000/portfolios/loss-experience?asset_type=residential"

Example single-portfolio response (one peril shown):

<!-- TODO real numbers -->
    {"portfolio_id": "PF-03",
     "filters": {"underwriting_year": null, "region": null, "asset_type": null},
     "perils": [{"peril": "fire", "policy_count": 190, "earned_premium_dkk": 1234567.89,
                 "incurred_loss_dkk": 234567.89, "loss_ratio": 0.19, "claim_count": 45,
                 "largest_claim_dkk": 98765.43}],
     "total": {"policy_count": 950, "earned_premium_dkk": 5000000.0, "incurred_loss_dkk": 10000000.0,
               "loss_ratio": 2.0, "claim_count": 300, "largest_claim_dkk": 285819.83}}

## Definitions

Taken from the brief (`docs/BRIEF.md`) and binding for the implementation:

- Incurred loss: what a claim has cost so far, in DKK: the paid amount for a settled claim, paid plus reserved for an open claim, nothing for a declined or withdrawn claim.
- Earned premium: the full annual premium of each policy term, in DKK, no pro-rata.
- Loss ratio: incurred loss divided by earned premium.
- Underwriting year: the calendar year of the policy's inception date.
- Currency: each amount is converted with its own currency, the premium at the rate of the inception month and the claim at the rate of the loss month. A missing rate excludes the row and is counted.

## Data quality

The files are source data, not clean data. Every normalisation and exclusion
(peril spellings, two date formats, orphan claims, claims before inception,
negative amounts, and so on) is applied in one place, logged with counts at
startup and exposed at `/data-quality`, so the numbers can always be traced
back to what was left out. The policy behind each rule is in `DECISIONS.md`.

## Verify

    uv run pytest -q
    uv run python scripts/verify_loss_experience.py PF-03 --compare-url http://localhost:8000

The tests that need the data skip when `data/` is absent (as in CI). The
script recomputes one portfolio with the standard library only (no pandas)
and, with `--compare-url`, checks the running service against it.

## Layout

- `lossexp/data.py`: load and clean the CSV files; every data-quality rule lives here and is logged with counts.
- `lossexp/fx.py`: monthly FX rates and conversion to DKK.
- `lossexp/metrics.py`: earned premium, incurred loss, loss ratio, per peril and in total.
- `lossexp/service.py`: the join layer: portfolio results, ranking and filters, shared by the API.
- `lossexp/api.py`: the FastAPI app (`lossexp.api:app`).
- `lossexp/static/index.html`: the page served at `/`.
- `scripts/verify_loss_experience.py`: independent recomputation, see Verify.
- `tests/`: pytest suite.

Assumptions and data decisions: `DECISIONS.md`. The task: `docs/BRIEF.md`.
