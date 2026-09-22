"""Load the four CSVs and apply every cleaning rule, in order, counted.

Each rule runs once, on the rows that survived the previous rules, so the
counts add up: source rows minus every "excluded" count equals the used rows.
Every rule yields exactly one quality entry, logged at startup and served by
/data-quality. Nothing is dropped silently and load order never decides
between conflicting rows.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from lossexp.fx import load_rates, month_key, to_dkk
from lossexp.metrics import STATUSES, incurred_amount, normalise_peril

log = logging.getLogger(__name__)

ASSET_COLUMNS = ["asset_id", "portfolio_id", "region", "asset_type", "construction_year", "sum_insured_dkk"]
POLICY_COLUMNS = ["policy_id", "asset_id", "peril", "inception_date", "expiry_date", "annual_premium", "currency"]
CLAIM_COLUMNS = [
    "claim_id", "policy_id", "loss_date", "reported_date",
    "paid_amount", "reserve_amount", "currency", "status",
]
ASSET_ATTRIBUTES = ["portfolio_id", "region", "asset_type"]
GROUP_ATTRIBUTES = ["portfolio_id", "peril", "underwriting_year", "region", "asset_type"]
FILES = ("assets.csv", "policies.csv", "claims.csv", "fx_rates.csv")


@dataclass(frozen=True)
class Dataset:
    """The cleaned tables plus the quality report that explains the difference from the source."""

    assets: pd.DataFrame
    policies: pd.DataFrame
    claims: pd.DataFrame
    rates: pd.DataFrame
    quality: list[dict]
    source_rows: dict[str, int]


def parse_dates(values: pd.Series) -> pd.Series:
    """ISO 'YYYY-MM-DD' first, then 'DD-MM-YYYY'; NaT for anything else.

    Day-first is certain for the second format (hundreds of source rows have a
    day above 12). ISO strings are never re-read day-first.
    """
    text = values.astype("string").str.strip()
    iso = pd.to_datetime(text, format="%Y-%m-%d", errors="coerce")
    day_first = pd.to_datetime(text, format="%d-%m-%Y", errors="coerce")
    return iso.fillna(day_first)


def _day_first_count(values: pd.Series) -> int:
    """How many values only parsed as DD-MM-YYYY (for the quality detail)."""
    text = values.astype("string").str.strip()
    iso = pd.to_datetime(text, format="%Y-%m-%d", errors="coerce")
    return int((iso.isna() & parse_dates(values).notna()).sum())


def _entry(rule: str, table: str, rows: int, action: str, detail: str, amount_dkk: float | None = None) -> dict:
    return {
        "rule": rule,
        "table": table,
        "rows": int(rows),
        "amount_dkk": None if amount_dkk is None else float(amount_dkk),
        "action": action,
        "detail": detail,
    }


def _drop_duplicate_ids(df: pd.DataFrame, key: str) -> tuple[pd.DataFrame, str]:
    """Identical duplicate rows collapse to one; rows sharing a key but differing are all excluded.

    A null key cannot be matched by anything, so those rows are excluded too.
    """
    identical = df.duplicated(keep="first")
    df = df[~identical]
    null_key = df[key].isna()
    df = df[~null_key]
    conflicting = df.duplicated(key, keep=False)
    df = df[~conflicting]
    detail = (
        f"{int(identical.sum())} identical duplicate rows collapsed, "
        f"{int(conflicting.sum())} rows with a conflicting duplicate {key} excluded, "
        f"{int(null_key.sum())} rows without a {key} excluded."
    )
    return df, detail


def _require_columns(df: pd.DataFrame, columns: list[str], name: str) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(f"{name}: missing columns {missing}")


def clean_policies(raw: pd.DataFrame, assets: pd.DataFrame, rates: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Rules 1-7 on policies; returns the cleaned frame and one quality entry per rule."""
    _require_columns(raw, POLICY_COLUMNS, "policies")
    quality: list[dict] = []
    df = raw.copy()
    before = len(df)

    # 1. peril spelling: case and surrounding whitespace only
    raw_peril = df["peril"].astype("string")
    df["peril"] = normalise_peril(raw_peril)
    changed = int((df["peril"].fillna("") != raw_peril.fillna("")).sum())
    quality.append(_entry(
        "policies_peril_normalised", "policies", changed, "normalised",
        f"{raw_peril.dropna().nunique()} spellings of {df['peril'].dropna().nunique()} perils: "
        "whitespace stripped and lower-cased.",
    ))

    # 2. duplicate policy_id
    df, detail = _drop_duplicate_ids(df, "policy_id")
    quality.append(_entry("policies_duplicate_id", "policies", before - len(df), "excluded", detail))
    before = len(df)

    # 3. asset must exist
    df = df[df["asset_id"].isin(assets["asset_id"])]
    quality.append(_entry(
        "policies_unknown_asset", "policies", before - len(df), "excluded",
        "asset_id not present in assets.csv, so no portfolio, region or asset type.",
    ))
    before = len(df)

    # 4. dates in either format
    day_first = _day_first_count(df["inception_date"]) + _day_first_count(df["expiry_date"])
    df = df.assign(inception_date=parse_dates(df["inception_date"]), expiry_date=parse_dates(df["expiry_date"]))
    df = df[df["inception_date"].notna() & df["expiry_date"].notna()]
    quality.append(_entry(
        "policies_unparseable_date", "policies", before - len(df), "excluded",
        f"inception_date or expiry_date in neither YYYY-MM-DD nor DD-MM-YYYY; {day_first} values were day-first.",
    ))
    before = len(df)

    # 5. term must run forwards
    df = df[df["expiry_date"] > df["inception_date"]]
    quality.append(_entry(
        "policies_expiry_not_after_inception", "policies", before - len(df), "excluded",
        "expiry_date on or before inception_date: no term to earn premium on.",
    ))
    before = len(df)

    # 6. a positive premium
    df = df.assign(annual_premium=pd.to_numeric(df["annual_premium"], errors="coerce"))
    df = df[df["annual_premium"] > 0]
    quality.append(_entry(
        "policies_non_positive_premium", "policies", before - len(df), "excluded",
        "annual_premium missing, non-numeric or not above zero.",
    ))
    before = len(df)

    # 7. premium into DKK at the inception-month rate
    df = df.assign(premium_dkk=to_dkk(df["annual_premium"], df["currency"], month_key(df["inception_date"]), rates))
    foreign = int((df["currency"] != "DKK").sum())
    df = df[df["premium_dkk"].notna()]
    quality.append(_entry(
        "policies_no_fx_rate", "policies", before - len(df), "excluded",
        f"no rate for the policy's currency in the inception month; {foreign} non-DKK premiums converted.",
    ))

    df = df.merge(assets[["asset_id"] + ASSET_ATTRIBUTES], on="asset_id", how="left", validate="many_to_one")
    df["underwriting_year"] = df["inception_date"].dt.year.astype(int)
    columns = [
        "policy_id", "asset_id", "portfolio_id", "peril", "underwriting_year", "region", "asset_type",
        "premium_dkk", "inception_date", "expiry_date", "currency", "annual_premium",
    ]
    return df[columns].reset_index(drop=True), quality


