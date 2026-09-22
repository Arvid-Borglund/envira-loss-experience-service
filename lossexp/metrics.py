"""Business definitions from docs/BRIEF.md, applied per group.

- Incurred loss: settled -> paid; open -> paid + reserve; declined and withdrawn -> 0.
- Earned premium: the full annual premium (no pro-rata).
- Loss ratio: incurred loss / earned premium, both in DKK; undefined (NaN) without premium.

These constants and functions are the single home of the definitions; other
layers pass frames through and never repeat the rules.
"""

import numpy as np
import pandas as pd

STATUSES = ("settled", "open", "declined", "withdrawn")
PERILS = ("fire", "flood", "hail", "storm", "subsidence")  # informational; groups come from the data

METRIC_COLUMNS = [
    "policy_count",
    "earned_premium_dkk",
    "incurred_loss_dkk",
    "loss_ratio",
    "claim_count",
    "largest_claim_dkk",
]


def normalise_peril(values: pd.Series) -> pd.Series:
    """Strip surrounding whitespace and lower-case, so 'SUBSIDENCE' and ' flood' join their peril."""
    return values.str.strip().str.lower()


def incurred_amount(status: pd.Series, paid: pd.Series, reserve: pd.Series) -> pd.Series:
    """Incurred loss per claim, in the claim's own currency.

    Raises ValueError on a status outside STATUSES: an unknown status has no
    defined cost and must be excluded upstream, never silently zeroed.
    """
    unknown = ~status.isin(STATUSES)
    if unknown.any():
        raise ValueError(f"unknown claim status: {sorted(status[unknown].astype(str).unique())}")
    paid = paid.astype(float)
    reserve = reserve.astype(float)
    values = np.select(
        [status.eq("settled").to_numpy(), status.eq("open").to_numpy()],
        [paid.to_numpy(), (paid + reserve).to_numpy()],
        default=0.0,
    )
    return pd.Series(values, index=status.index, dtype=float)


def loss_experience(policies: pd.DataFrame, claims: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """One row per group present in `policies`, sorted by the `by` columns.

    policies needs policy_id, premium_dkk and the `by` columns; claims needs
    claim_id, incurred_dkk and the `by` columns. A group without claims gets
    zeros. Claims in a group without policies cannot happen for claims that
    belong to a policy, so they raise ValueError instead of being dropped.
    """
    if not by:  # a grand total: group on a constant and drop it again
        policies = policies.assign(_all=0)
        claims = claims.assign(_all=0)
        return loss_experience(policies, claims, ["_all"]).drop(columns="_all")

    grouped_policies = policies.groupby(by, sort=True, dropna=False).agg(
        policy_count=("policy_id", "size"),
        earned_premium_dkk=("premium_dkk", "sum"),
    )
    grouped_claims = claims.groupby(by, sort=True, dropna=False).agg(
        incurred_loss_dkk=("incurred_dkk", "sum"),
        claim_count=("claim_id", "size"),
        largest_claim_dkk=("incurred_dkk", "max"),
    )
    without_policies = grouped_claims.index.difference(grouped_policies.index)
    if len(without_policies):
        raise ValueError(f"claims in groups without policies: {without_policies.tolist()[:5]}")

    out = grouped_policies.join(grouped_claims, how="left")
    out["incurred_loss_dkk"] = out["incurred_loss_dkk"].fillna(0.0).astype(float)
    out["claim_count"] = out["claim_count"].fillna(0).astype(int)
    out["largest_claim_dkk"] = out["largest_claim_dkk"].fillna(0.0).astype(float)
    out["earned_premium_dkk"] = out["earned_premium_dkk"].astype(float)
    out["policy_count"] = out["policy_count"].astype(int)
    premium = out["earned_premium_dkk"]
    out["loss_ratio"] = (out["incurred_loss_dkk"] / premium.where(premium > 0)).astype(float)
    return out.reset_index()[list(by) + METRIC_COLUMNS]
