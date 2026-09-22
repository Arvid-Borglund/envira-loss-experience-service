"""Join layer shared by the API and any CLI.

The dataset is loaded and cleaned once; filters are applied at query time on
the cleaned frames because the volumes are tiny. This layer also owns the
JSON shapes and the rounding (DKK to 2 decimals, ratios to 4), so the API
stays a thin HTTP mapping.
"""

import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from lossexp.data import Dataset, load_dataset
from lossexp.metrics import loss_experience

RANKING = "loss_ratio desc, incurred_loss_dkk desc, portfolio_id asc; portfolios without premium last"
FILTERS = ("underwriting_year", "region", "asset_type")


class PortfolioNotFound(KeyError):
    """No cleaned policy belongs to that portfolio id."""

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


class InvalidFilter(ValueError):
    """A filter value the data does not contain; the message lists the valid values."""


def _money(value: float) -> float:
    return round(float(value), 2)


def _ratio(value: float | None) -> float | None:
    return None if value is None or math.isnan(value) else round(float(value), 4)


def _metrics_json(row: dict) -> dict:
    return {
        "policy_count": int(row["policy_count"]),
        "earned_premium_dkk": _money(row["earned_premium_dkk"]),
        "incurred_loss_dkk": _money(row["incurred_loss_dkk"]),
        "loss_ratio": _ratio(row["loss_ratio"]),
        "claim_count": int(row["claim_count"]),
        "largest_claim_dkk": _money(row["largest_claim_dkk"]),
    }


EMPTY_METRICS = {
    "policy_count": 0, "earned_premium_dkk": 0.0, "incurred_loss_dkk": 0.0,
    "loss_ratio": None, "claim_count": 0, "largest_claim_dkk": 0.0,
}


@dataclass
class LossIndex:
    """The cleaned dataset plus the valid values every filter can take."""

    dataset: Dataset
    portfolio_ids: list[str]
    underwriting_years: list[int]
    regions: list[str]
    asset_types: list[str]

    def _select(
        self, portfolio_id: str | None, underwriting_year: int | None, region: str | None, asset_type: str | None,
    ) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
        """Validate the filters, then return the matching policies and claims and the filters echoed back."""
        filters = {"underwriting_year": underwriting_year, "region": region, "asset_type": asset_type}
        valid = {"underwriting_year": self.underwriting_years, "region": self.regions, "asset_type": self.asset_types}
        for name, value in filters.items():
            if value is not None and value not in valid[name]:
                raise InvalidFilter(f"unknown {name} {value}; valid values: {', '.join(map(str, valid[name]))}")
        policies, claims = self.dataset.policies, self.dataset.claims
        if portfolio_id is not None:
            if portfolio_id not in self.portfolio_ids:
                raise PortfolioNotFound(f"unknown portfolio {portfolio_id}")
            policies = policies[policies["portfolio_id"] == portfolio_id]
            claims = claims[claims["portfolio_id"] == portfolio_id]
        for name, value in filters.items():
            if value is not None:
                policies = policies[policies[name] == value]
                claims = claims[claims[name] == value]
        return policies, claims, filters

    def portfolio(
        self, portfolio_id: str, *, underwriting_year: int | None = None,
        region: str | None = None, asset_type: str | None = None,
    ) -> dict:
        """Loss experience per peril and in total for one portfolio."""
        policies, claims, filters = self._select(portfolio_id, underwriting_year, region, asset_type)
        perils = loss_experience(policies, claims, ["peril"]).to_dict("records")
        total = loss_experience(policies, claims, []).to_dict("records")
        return {
            "portfolio_id": portfolio_id,
            "filters": filters,
            "perils": [{"peril": row["peril"], **_metrics_json(row)} for row in perils],
            "total": _metrics_json(total[0]) if total else dict(EMPTY_METRICS),
        }

    def compare(
        self, *, underwriting_year: int | None = None, region: str | None = None, asset_type: str | None = None,
    ) -> dict:
        """Every portfolio with policies under the filters, ranked per RANKING, with its worst peril."""
        policies, claims, filters = self._select(None, underwriting_year, region, asset_type)
        totals = loss_experience(policies, claims, ["portfolio_id"])
        totals["_no_premium"] = totals["loss_ratio"].isna()
        totals = totals.sort_values(
            ["_no_premium", "loss_ratio", "incurred_loss_dkk", "portfolio_id"],
            ascending=[True, False, False, True], na_position="last",
        )
        per_peril = loss_experience(policies, claims, ["portfolio_id", "peril"]).dropna(subset=["loss_ratio"])
        worst = (
            per_peril.sort_values(["portfolio_id", "loss_ratio", "peril"], ascending=[True, False, True])
            .drop_duplicates("portfolio_id")
            .set_index("portfolio_id")
        )
        rows = []
        for rank, row in enumerate(totals.to_dict("records"), start=1):
            pid = row["portfolio_id"]
            worst_peril = None
            if pid in worst.index:
                worst_peril = {"peril": worst.at[pid, "peril"], "loss_ratio": _ratio(worst.at[pid, "loss_ratio"])}
            rows.append({"rank": rank, "portfolio_id": pid, **_metrics_json(row), "worst_peril": worst_peril})
        return {"ranking": RANKING, "filters": filters, "portfolios": rows}

    def _used_rows(self) -> dict:
        return {"policies": int(len(self.dataset.policies)), "claims": int(len(self.dataset.claims))}

    def quality(self) -> dict:
        """What was excluded, normalised or noted, in the order the rules ran."""
        issues = [
            {**entry, "amount_dkk": None if entry["amount_dkk"] is None else _money(entry["amount_dkk"])}
            for entry in self.dataset.quality
        ]
        return {"source_rows": dict(self.dataset.source_rows), "used_rows": self._used_rows(), "issues": issues}

    def summary(self) -> dict:
        """Row counts and the portfolios and perils present, for /health."""
        return {
            "source_rows": dict(self.dataset.source_rows),
            "used_rows": self._used_rows(),
            "portfolios": list(self.portfolio_ids),
            "perils": sorted(self.dataset.policies["peril"].unique().tolist()),
        }


def build_index(data_dir: Path) -> LossIndex:
    """Load and clean the data once and record the valid filter values."""
    dataset = load_dataset(data_dir)
    policies = dataset.policies
    return LossIndex(
        dataset=dataset,
        portfolio_ids=sorted(policies["portfolio_id"].unique().tolist()),
        underwriting_years=sorted(int(y) for y in policies["underwriting_year"].unique()),
        regions=sorted(policies["region"].unique().tolist()),
        asset_types=sorted(policies["asset_type"].unique().tolist()),
    )
