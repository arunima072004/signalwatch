"""
tests/conftest.py
==================
Shared pytest fixtures used across all test modules.
"""

from __future__ import annotations

from datetime import timezone

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Minimal raw DataFrame (mimics the Datafiniti CSV schema)
# ---------------------------------------------------------------------------

@pytest.fixture
def raw_df_minimal() -> pd.DataFrame:
    """
    A small raw DataFrame with the same column names as the real CSV.
    All values are strings (as the loader returns them).
    prices.dateSeen contains both single and multi-timestamp examples.
    """
    return pd.DataFrame(
        {
            "id": ["P001", "P001", "P002", "P002", "P003"],
            "prices.amountMax": ["99.99", "89.99", "199.00", "189.00", "49.00"],
            "prices.amountMin": ["99.99", "89.99", "195.00", "185.00", ""],
            "prices.availability": [
                "Yes", "In Stock", "In Stock", "Out of Stock", "Yes"
            ],
            "prices.condition": ["New", "New", "New", "New", "New"],
            "prices.currency": ["USD", "USD", "USD", "USD", "USD"],
            "prices.dateSeen": [
                "2017-01-01T00:00:00Z,2017-01-15T00:00:00Z",  # multi
                "2017-02-01T00:00:00Z",                         # single
                "2017-01-10T00:00:00Z,2017-01-20T00:00:00Z,2017-02-10T00:00:00Z",
                "2017-03-01T00:00:00Z",
                "2017-01-05T00:00:00Z",
            ],
            "prices.isSale": ["TRUE", "FALSE", "FALSE", "TRUE", "FALSE"],
            "prices.merchant": [
                "Amazon.com", "Amazon.com", "BestBuy", "BestBuy", "Walmart"
            ],
            "prices.shipping": ["Free", "", "Free", "Free", ""],
            "prices.sourceURLs": [
                "http://amazon.com/p1", "", "http://bestbuy.com/p2", "", ""
            ],
            "asins": ["B001", "B001", "B002", "B002", "B003"],
            "brand": ["BrandA", "BrandA", "BrandB", "BrandB", "BrandC"],
            "categories": ["Electronics", "Electronics", "Cameras", "Cameras", "Audio"],
            "dateAdded": [
                "2016-12-01T00:00:00Z", "2016-12-01T00:00:00Z",
                "2016-11-01T00:00:00Z", "2016-11-01T00:00:00Z",
                "2016-10-01T00:00:00Z",
            ],
            "dateUpdated": [
                "2017-02-01T00:00:00Z", "2017-02-01T00:00:00Z",
                "2017-03-01T00:00:00Z", "2017-03-01T00:00:00Z",
                "2017-01-20T00:00:00Z",
            ],
            "ean": ["", "", "", "", ""],
            "imageURLs": ["", "", "", "", ""],
            "keys": ["", "", "", "", ""],
            "manufacturer": ["MfgA", "MfgA", "MfgB", "MfgB", "MfgC"],
            "manufacturerNumber": ["MN-001", "MN-001", "MN-002", "MN-002", "MN-003"],
            "name": [
                "Product Alpha", "Product Alpha",
                "Product Beta", "Product Beta",
                "Product Gamma",
            ],
            "primaryCategories": [
                "Electronics", "Electronics", "Cameras", "Cameras", "Audio"
            ],
            "sourceURLs": ["http://amazon.com", "", "http://bestbuy.com", "", ""],
            "upc": ["111", "111", "222", "222", "333"],
            "weight": ["1 lb", "1 lb", "2 lb", "2 lb", "0.5 lb"],
        }
    )