def clean_claims(raw: pd.DataFrame, policies: pd.DataFrame, rates: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Rules 8-16 on claims, against the cleaned policies; one quality entry per rule."""
    _require_columns(raw, CLAIM_COLUMNS, "claims")
    quality: list[dict] = []
    df = raw.copy()
    before = len(df)

    # 8. duplicate claim_id
    df, detail = _drop_duplicate_ids(df, "claim_id")
    quality.append(_entry("claims_duplicate_id", "claims", before - len(df), "excluded", detail))
    before = len(df)

    # 9. a status with a defined cost
    unknown = sorted(df.loc[~df["status"].isin(STATUSES), "status"].astype(str).unique())
    df = df[df["status"].isin(STATUSES)]
    quality.append(_entry(
        "claims_unknown_status", "claims", before - len(df), "excluded",
        f"status outside {list(STATUSES)}: {unknown or 'none found'}.",
    ))
    before = len(df)

    # 10. a claim belongs to a policy
    orphan = ~df["policy_id"].isin(policies["policy_id"])
    examples = sorted(df.loc[orphan, "policy_id"].astype(str).unique())[:3]
    df = df[~orphan]
    quality.append(_entry(
        "claims_orphan_policy", "claims", before - len(df), "excluded",
        f"orphan claim: policy_id not among the cleaned policies (e.g. {', '.join(examples) or 'none'}).",
    ))
    before = len(df)

    policy_columns = ["policy_id", "asset_id", "inception_date", "expiry_date", "currency"] + GROUP_ATTRIBUTES
    df = df.merge(
        policies[policy_columns].rename(columns={"currency": "policy_currency"}),
        on="policy_id", how="left", validate="many_to_one",
    )

    # 11. dates in either format
    day_first = _day_first_count(df["loss_date"]) + _day_first_count(df["reported_date"])
    df = df.assign(loss_date=parse_dates(df["loss_date"]), reported_date=parse_dates(df["reported_date"]))
    unreported = int(df["reported_date"].isna().sum())
    df = df[df["loss_date"].notna()]
    quality.append(_entry(
        "claims_unparseable_date", "claims", before - len(df), "excluded",
        f"loss_date in neither YYYY-MM-DD nor DD-MM-YYYY; {day_first} values were day-first. "
        f"reported_date feeds no figure, so {unreported} unparseable reported dates were kept as missing.",
    ))
    before = len(df)

    # 12. the loss must fall inside the policy term
    outside = (df["loss_date"] < df["inception_date"]) | (df["loss_date"] > df["expiry_date"])
    candidates = df.loc[outside, ["claim_id", "loss_date", "asset_id", "peril"]].merge(
        policies[["asset_id", "peril", "inception_date", "expiry_date"]], on=["asset_id", "peril"],
    )
    covered = candidates[
        (candidates["inception_date"] <= candidates["loss_date"])
        & (candidates["loss_date"] <= candidates["expiry_date"])
    ]["claim_id"].nunique()
    too_early = int((df.loc[outside, "loss_date"] < df.loc[outside, "inception_date"]).sum())
    df = df[~outside]
    quality.append(_entry(
        "claims_loss_date_outside_term", "claims", before - len(df), "excluded",
        f"loss_date outside the policy's [inception_date, expiry_date] ({too_early} before inception); "
        f"{covered} of them have another term of the same asset and peril covering the loss date: "
        "re-attribution candidates, not re-attributed in this version.",
    ))
    before = len(df)

    # 13. amounts must be numbers and not negative
    df = df.assign(
        paid_amount=pd.to_numeric(df["paid_amount"], errors="coerce"),
        reserve_amount=pd.to_numeric(df["reserve_amount"], errors="coerce"),
    )
    negative_paid = int((df["paid_amount"] < 0).sum())
    negative_reserve = int((df["reserve_amount"] < 0).sum())
    df = df[(df["paid_amount"] >= 0) & (df["reserve_amount"] >= 0)]
    quality.append(_entry(
        "claims_negative_amount", "claims", before - len(df), "excluded",
        f"paid_amount or reserve_amount negative or non-numeric ({negative_paid} negative paid, "
        f"{negative_reserve} negative reserve).",
    ))
    before = len(df)

    loss_month = month_key(df["loss_date"])

    # 14. a settled claim still carrying a reserve: kept, the reserve is ignored by definition
    settled_reserve = (df["status"] == "settled") & (df["reserve_amount"] > 0)
    ignored = to_dkk(
        df.loc[settled_reserve, "reserve_amount"], df.loc[settled_reserve, "currency"],
        loss_month[settled_reserve], rates,
    ).sum()
    quality.append(_entry(
        "claims_settled_with_reserve", "claims", int(settled_reserve.sum()), "noted",
        "settled claims with reserve_amount > 0: kept, the reserve is ignored because a settled claim costs what was paid.",
        amount_dkk=ignored,
    ))

    # 15. claim booked in another currency than its policy: kept, each amount converts with its own currency
    mixed = df["currency"] != df["policy_currency"]
    quality.append(_entry(
        "claims_currency_differs_from_policy", "claims", int(mixed.sum()), "noted",
        "claim currency differs from the policy's: kept, the claim converts with its own currency at the loss-month rate.",
    ))

    # 16. incurred amount into DKK at the loss-month rate
    incurred = incurred_amount(df["status"], df["paid_amount"], df["reserve_amount"])
    df = df.assign(incurred_dkk=to_dkk(incurred, df["currency"], loss_month, rates))
    foreign = int((df["currency"] != "DKK").sum())
    df = df[df["incurred_dkk"].notna()]
    quality.append(_entry(
        "claims_no_fx_rate", "claims", before - len(df), "excluded",
        f"no rate for the claim's currency in the loss month; {foreign} non-DKK claims converted.",
    ))

    columns = [
        "claim_id", "policy_id", "portfolio_id", "peril", "underwriting_year", "region", "asset_type",
        "incurred_dkk", "loss_date", "reported_date", "status", "currency", "paid_amount", "reserve_amount",
    ]
    return df[columns].reset_index(drop=True), quality


def load_dataset(data_dir: Path) -> Dataset:
    """Read the four CSVs from data_dir, apply the rules and log every quality entry."""
    data_dir = Path(data_dir)
    assets = pd.read_csv(data_dir / "assets.csv", dtype={c: str for c in ["asset_id"] + ASSET_ATTRIBUTES})
    raw_policies = pd.read_csv(data_dir / "policies.csv", dtype=str)  # text in, typed by the rules
    raw_claims = pd.read_csv(data_dir / "claims.csv", dtype=str)
    rates = load_rates(data_dir / "fx_rates.csv")

    _require_columns(assets, ASSET_COLUMNS, "assets")
    if assets["asset_id"].isna().any() or assets["asset_id"].duplicated().any():
        raise ValueError("assets.csv: asset_id must be present and unique")
    if assets[ASSET_ATTRIBUTES].isna().any().any():
        raise ValueError("assets.csv: portfolio_id, region and asset_type must be present on every row")

    source_rows = {
        "assets": len(assets), "policies": len(raw_policies), "claims": len(raw_claims), "fx_rates": len(rates),
    }
    policies, policy_quality = clean_policies(raw_policies, assets, rates)
    claims, claim_quality = clean_claims(raw_claims, policies, rates)
    quality = policy_quality + claim_quality

    for entry in quality:
        amount = "" if entry["amount_dkk"] is None else f" ({entry['amount_dkk']:,.2f} DKK)"
        log.info("quality %s: %s %d rows%s: %s", entry["rule"], entry["action"], entry["rows"], amount, entry["detail"])
    log.info(
        "loaded %s: policies %d of %d used, claims %d of %d used, %d assets, %d fx rates",
        data_dir, len(policies), len(raw_policies), len(claims), len(raw_claims), len(assets), len(rates),
    )
    return Dataset(assets=assets, policies=policies, claims=claims, rates=rates, quality=quality, source_rows=source_rows)
