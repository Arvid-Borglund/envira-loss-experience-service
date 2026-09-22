"""Business logic on hand-built frames: incurred mapping, peril normalisation, per-group aggregation."""

import math

import pandas as pd
import pytest

from lossexp.metrics import incurred_amount, loss_experience, normalise_peril

GROUP = {"portfolio_id": "PF-01", "underwriting_year": 2023, "region": "Sjaelland", "asset_type": "residential"}
RESULT_COLUMNS = ["policy_count", "earned_premium_dkk", "incurred_loss_dkk", "loss_ratio", "claim_count", "largest_claim_dkk"]


def policy(policy_id, peril, premium_dkk, **overrides):
    return {**GROUP, "policy_id": policy_id, "peril": peril, "premium_dkk": premium_dkk, **overrides}


def claim(claim_id, policy_id, peril, incurred_dkk, **overrides):
    return {**GROUP, "claim_id": claim_id, "policy_id": policy_id, "peril": peril, "incurred_dkk": incurred_dkk, **overrides}


def experience(policies, claims, by=("portfolio_id", "peril")):
    return loss_experience(pd.DataFrame(policies), pd.DataFrame(claims), by=list(by))


def row(result, **key):
    """The single result row whose `by` columns equal `key`."""
    mask = pd.Series(True, index=result.index)
    for column, value in key.items():
        mask &= result[column] == value
    matches = result[mask]
    assert len(matches) == 1, f"expected one row for {key}, got {len(matches)}"
    return matches.iloc[0]


def test_incurred_amount_maps_each_status():
    status = pd.Series(["settled", "open", "declined", "withdrawn"])
    paid = pd.Series([100.0, 100.0, 100.0, 100.0])
    reserve = pd.Series([40.0, 40.0, 40.0, 40.0])
    assert incurred_amount(status, paid, reserve).tolist() == [100.0, 140.0, 0.0, 0.0]


def test_incurred_amount_rejects_unknown_status():
    with pytest.raises(ValueError):
        incurred_amount(pd.Series(["pending"]), pd.Series([1.0]), pd.Series([0.0]))


def test_normalise_peril_strips_and_lowercases():
    assert normalise_peril(pd.Series([" Flood ", "FIRE  ", "hail"])).tolist() == ["flood", "fire", "hail"]


def test_loss_experience_sums_each_group_separately():
    policies = [policy("P1", "fire", 1000.0), policy("P2", "fire", 3000.0), policy("P3", "flood", 2000.0)]
    claims = [claim("C1", "P1", "fire", 400.0), claim("C2", "P2", "fire", 600.0), claim("C3", "P3", "flood", 500.0)]
    result = experience(policies, claims)
    fire, flood = row(result, peril="fire"), row(result, peril="flood")
    assert (fire.policy_count, fire.earned_premium_dkk, fire.incurred_loss_dkk, fire.claim_count) == (2, 4000.0, 1000.0, 2)
    assert fire.loss_ratio == pytest.approx(0.25)
    assert (flood.policy_count, flood.earned_premium_dkk, flood.incurred_loss_dkk, flood.claim_count) == (1, 2000.0, 500.0, 1)


def test_group_without_claims_shows_zeros():
    result = experience([policy("P1", "fire", 1000.0), policy("P2", "flood", 500.0)], [claim("C1", "P1", "fire", 10.0)])
    flood = row(result, peril="flood")
    assert (flood.claim_count, flood.incurred_loss_dkk, flood.largest_claim_dkk, flood.loss_ratio) == (0, 0.0, 0.0, 0.0)


def test_loss_ratio_is_nan_when_premium_is_zero():
    result = experience([policy("P1", "fire", 0.0)], [claim("C1", "P1", "fire", 10.0)])
    assert math.isnan(row(result, peril="fire").loss_ratio)


def test_largest_claim_is_the_max_single_incurred():
    claims = [claim("C1", "P1", "fire", 100.0), claim("C2", "P1", "fire", 700.0), claim("C3", "P1", "fire", 300.0)]
    fire = row(experience([policy("P1", "fire", 1000.0)], claims), peril="fire")
    assert (fire.largest_claim_dkk, fire.incurred_loss_dkk) == (700.0, 1100.0)


def test_policy_count_counts_terms_not_assets():
    two_terms = [policy("P1-2023", "fire", 100.0), policy("P1-2024", "fire", 100.0, underwriting_year=2024)]
    result = experience(two_terms, [claim("C1", "P1-2023", "fire", 10.0)])
    assert row(result, peril="fire").policy_count == 2


def test_claim_in_group_without_policies_raises():
    with pytest.raises(ValueError):
        experience([policy("P1", "fire", 100.0)], [claim("C1", "P9", "flood", 10.0)])


def test_by_portfolio_aggregates_across_perils_and_sorts_by_key():
    policies = [policy("P1", "fire", 1000.0, portfolio_id="PF-02"), policy("P2", "flood", 3000.0, portfolio_id="PF-02"), policy("P3", "hail", 500.0)]
    claims = [claim("C1", "P1", "fire", 100.0, portfolio_id="PF-02"), claim("C2", "P2", "flood", 900.0, portfolio_id="PF-02")]
    result = experience(policies, claims, by=["portfolio_id"])
    assert list(result.columns) == ["portfolio_id", *RESULT_COLUMNS]
    assert result["portfolio_id"].tolist() == ["PF-01", "PF-02"]
    pf02 = row(result, portfolio_id="PF-02")
    assert (pf02.policy_count, pf02.earned_premium_dkk, pf02.incurred_loss_dkk, pf02.claim_count, pf02.largest_claim_dkk) == (2, 4000.0, 1000.0, 2, 900.0)