# ---------------------------------------------------------------------------
# Cleaned (preprocessed) DataFrame fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def cleaned_df() -> pd.DataFrame:
    """
    A small cleaned DataFrame with the output schema of preprocessing.preprocess().
    Six observations across three (product_id, merchant) pairs.
    Timestamps are strictly ascending within each pair.
    """
    utc = timezone.utc
    return pd.DataFrame(
        {
            "product_id": ["P001", "P001", "P001", "P002", "P002", "P002"],
            "product_name": ["Alpha", "Alpha", "Alpha", "Beta", "Beta", "Beta"],
            "brand": ["BrandA", "BrandA", "BrandA", "BrandB", "BrandB", "BrandB"],
            "manufacturer": ["MfgA"] * 3 + ["MfgB"] * 3,
            "manufacturer_number": ["MN1"] * 3 + ["MN2"] * 3,
            "category": ["Electronics"] * 6,
            "categories_raw": ["Electronics"] * 6,
            "asins": ["B001"] * 3 + ["B002"] * 3,
            "upc": ["111"] * 3 + ["222"] * 3,
            "ean": [""] * 6,
            "weight": ["1 lb"] * 6,
            "merchant": ["Amazon.com"] * 3 + ["BestBuy"] * 3,
            "currency": ["USD"] * 6,
            "price": [100.0, 90.0, 85.0, 200.0, 190.0, 180.0],
            "price_min": [100.0, 90.0, 85.0, 200.0, 190.0, 180.0],
            "price_max": [105.0, 95.0, 90.0, 210.0, 200.0, 190.0],
            "observed_at": pd.to_datetime(
                [
                    "2017-01-01", "2017-01-15", "2017-02-01",
                    "2017-01-10", "2017-01-20", "2017-02-10",
                ],
                utc=True,
            ),
            "is_sale": [False, False, True, False, True, False],
            "availability": ["Yes", "Yes", "Yes", "Yes", "Yes", "In Stock"],
            "condition": ["New"] * 6,
            "shipping": ["Free"] * 6,
            "offer": [""] * 6,
            "source_url": ["http://amazon.com"] * 3 + ["http://bestbuy.com"] * 3,
            "date_added": pd.to_datetime(["2016-12-01"] * 6, utc=True),
            "date_updated": pd.to_datetime(["2017-02-15"] * 6, utc=True),
        }
    )


# ---------------------------------------------------------------------------
# Simple time series (single PM pair, 10 observations)
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_series() -> pd.DataFrame:
    """
    Ten observations for (P001, Amazon.com) with a known price drop at index 6.
    """
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


# ---------------------------------------------------------------------------
# Minimal ChangeEvent fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_change_event():
    """A minimal ChangeEvent for testing event and query generation."""
    from src.events.event_generator import ChangeEvent

    return ChangeEvent(
        event_id="evt_test001",
        product_id="P001",
        product_name="Sony WH-1000XM4 Headphones",
        brand="Sony",
        manufacturer="Sony",
        manufacturer_number="WH1000XM4",
        category="Electronics",
        asins="B0863TXGM3",
        upc="027242920934",
        merchant="Amazon.com",
        observed_at="2017-03-15T06:00:00+00:00",
        previous_price=299.99,
        current_price=249.99,
        absolute_change=-50.00,
        percentage_change=-16.67,
        change_direction="decrease",
        cp_probability=0.72,
        map_run_length=3,
        log_price_diff=-0.182,
        is_sale=True,
        offer="http://amazon.com/deal",
        availability="Yes",
        condition="New",
        competitor_count=2,
        competitor_price_median=279.99,
        price_vs_comp_median=-30.00,
        competitors_changed_7d=1,
        competitor_direction_7d=-1,
        source_url="http://amazon.com/sony-wh1000xm4",
    )


@pytest.fixture
def sample_labelled_event(sample_change_event):
    """A LabelledEvent wrapping the sample ChangeEvent."""
    from src.weak_supervision.label_generator import LabelledEvent

    return LabelledEvent(
        event=sample_change_event,
        labels=["promotion_related", "competitive_related"],
        label_evidence={
            "promotion_related": ["is_sale=True at change point"],
            "competitive_related": ["1 competitor changed price in past 7 days"],
        },
    )
