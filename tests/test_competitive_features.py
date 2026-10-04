"""tests/test_competitive_features.py — Tests for competitive_features.py"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.features.competitive_features import (
    _latest_prices_before_t,
    compute_competitive_features,
)
from src.timeseries.builder import build_time_series
from src.features.price_features import compute_all_price_features


@pytest.fixture
def multi_merchant_df():
    """
    Two merchants selling the same product P001.
    Amazon.com: prices 100, 90, 80 at T1, T2, T3
    BestBuy:    prices 110, 100     at T1, T2
    """
    dates_amazon = pd.to_datetime(
        ["2017-01-01", "2017-01-15", "2017-02-01"], utc=True
    )
    dates_bestbuy = pd.to_datetime(["2017-01-05", "2017-01-20"], utc=True)
    rows = []
    for d, p in zip(dates_amazon, [100.0, 90.0, 80.0]):
        rows.append(
            dict(
                product_id="P001", merchant="Amazon.com", observed_at=d,
                price=p, price_min=p, price_max=p + 5,
                is_sale=False, availability="Yes", condition="New",
                offer="", product_name="Alpha", brand="BrandA",
                manufacturer="MfgA", manufacturer_number="MN1",
                category="Electronics", source_url="",
                previous_price=None, absolute_change=None,
                percentage_change=None, days_since_previous=None,
                observation_index=0,
            )
        )
    for d, p in zip(dates_bestbuy, [110.0, 100.0]):
        rows.append(
            dict(
                product_id="P001", merchant="BestBuy", observed_at=d,
                price=p, price_min=p, price_max=p + 5,
                is_sale=False, availability="Yes", condition="New",
                offer="", product_name="Alpha", brand="BrandA",
                manufacturer="MfgA", manufacturer_number="MN1",
                category="Electronics", source_url="",
                previous_price=None, absolute_change=None,
                percentage_change=None, days_since_previous=None,
                observation_index=0,
            )
        )
    df = pd.DataFrame(rows)
    df["previous_price"] = pd.to_numeric(df["previous_price"], errors="coerce")
    df["absolute_change"] = pd.to_numeric(df["absolute_change"], errors="coerce")
    df["percentage_change"] = pd.to_numeric(df["percentage_change"], errors="coerce")
    df["days_since_previous"] = pd.to_numeric(df["days_since_previous"], errors="coerce")
    return df


def test_no_future_leakage_in_competitor_prices(multi_merchant_df):
    """
    For Amazon.com at T1 (2017-01-01), no competitor prices should be available
    because BestBuy's first observation is at T=2017-01-05 > T1.
    """
    t1 = pd.Timestamp("2017-01-01", tz="UTC")
    comp = _latest_prices_before_t(multi_merchant_df, t1, "Amazon.com")
    assert comp.empty, (
        "Competitor prices must not include observations at or after T1"
    )


def test_competitor_prices_correctly_found(multi_merchant_df):
    """
    For Amazon.com at T3 (2017-02-01), BestBuy's latest price before T3
    is $100.00 (from 2017-01-20).
    """
    t3 = pd.Timestamp("2017-02-01", tz="UTC")
    comp = _latest_prices_before_t(multi_merchant_df, t3, "Amazon.com")
    assert len(comp) == 1
    assert comp.iloc[0]["merchant"] == "BestBuy"
    assert comp.iloc[0]["price"] == pytest.approx(100.0)


def test_compute_competitive_features_no_leakage(multi_merchant_df):
    """
    At each observation, only competitor obs strictly BEFORE the current
    timestamp should influence competitive features.
    """
    result = compute_competitive_features(multi_merchant_df)

    # Amazon.com at T1 (2017-01-01): no competitors yet → competitor_count=0
    amazon_t1 = result[
        (result["merchant"] == "Amazon.com") &
        (result["observed_at"] == pd.Timestamp("2017-01-01", tz="UTC"))
    ]
    assert len(amazon_t1) == 1
    assert amazon_t1.iloc[0]["competitor_count"] == 0

    # Amazon.com at T2 (2017-01-15): BestBuy had obs on 2017-01-05 → 1 competitor
    amazon_t2 = result[
        (result["merchant"] == "Amazon.com") &
        (result["observed_at"] == pd.Timestamp("2017-01-15", tz="UTC"))
    ]
    assert len(amazon_t2) == 1
    assert amazon_t2.iloc[0]["competitor_count"] == 1
    assert amazon_t2.iloc[0]["competitor_price_median"] == pytest.approx(110.0)


def test_single_merchant_product_has_nan_comp_features(cleaned_df):
    """
    A product with only one merchant should have NaN competitive features.
    """
    # P003 in cleaned_df has only one merchant
    single = cleaned_df[cleaned_df["product_id"] == "P001"].copy()
    # Keep only one merchant
    single = single[single["merchant"] == "Amazon.com"].copy()
    cat = build_time_series(single, min_observations=2)
    pf = compute_all_price_features(cat.series_df)
    result = compute_competitive_features(pf)
    assert result["competitor_count"].eq(0).all()
    assert result["competitor_price_median"].isna().all()


def test_competitive_features_output_columns(multi_merchant_df):
    result = compute_competitive_features(multi_merchant_df)
    expected_cols = [
        "competitor_count", "competitor_price_min", "competitor_price_max",
        "competitor_price_mean", "competitor_price_median",
        "price_vs_comp_median", "price_vs_comp_mean",
        "relative_price_position", "is_cheapest", "is_most_expensive",
        "competitors_changed_7d", "competitor_direction_7d",
    ]
    for col in expected_cols:
        assert col in result.columns, f"Missing column: {col}"
