"""Currency conversion: the rate of the chosen month, DKK as identity, and a missing rate that is never zero."""

import math

import pandas as pd
import pytest

from lossexp.fx import load_rates, month_key, to_dkk

RATES = pd.DataFrame(
    [
        {"month": "2024-03", "currency": "EUR", "rate_dkk_per_unit": 7.45},
        {"month": "2024-04", "currency": "EUR", "rate_dkk_per_unit": 7.50},
    ]
)


def convert(amounts, currencies, months):
    return to_dkk(pd.Series(amounts), pd.Series(currencies), pd.Series(months), RATES)


def test_month_key_formats_year_and_month():
    dates = pd.to_datetime(pd.Series(["2024-03-26", "2023-12-01"]))
    assert month_key(dates).tolist() == ["2024-03", "2023-12"]


def test_to_dkk_uses_the_rate_of_the_given_month():
    assert convert([100.0, 100.0], ["EUR", "EUR"], ["2024-03", "2024-04"]).tolist() == pytest.approx([745.0, 750.0])


def test_to_dkk_treats_dkk_as_one_even_without_a_rate_row():
    assert convert([123.4], ["DKK"], ["2019-01"]).tolist() == [123.4]


def test_to_dkk_gives_nan_not_zero_for_a_missing_rate():
    converted = convert([100.0], ["EUR"], ["2024-05"])
    assert math.isnan(converted.iloc[0])


def test_load_rates_rejects_duplicate_month_and_currency(tmp_path):
    path = tmp_path / "fx_rates.csv"
    path.write_text("month,currency,rate_dkk_per_unit\n2024-03,EUR,7.45\n2024-03,EUR,7.46\n")
    with pytest.raises(ValueError):
        load_rates(path)
