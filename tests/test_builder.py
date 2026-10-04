"""tests/test_builder.py — Tests for src/timeseries/builder.py"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.timeseries.builder import (
    TimeSeriesCatalogue,
    build_time_series,
    get_series,
    iter_usable_series,
)


def test_build_time_series_returns_catalogue(cleaned_df):
    cat = build_time_series(cleaned_df, min_observations=2)
    assert isinstance(cat, TimeSeriesCatalogue)


def test_build_time_series_series_df_shape(cleaned_df):
    cat = build_time_series(cleaned_df)
    # Should have same number of rows as cleaned_df (no rows added or removed)
    assert len(cat.series_df) == len(cleaned_df)


def test_build_time_series_sorted_chronologically(cleaned_df):
    """Each PM group must be sorted ascending by observed_at."""
    cat = build_time_series(cleaned_df)
    for (pid, merch), group in cat.series_df.groupby(["product_id", "merchant"]):
        ts = group["observed_at"].values
        assert all(ts[i] <= ts[i + 1] for i in range(len(ts) - 1)), (
            f"Group ({pid}, {merch}) is not sorted chronologically."
        )


def test_build_time_series_previous_price(cleaned_df):
    """previous_price at index 0 must be NaN; at index 1 must equal price at index 0."""
    cat = build_time_series(cleaned_df)
    for (pid, merch), group in cat.series_df.groupby(["product_id", "merchant"]):
        g = group.reset_index(drop=True)
        assert pd.isna(g.loc[0, "previous_price"]), (
            f"({pid},{merch}): previous_price at index 0 should be NaN"
        )
        if len(g) > 1:
            assert g.loc[1, "previous_price"] == pytest.approx(g.loc[0, "price"])


def test_build_time_series_absolute_change(cleaned_df):
    """absolute_change = price - previous_price."""
    cat = build_time_series(cleaned_df)
    df = cat.series_df.dropna(subset=["previous_price"])
    for _, row in df.iterrows():
        expected = row["price"] - row["previous_price"]
        assert row["absolute_change"] == pytest.approx(expected, abs=1e-6)


def test_build_time_series_percentage_change(cleaned_df):
    """percentage_change = absolute_change / previous_price * 100."""
    cat = build_time_series(cleaned_df)
    df = cat.series_df.dropna(subset=["previous_price", "absolute_change"])
    for _, row in df.iterrows():
        expected = row["absolute_change"] / row["previous_price"] * 100.0
        assert row["percentage_change"] == pytest.approx(expected, abs=1e-4)


def test_build_time_series_observation_index_starts_zero(cleaned_df):
    cat = build_time_series(cleaned_df)
    for (pid, merch), group in cat.series_df.groupby(["product_id", "merchant"]):
        g = group.reset_index(drop=True)
        assert g.loc[0, "observation_index"] == 0


def test_build_time_series_days_since_previous(cleaned_df):
    """days_since_previous at index 0 must be NaN; at index 1 must be > 0."""
    cat = build_time_series(cleaned_df)
    for (pid, merch), group in cat.series_df.groupby(["product_id", "merchant"]):
        g = group.reset_index(drop=True)
        assert pd.isna(g.loc[0, "days_since_previous"])
        if len(g) > 1:
            assert g.loc[1, "days_since_previous"] > 0


def test_build_time_series_usable_pairs(cleaned_df):
    """Pairs with <5 observations should not appear in usable_pairs."""
    cat = build_time_series(cleaned_df, min_observations=5)
    # cleaned_df has 3 obs per pair → none should be usable with threshold 5
    assert len(cat.usable_pairs) == 0


def test_build_time_series_usable_pairs_threshold_2(cleaned_df):
    """With threshold=2, pairs with 3 obs should be usable."""
    cat = build_time_series(cleaned_df, min_observations=2)
    assert len(cat.usable_pairs) == 2  # two PM pairs each with 3 obs


def test_get_series_returns_correct_pair(cleaned_df):
    cat = build_time_series(cleaned_df)
    s = get_series(cat, "P001", "Amazon.com")
    assert len(s) == 3
    assert (s["product_id"] == "P001").all()
    assert (s["merchant"] == "Amazon.com").all()


def test_get_series_missing_pair_returns_empty(cleaned_df):
    cat = build_time_series(cleaned_df)
    s = get_series(cat, "NONEXISTENT", "NoMerchant")
    assert s.empty


def test_iter_usable_series(cleaned_df):
    cat = build_time_series(cleaned_df, min_observations=2)
    pairs = [(pid, merch) for pid, merch, _ in iter_usable_series(cat)]
    # Should yield both pairs
    assert len(pairs) == 2
    assert ("P001", "Amazon.com") in pairs
    assert ("P002", "BestBuy") in pairs


def test_build_time_series_no_future_leakage(cleaned_df):
    """
    Critical: at observation index i, previous_price must only use
    information from obs 0..i-1.  Verified by checking that
    previous_price[i] == price[i-1].
    """
    cat = build_time_series(cleaned_df)
    df = cat.series_df
    for (pid, merch), group in df.groupby(["product_id", "merchant"]):
        g = group.sort_values("observed_at").reset_index(drop=True)
        for i in range(1, len(g)):
            assert g.loc[i, "previous_price"] == pytest.approx(
                g.loc[i - 1, "price"]
            ), f"Future leakage detected at ({pid},{merch}) index {i}"


def test_build_time_series_summary_columns(cleaned_df):
    cat = build_time_series(cleaned_df)
    required_cols = [
        "product_id", "merchant", "n_observations",
        "first_observed", "last_observed", "price_mean",
    ]
    for col in required_cols:
        assert col in cat.summary.columns


def test_build_time_series_save_load_roundtrip(cleaned_df, tmp_path):
    from src.timeseries.builder import load_series, save_series
    cat = build_time_series(cleaned_df)
    save_series(cat, tmp_path)
    cat2 = load_series(tmp_path)
    assert len(cat2.series_df) == len(cat.series_df)
    assert len(cat2.summary) == len(cat.summary)
