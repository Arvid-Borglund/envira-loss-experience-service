"""Loading and cleaning: date parsing and the exclusion rules, each on a tiny hand-built frame."""

from pathlib import Path

import pandas as pd
import pytest

from lossexp.data import clean_claims, clean_policies, load_dataset, parse_dates

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
needs_data = pytest.mark.skipif(not (DATA_DIR / "claims.csv").exists(), reason="data/ not present (see README)")

ASSETS = pd.DataFrame(
    [{"asset_id": "A-1", "portfolio_id": "PF-01", "region": "Sjaelland", "asset_type": "residential", "construction_year": 1990, "sum_insured_dkk": 2_000_000.0}]
)
RATES = pd.DataFrame(
    [
        {"month": "2024-01", "currency": "EUR", "rate_dkk_per_unit": 7.40},
        {"month": "2024-06", "currency": "EUR", "rate_dkk_per_unit": 7.50},
    ]
)
# Rule names are not part of the contract: an issue is recognised by a keyword in its rule name.
ORPHAN, OUTSIDE_TERM, NEGATIVE = ("orphan",), ("outside", "term"), ("negative",)
RESERVE, CURRENCY, RATE, PERIL = ("reserve",), ("currency",), ("rate", "fx"), ("peril",)
MIXED_DATES = pd.Series(["2024-03-26", "10-04-2024", "garbage"])


def issue(issues, keywords, action="excluded"):
    for entry in issues:
        if entry["action"] == action and any(keyword in entry["rule"].lower() for keyword in keywords):
            return entry
    pytest.fail(f"no {action} issue matching {keywords} among {[entry['rule'] for entry in issues]}")


def raw_policy(**overrides):
    base = {"policy_id": "P-1", "asset_id": "A-1", "peril": "fire", "inception_date": "2024-01-15", "expiry_date": "2025-01-14", "annual_premium": 1000.0, "currency": "DKK"}
    return {**base, **overrides}


def raw_claim(**overrides):
    base = {"claim_id": "C-1", "policy_id": "P-1", "loss_date": "2024-06-01", "reported_date": "2024-06-05", "paid_amount": 100.0, "reserve_amount": 0.0, "currency": "DKK", "status": "settled"}
    return {**base, **overrides}


def policies_from(*rows):
    return clean_policies(pd.DataFrame(list(rows)), ASSETS, RATES)


def claims_from(policies, *rows):
    return clean_claims(pd.DataFrame(list(rows)), policies, RATES)


@pytest.fixture
def policies():
    """One cleaned DKK fire policy on A-1, in force 2024-01-15 to 2025-01-14."""
    return policies_from(raw_policy())[0]


def test_parse_dates_reads_iso():
    assert parse_dates(MIXED_DATES).iloc[0] == pd.Timestamp("2024-03-26")


def test_parse_dates_reads_day_first_not_month_first():
    assert parse_dates(MIXED_DATES).iloc[1] == pd.Timestamp("2024-04-10")


def test_parse_dates_gives_nat_for_garbage():
    assert pd.isna(parse_dates(MIXED_DATES).iloc[2])


def test_clean_policies_normalises_peril_and_reports_it():
    clean, issues = policies_from(raw_policy(peril=" Flood "))
    assert clean["peril"].tolist() == ["flood"]
    assert issue(issues, PERIL, action="normalised")["rows"] == 1


def test_clean_policies_converts_eur_premium_at_inception_month():
    clean, _ = policies_from(raw_policy(currency="EUR", annual_premium=100.0))  # incepts 2024-01, rate 7.40
    assert clean["premium_dkk"].iloc[0] == pytest.approx(740.0)


def test_clean_policies_derives_group_columns_from_the_asset():
    first = policies_from(raw_policy())[0].iloc[0]
    assert (first.portfolio_id, first.region, first.asset_type, first.underwriting_year) == ("PF-01", "Sjaelland", "residential", 2024)


def test_clean_policies_excludes_unknown_asset():
    clean, _ = policies_from(raw_policy(), raw_policy(policy_id="P-2", asset_id="A-404"))
    assert clean["policy_id"].tolist() == ["P-1"]


def test_clean_claims_excludes_orphan_and_reports_it(policies):
    clean, issues = claims_from(policies, raw_claim(), raw_claim(claim_id="C-2", policy_id="P-404"))
    assert clean["claim_id"].tolist() == ["C-1"]
    assert issue(issues, ORPHAN)["rows"] == 1


