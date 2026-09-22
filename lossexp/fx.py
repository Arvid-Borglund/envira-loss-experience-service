"""Currency conversion into DKK with the month-end rate table.

Rule: an amount is converted at the rate of the month chosen for it (the caller
picks the month: inception month for premiums, loss month for claims). A missing
rate is never zero: the result is NaN and the caller excludes and counts the row.
DKK always converts at 1.0, even if the table lacks a DKK row.
"""

from pathlib import Path

import pandas as pd

RATE_COLUMNS = ("month", "currency", "rate_dkk_per_unit")


def month_key(dates: pd.Series) -> pd.Series:
    """'YYYY-MM' for each datetime64 value; NaT becomes NaN."""
    return dates.dt.strftime("%Y-%m")


def load_rates(path: Path) -> pd.DataFrame:
    """Read fx_rates.csv (month, currency, rate_dkk_per_unit).

    Raises ValueError when a (month, currency) pair occurs twice: load order
    must never decide which rate wins.
    """
    rates = pd.read_csv(path, dtype={"month": str, "currency": str})
    missing = set(RATE_COLUMNS) - set(rates.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")
    rates = rates[list(RATE_COLUMNS)].copy()
    rates["month"] = rates["month"].str.strip()
    rates["currency"] = rates["currency"].str.strip().str.upper()
    rates["rate_dkk_per_unit"] = pd.to_numeric(rates["rate_dkk_per_unit"], errors="raise")
    duplicated = rates.duplicated(["month", "currency"], keep=False)
    if duplicated.any():
        keys = rates.loc[duplicated, ["month", "currency"]].drop_duplicates()
        raise ValueError(
            f"{path}: {int(duplicated.sum())} rows share a (month, currency) key: "
            f"{keys.to_records(index=False).tolist()}"
        )
    if (rates["rate_dkk_per_unit"] <= 0).any():
        raise ValueError(f"{path}: rates must be positive")
    return rates.reset_index(drop=True)


def to_dkk(
    amount: pd.Series, currency: pd.Series, month: pd.Series, rates: pd.DataFrame
) -> pd.Series:
    """amount * rate_dkk_per_unit for (month, currency), aligned on amount's index.

    NaN where the table has no rate for that month and currency; DKK is 1.0
    regardless of the table.
    """
    lookup = rates.set_index(["month", "currency"])["rate_dkk_per_unit"]
    keys = pd.MultiIndex.from_arrays([month.to_numpy(), currency.to_numpy()])
    rate = pd.Series(lookup.reindex(keys).to_numpy(dtype=float), index=amount.index)
    rate = rate.where(currency.to_numpy() != "DKK", 1.0)
    return pd.to_numeric(amount, errors="coerce").astype(float) * rate
