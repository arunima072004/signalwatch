"""tests/test_preprocessing.py — Tests for src/data/preprocessing.py"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.data.preprocessing import preprocess


def test_preprocess_returns_dataframe(raw_df_minimal):
    cleaned, log = preprocess(raw_df_minimal)
    assert isinstance(cleaned, pd.DataFrame)
    assert len(cleaned) > 0


def test_preprocess_explodes_multidates(raw_df_minimal):
    """Rows with comma-separated dateSeen should be exploded to multiple rows."""
    cleaned, _ = preprocess(raw_df_minimal)
    # raw_df_minimal row 0 has 2 dates → 2 rows; row 2 has 3 dates → 3 rows
    # So cleaned should have more rows than the original 5
    assert len(cleaned) > 5


def test_preprocess_timestamps_are_utc(raw_df_minimal):
    cleaned, _ = preprocess(raw_df_minimal)
    assert pd.api.types.is_datetime64_any_dtype(cleaned["observed_at"])
    # Should be UTC-aware
    assert cleaned["observed_at"].dt.tz is not None


def test_preprocess_price_is_positive(raw_df_minimal):
    cleaned, _ = preprocess(raw_df_minimal)
    assert (cleaned["price"] > 0).all()


def test_preprocess_no_negative_prices(raw_df_minimal):
    cleaned, _ = preprocess(raw_df_minimal)
    assert not (cleaned["price"] < 0).any()


def test_preprocess_is_sale_is_bool(raw_df_minimal):
    cleaned, _ = preprocess(raw_df_minimal)
    assert cleaned["is_sale"].dtype == bool


def test_preprocess_currency_is_usd(raw_df_minimal):
    cleaned, _ = preprocess(raw_df_minimal)
    assert (cleaned["currency"] == "USD").all()


def test_preprocess_no_empty_product_id(raw_df_minimal):
    cleaned, _ = preprocess(raw_df_minimal)
    assert not (cleaned["product_id"].str.strip() == "").any()


def test_preprocess_no_empty_merchant(raw_df_minimal):
    cleaned, _ = preprocess(raw_df_minimal)
    assert not (cleaned["merchant"].str.strip() == "").any()


def test_preprocess_output_columns(raw_df_minimal):
    """All expected output columns must be present."""
    from src.data.preprocessing import _OUTPUT_COLUMNS
    cleaned, _ = preprocess(raw_df_minimal)
    for col in _OUTPUT_COLUMNS:
        assert col in cleaned.columns, f"Missing output column: {col}"


def test_preprocess_no_duplicate_observations(raw_df_minimal):
    """No exact (product_id, merchant, observed_at, price) duplicates."""
    cleaned, _ = preprocess(raw_df_minimal)
    dupes = cleaned.duplicated(
        subset=["product_id", "merchant", "observed_at", "price"]
    ).sum()
    assert dupes == 0


def test_preprocess_filtering_log_has_steps(raw_df_minimal):
    _, log = preprocess(raw_df_minimal)
    assert len(log.steps) > 0


def test_preprocess_price_fallback_to_amountmax():
    """When price_min is empty, price should fall back to price_max."""
    df = pd.DataFrame(
        {
            "id": ["P099"],
            "prices.amountMax": ["49.99"],
            "prices.amountMin": [""],        # empty → fallback to max
            "prices.availability": ["Yes"],
            "prices.condition": ["New"],
            "prices.currency": ["USD"],
            "prices.dateSeen": ["2017-06-01T00:00:00Z"],
            "prices.isSale": ["FALSE"],
            "prices.merchant": ["TestMerchant"],
            "prices.shipping": ["Free"],
            "prices.sourceURLs": [""],
            "asins": [""],
            "brand": ["BrandX"],
            "categories": ["Electronics"],
            "dateAdded": ["2017-01-01T00:00:00Z"],
            "dateUpdated": ["2017-06-01T00:00:00Z"],
            "ean": [""],
            "imageURLs": [""],
            "keys": [""],
            "manufacturer": ["MfgX"],
            "manufacturerNumber": ["MX1"],
            "name": ["Product X"],
            "primaryCategories": ["Electronics"],
            "sourceURLs": [""],
            "upc": [""],
            "weight": [""],
        }
    )
    cleaned, _ = preprocess(df)
    assert len(cleaned) == 1
    assert cleaned.iloc[0]["price"] == pytest.approx(49.99)


def test_preprocess_drops_non_usd_currency():
    """Non-USD rows should be dropped."""
    df = pd.DataFrame(
        {
            "id": ["P001", "P002"],
            "prices.amountMax": ["99.99", "89.99"],
            "prices.amountMin": ["99.99", "89.99"],
            "prices.availability": ["Yes", "Yes"],
            "prices.condition": ["New", "New"],
            "prices.currency": ["USD", "GBP"],
            "prices.dateSeen": ["2017-01-01T00:00:00Z", "2017-01-01T00:00:00Z"],
            "prices.isSale": ["FALSE", "FALSE"],
            "prices.merchant": ["Amazon", "Amazon"],
            "prices.shipping": ["", ""],
            "prices.sourceURLs": ["", ""],
            "asins": ["", ""],
            "brand": ["B", "B"],
            "categories": ["E", "E"],
            "dateAdded": ["2017-01-01T00:00:00Z", "2017-01-01T00:00:00Z"],
            "dateUpdated": ["2017-01-01T00:00:00Z", "2017-01-01T00:00:00Z"],
            "ean": ["", ""],
            "imageURLs": ["", ""],
            "keys": ["", ""],
            "manufacturer": ["M", "M"],
            "manufacturerNumber": ["", ""],
            "name": ["N", "N"],
            "primaryCategories": ["E", "E"],
            "sourceURLs": ["", ""],
            "upc": ["", ""],
            "weight": ["", ""],
        }
    )
    cleaned, _ = preprocess(df)
    assert len(cleaned) == 1
    assert cleaned.iloc[0]["currency"] == "USD"
