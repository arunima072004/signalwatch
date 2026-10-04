"""tests/test_price_features.py — Tests for src/features/price_features.py"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.features.price_features import compute_price_features, compute_all_price_features
from src.timeseries.builder import build_time_series


@pytest.fixture
def series_with_derived(simple_series):
    """simple_series with builder-derived columns added."""
    from src.timeseries.builder import build_time_series
    cat = build_time_series(simple_series, min_observations=2)
    return cat.series_df


def test_compute_price_features_returns_dataframe(series_with_derived):
    df = compute_price_features(series_with_derived)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == len(series_with_derived)


def test_log_price_is_log_of_price(series_with_derived):
    df = compute_price_features(series_with_derived)
    for _, row in df.iterrows():
        if pd.notna(row["price"]) and row["price"] > 0:
            assert row["log_price"] == pytest.approx(np.log(row["price"]), rel=1e-6)


def test_log_price_diff_equals_log_price_lag1(series_with_derived):
    """log_price_diff[i] = log_price[i] - log_price[i-1]."""
    df = compute_price_features(series_with_derived).reset_index(drop=True)
    for i in range(1, len(df)):
        expected = df.loc[i, "log_price"] - df.loc[i - 1, "log_price"]
        assert df.loc[i, "log_price_diff"] == pytest.approx(expected, abs=1e-9)


def test_log_price_diff_first_row_is_nan(series_with_derived):
    df = compute_price_features(series_with_derived).reset_index(drop=True)
    assert pd.isna(df.loc[0, "log_price_diff"])


def test_rolling_mean_uses_only_past_data(series_with_derived):
    """
    Rolling mean at position i should equal mean(log_price[max(0,i-w+1):i+1]).
    Verifies no future leakage in rolling stats.
    """
    df = compute_price_features(series_with_derived, windows=[3]).reset_index(drop=True)
    for i in range(2, len(df)):
        window_vals = df["log_price"].iloc[max(0, i - 2): i + 1]
        expected = window_vals.mean()
        assert df.loc[i, "rolling_mean_3"] == pytest.approx(expected, abs=1e-9)


def test_rolling_columns_present(series_with_derived):
    df = compute_price_features(series_with_derived, windows=[3, 5])
    for w in [3, 5]:
        for suffix in [f"rolling_mean_{w}", f"rolling_std_{w}",
                       f"rolling_median_{w}", f"rolling_volatility_{w}"]:
            assert suffix in df.columns, f"Missing column: {suffix}"


def test_expanding_zscore_defined_from_index_2(series_with_derived):
    """Expanding z-score requires min_periods=3, so first 2 rows should be NaN."""
    df = compute_price_features(series_with_derived).reset_index(drop=True)
    # First 2 rows should be NaN (min_periods=3 means we need 3 obs)
    assert pd.isna(df.loc[0, "expanding_zscore"])
    assert pd.isna(df.loc[1, "expanding_zscore"])


def test_price_direction_sign(series_with_derived):
    """price_direction should match sign of absolute_change."""
    from src.timeseries.builder import build_time_series
    cat = build_time_series(simple_series_fixture(), min_observations=2)
    s = cat.series_df
    df = compute_price_features(s).reset_index(drop=True)
    for _, row in df.iterrows():
        ac = row["absolute_change"]
        pd_val = row["price_direction"]
        if pd.isna(ac):
            assert pd_val == 0
        elif ac > 0:
            assert pd_val == 1
        elif ac < 0:
            assert pd_val == -1
        else:
            assert pd_val == 0


def simple_series_fixture() -> pd.DataFrame:
    prices = [100.0, 100.5, 99.8, 100.2, 100.1, 100.0, 75.0, 74.8, 75.2, 74.9]
    dates = pd.date_range("2017-01-01", periods=10, freq="7D", tz="UTC")
    return pd.DataFrame(
        {
            "product_id": ["P001"] * 10,
            "merchant": ["Amazon.com"] * 10,
            "observed_at": dates,
            "price": prices,
            "price_min": prices,
            "price_max": [p + 2 for p in prices],
            "is_sale": [False] * 5 + [True] * 5,
            "availability": ["Yes"] * 10,
            "condition": ["New"] * 10,
            "offer": [""] * 10,
            "product_name": ["Alpha"] * 10,
            "brand": ["BrandA"] * 10,
            "manufacturer": ["MfgA"] * 10,
            "manufacturer_number": ["MN1"] * 10,
            "category": ["Electronics"] * 10,
            "source_url": ["http://amazon.com"] * 10,
        }
    )


def test_compute_all_price_features_multi_group(cleaned_df):
    cat = build_time_series(cleaned_df, min_observations=2)
    df = compute_all_price_features(cat.series_df)
    assert len(df) == len(cleaned_df)
    assert "log_price" in df.columns
    assert "log_price_diff" in df.columns