def test_clean_claims_excludes_loss_outside_policy_term(policies):
    before = raw_claim(claim_id="C-2", loss_date="2024-01-01", reported_date="2024-01-02")
    after = raw_claim(claim_id="C-3", loss_date="2025-02-01", reported_date="2025-02-02")
    clean, issues = claims_from(policies, raw_claim(), before, after)
    assert clean["claim_id"].tolist() == ["C-1"]
    assert issue(issues, OUTSIDE_TERM)["rows"] == 2


def test_clean_claims_keeps_loss_on_term_boundaries(policies):
    on_inception = raw_claim(loss_date="2024-01-15", reported_date="2024-01-20")
    on_expiry = raw_claim(claim_id="C-2", loss_date="2025-01-14", reported_date="2025-01-20")
    assert len(claims_from(policies, on_inception, on_expiry)[0]) == 2


def test_clean_claims_excludes_negative_paid(policies):
    clean, issues = claims_from(policies, raw_claim(), raw_claim(claim_id="C-2", paid_amount=-5.0))
    assert clean["claim_id"].tolist() == ["C-1"]
    assert issue(issues, NEGATIVE)["rows"] == 1


def test_clean_claims_keeps_settled_with_reserve_and_ignores_it(policies):
    clean, issues = claims_from(policies, raw_claim(paid_amount=100.0, reserve_amount=50.0))
    assert clean["incurred_dkk"].tolist() == [100.0]
    assert issue(issues, RESERVE, action="noted")["rows"] == 1


def test_clean_claims_converts_eur_at_loss_month(policies):
    clean, _ = claims_from(policies, raw_claim(currency="EUR", paid_amount=100.0))  # loss 2024-06, rate 7.50
    assert clean["incurred_dkk"].iloc[0] == pytest.approx(750.0)


def test_clean_claims_notes_currency_differing_from_policy(policies):
    _, issues = claims_from(policies, raw_claim(currency="EUR"))  # the policy is in DKK
    assert issue(issues, CURRENCY, action="noted")["rows"] == 1


def test_clean_claims_excludes_claim_without_fx_rate(policies):
    clean, issues = claims_from(policies, raw_claim(currency="EUR", loss_date="2024-03-01", reported_date="2024-03-02"))
    assert clean.empty
    assert issue(issues, RATE)["rows"] == 1


def test_clean_claims_collapses_identical_duplicates(policies):
    assert len(claims_from(policies, raw_claim(), raw_claim())[0]) == 1


def test_clean_claims_excludes_conflicting_duplicates(policies):
    assert claims_from(policies, raw_claim(paid_amount=100.0), raw_claim(paid_amount=200.0))[0].empty


def test_clean_claims_issues_follow_rule_order_and_excluded_rows_add_up(policies):
    orphan_and_negative = raw_claim(claim_id="C-2", policy_id="P-404", paid_amount=-1.0)  # counted once, by the first rule
    raw = pd.DataFrame([raw_claim(), orphan_and_negative, raw_claim(claim_id="C-3", loss_date="2023-01-01"), raw_claim(claim_id="C-4", paid_amount=-1.0)])
    clean, issues = clean_claims(raw, policies, RATES)
    excluded = [entry for entry in issues if entry["action"] == "excluded"]
    assert len(raw) - len(clean) == sum(entry["rows"] for entry in excluded) == 3
    positions = [excluded.index(issue(excluded, keywords)) for keywords in (ORPHAN, OUTSIDE_TERM, NEGATIVE)]
    assert positions == sorted(positions)


@needs_data
def test_load_dataset_real_data_counts():
    dataset = load_dataset(DATA_DIR)
    assert dataset.source_rows == {"assets": 4200, "policies": 11560, "claims": 4509, "fx_rates": 168}
    claim_issues = [entry for entry in dataset.quality if entry["table"] == "claims"]
    assert issue(claim_issues, ORPHAN)["rows"] == 260
    assert issue(claim_issues, OUTSIDE_TERM)["rows"] == 310
    assert issue(claim_issues, NEGATIVE)["rows"] == 245
    assert issue(dataset.quality, PERIL, action="normalised")["rows"] == 1321  # 11560 minus the five canonical spellings
    excluded = sum(entry["rows"] for entry in claim_issues if entry["action"] == "excluded")
    assert len(dataset.claims) + excluded == dataset.source_rows["claims"]
