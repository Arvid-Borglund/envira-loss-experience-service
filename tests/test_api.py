"""End to end through FastAPI against the real data; the whole module is skipped when data/ is absent."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
pytestmark = pytest.mark.skipif(not (DATA_DIR / "claims.csv").exists(), reason="data/ not present (see README)")

PERILS = ["fire", "flood", "hail", "storm", "subsidence"]
METRIC_KEYS = {"policy_count", "earned_premium_dkk", "incurred_loss_dkk", "loss_ratio", "claim_count", "largest_claim_dkk"}
SOURCE_ROWS = {"assets": 4200, "policies": 11560, "claims": 4509, "fx_rates": 168}


@pytest.fixture(scope="module")
def client():
    with pytest.MonkeyPatch.context() as env:
        env.setenv("LOSSEXP_DATA_DIR", str(DATA_DIR))
        from lossexp.api import app

        with TestClient(app) as client:
            yield client


@pytest.fixture(scope="module")
def pf03(client):
    response = client.get("/portfolios/PF-03/loss-experience")
    assert response.status_code == 200
    return response.json()


def test_portfolio_response_has_exactly_the_contract_keys(pf03):
    assert set(pf03) == {"portfolio_id", "filters", "perils", "total"}
    assert set(pf03["filters"]) == {"underwriting_year", "region", "asset_type"}
    assert all(set(peril) == METRIC_KEYS | {"peril"} for peril in pf03["perils"])
    assert set(pf03["total"]) == METRIC_KEYS


def test_portfolio_lists_the_five_perils_sorted(pf03):
    assert [peril["peril"] for peril in pf03["perils"]] == PERILS


def test_portfolio_total_is_the_sum_of_its_perils(pf03):
    for key in ("incurred_loss_dkk", "earned_premium_dkk"):
        assert pf03["total"][key] == pytest.approx(sum(peril[key] for peril in pf03["perils"]), abs=0.01)
    assert pf03["total"]["policy_count"] == sum(peril["policy_count"] for peril in pf03["perils"])


def test_pf03_is_loss_making(pf03):
    assert pf03["total"]["loss_ratio"] > 1


def test_unknown_portfolio_is_404(client):
    assert client.get("/portfolios/PF-99/loss-experience").status_code == 404


def test_unknown_asset_type_filter_is_400(client):
    assert client.get("/portfolios/PF-03/loss-experience", params={"asset_type": "castle"}).status_code == 400


def test_underwriting_year_filter_narrows_the_book(client):
    unfiltered = client.get("/portfolios/PF-01/loss-experience").json()
    filtered = client.get("/portfolios/PF-01/loss-experience", params={"underwriting_year": 2023}).json()
    assert filtered["filters"]["underwriting_year"] == 2023
    assert filtered["total"]["policy_count"] <= unfiltered["total"]["policy_count"]


def test_compare_ranks_all_portfolios_by_loss_ratio(client):
    body = client.get("/portfolios/loss-experience").json()
    assert set(body) == {"ranking", "filters", "portfolios"}
    portfolios = body["portfolios"]
    assert [portfolio["rank"] for portfolio in portfolios] == list(range(1, 13))
    assert sorted(portfolio["portfolio_id"] for portfolio in portfolios) == [f"PF-{n:02d}" for n in range(1, 13)]
    ratios = [portfolio["loss_ratio"] for portfolio in portfolios if portfolio["loss_ratio"] is not None]
    assert ratios == sorted(ratios, reverse=True)


def test_compare_worst_peril_is_at_least_the_portfolio_ratio(client):
    for portfolio in client.get("/portfolios/loss-experience").json()["portfolios"]:
        worst = portfolio["worst_peril"]
        if worst and worst["loss_ratio"] is not None and portfolio["loss_ratio"] is not None:
            assert worst["loss_ratio"] >= portfolio["loss_ratio"] - 1e-9


def test_data_quality_reports_sources_and_the_orphan_rule(client):
    body = client.get("/data-quality").json()
    assert body["source_rows"] == SOURCE_ROWS
    assert set(body["used_rows"]) == {"policies", "claims"}
    orphan = [entry for entry in body["issues"] if "orphan" in entry["rule"].lower()]
    assert orphan and orphan[0]["rows"] == 260


def test_health_is_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
