"""
src/features/competitive_features.py
======================================
Computes competitor-relative price features for each (product_id, merchant,
observed_at) observation.

Temporal leakage prevention
----------------------------
This is an OFFLINE HISTORICAL REPLAY of an online algorithm.  When computing
the competitive context for observation (product_id=P, merchant=M, t=T), we
must only use competitor observations with timestamp STRICTLY LESS THAN T
from the same dataset.

Implementation approach: for each observation at time T for merchant M,
the competitor snapshot is built from the MOST RECENT observation for every
OTHER merchant carrying the same product_id, where that observation's
timestamp < T.

This is the correct causal definition:
  "What did we know about competitor prices just before we saw M's price at T?"

If no competitor observations exist before T for a given product, all
competitive features for that row are NaN.  No values are fabricated.

Feature catalogue
-----------------
  competitor_count        number of other merchants with known price at T
  competitor_price_min    min price across competitors (at their latest t < T)
  competitor_price_max    max price across competitors
  competitor_price_mean   mean price across competitors
  competitor_price_median median price across competitors
  price_vs_comp_median    price[M,T] - competitor_price_median
  price_vs_comp_mean      price[M,T] - competitor_price_mean
  price_vs_comp_min       price[M,T] - competitor_price_min
  relative_price_position price[M,T] / competitor_price_median  (ratio)
  is_cheapest             bool: price[M,T] <= competitor_price_min
  is_most_expensive       bool: price[M,T] >= competitor_price_max
  competitors_changed_7d  number of competitors that changed price in ±7d
                          window around T (uses only past observations up to T)
  competitor_direction_7d net direction of competitor price changes in past 7d:
                          +1 = majority increased, -1 = majority decreased, 0 = mixed

Performance note
----------------
A naïve nested-loop implementation would be O(N²) over all observations.
We use a merge + filter approach: for each product, we precompute a lookup
table of (merchant, timestamp → latest price before T) keyed by product_id,
then join efficiently using pandas groupby + shift logic.

For large datasets the per-product approach keeps memory bounded.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _latest_prices_before_t(
    product_df: pd.DataFrame,
    t: pd.Timestamp,
    focal_merchant: str,
) -> pd.DataFrame:
    """
    For a single product, return the most recent price for every OTHER
    merchant strictly before timestamp t.

    Parameters
    ----------
    product_df:
        All observations for one product_id, sorted by observed_at ascending.
    t:
        The focal timestamp.
    focal_merchant:
        The merchant whose observation we are augmenting (excluded).

    Returns
    -------
    pd.DataFrame with columns [merchant, price] — one row per competitor.
    """
    # Exclude the focal merchant and future observations
    comp = product_df[
        (product_df["merchant"] != focal_merchant) &
        (product_df["observed_at"] < t)
    ]
    if comp.empty:
        return pd.DataFrame(columns=["merchant", "price"])

    # Take the most recent price per competitor
    latest = (
        comp.sort_values("observed_at")
        .groupby("merchant", sort=False)
        .last()
        .reset_index()[["merchant", "price"]]
    )
    return latest


def _compute_competitor_features_for_product(
    product_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compute all competitive features for every observation of a single
    product across all its merchants.

    The product_df must be sorted by observed_at ascending.
    """
    rows: list[dict] = []

    for idx, row in product_df.iterrows():
        t = row["observed_at"]
        focal_merchant = row["merchant"]
        focal_price = row["price"]

        comp_prices = _latest_prices_before_t(product_df, t, focal_merchant)

        if comp_prices.empty:
            rows.append(
                {
                    "_idx": idx,
                    "competitor_count": 0,
                    "competitor_price_min": np.nan,
                    "competitor_price_max": np.nan,
                    "competitor_price_mean": np.nan,
                    "competitor_price_median": np.nan,
                    "price_vs_comp_median": np.nan,
                    "price_vs_comp_mean": np.nan,
                    "price_vs_comp_min": np.nan,
                    "relative_price_position": np.nan,
                    "is_cheapest": np.nan,
                    "is_most_expensive": np.nan,
                    "competitors_changed_7d": 0,
                    "competitor_direction_7d": 0,
                }
            )
            continue

        prices = comp_prices["price"].dropna()
        comp_min = float(prices.min())
        comp_max = float(prices.max())
        comp_mean = float(prices.mean())
        comp_median = float(prices.median())

        # Competitors that changed price in the past 7 days
        cutoff_7d = t - pd.Timedelta(days=7)
        comp_7d = product_df[
            (product_df["merchant"] != focal_merchant) &
            (product_df["observed_at"] >= cutoff_7d) &
            (product_df["observed_at"] < t) &
            (product_df["absolute_change"].notna()) &
            (product_df["absolute_change"] != 0)
        ]
        changed_merchants = comp_7d["merchant"].nunique()

        # Net direction of competitor changes in past 7 days
        if not comp_7d.empty:
            pos = (comp_7d["absolute_change"] > 0).sum()
            neg = (comp_7d["absolute_change"] < 0).sum()
            if pos > neg:
                direction = 1
            elif neg > pos:
                direction = -1
            else:
                direction = 0
        else:
            direction = 0

        rows.append(
            {
                "_idx": idx,
                "competitor_count": len(prices),
                "competitor_price_min": comp_min,
                "competitor_price_max": comp_max,
                "competitor_price_mean": round(comp_mean, 4),
                "competitor_price_median": comp_median,
                "price_vs_comp_median": round(focal_price - comp_median, 4),
                "price_vs_comp_mean": round(focal_price - comp_mean, 4),
                "price_vs_comp_min": round(focal_price - comp_min, 4),
                "relative_price_position": round(
                    focal_price / comp_median if comp_median != 0 else np.nan, 4
                ),
                "is_cheapest": bool(focal_price <= comp_min),
                "is_most_expensive": bool(focal_price >= comp_max),
                "competitors_changed_7d": int(changed_merchants),
                "competitor_direction_7d": int(direction),
            }
        )

    feat_df = pd.DataFrame(rows).set_index("_idx")
    return feat_df


def compute_competitive_features(
    series_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compute competitor-relative features for every observation in the flat
    series DataFrame, respecting temporal ordering to prevent data leakage.

    Parameters
    ----------
    series_df:
        Full flat series DataFrame from TimeSeriesCatalogue.series_df or
        the price-features augmented version.  Must contain:
        product_id, merchant, observed_at, price, absolute_change.

    Returns
    -------
    pd.DataFrame
        Input DataFrame with competitive feature columns appended.
        Sorted by (product_id, merchant, observed_at).
    """
    logger.info(
        "Computing competitive features for %d observations …", len(series_df)
    )

    # Ensure datetime type
    df = series_df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df["observed_at"]):
        df["observed_at"] = pd.to_datetime(df["observed_at"], errors="coerce", utc=True)

    all_feature_parts: list[pd.DataFrame] = []

    product_ids = df["product_id"].unique()
    n_products = len(product_ids)

    for i, pid in enumerate(product_ids):
        if (i + 1) % 100 == 0 or (i + 1) == n_products:
            logger.info(
                "  Competitive features: product %d/%d", i + 1, n_products
            )

        product_df = df[df["product_id"] == pid].sort_values("observed_at").copy()
        n_merchants = product_df["merchant"].nunique()

        if n_merchants < 2:
            # No competitors — all competitive features are NaN / 0
            feat_df = pd.DataFrame(
                index=product_df.index,
                data={
                    "competitor_count": 0,
                    "competitor_price_min": np.nan,
                    "competitor_price_max": np.nan,
                    "competitor_price_mean": np.nan,
                    "competitor_price_median": np.nan,
                    "price_vs_comp_median": np.nan,
                    "price_vs_comp_mean": np.nan,
                    "price_vs_comp_min": np.nan,
                    "relative_price_position": np.nan,
                    "is_cheapest": np.nan,
                    "is_most_expensive": np.nan,
                    "competitors_changed_7d": 0,
                    "competitor_direction_7d": 0,
                },
            )
        else:
            feat_df = _compute_competitor_features_for_product(product_df)

        all_feature_parts.append(feat_df)

    # Concatenate all feature frames and join back to the original df
    all_features = pd.concat(all_feature_parts)
    result = df.join(all_features, how="left")
    result = result.sort_values(
        ["product_id", "merchant", "observed_at"]
    ).reset_index(drop=True)

    logger.info(
        "Competitive features computed: %d rows, %d columns",
        len(result),
        len(result.columns),
    )
    return result


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def save_competitive_features(df: pd.DataFrame, output_path: str | Path) -> None:
    """Save the competitive features DataFrame to CSV."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    logger.info(
        "Competitive features saved to: %s (%d rows)", output_path, len(df)
    )


def load_competitive_features(input_path: str | Path) -> pd.DataFrame:
    """Load competitive features CSV with correct dtypes."""
    df = pd.read_csv(input_path)
    for col in ["observed_at", "date_added", "date_updated"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
    bool_cols = ["is_cheapest", "is_most_expensive", "is_sale"]
    for col in bool_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.upper().isin(["TRUE", "1"])
    non_numeric = {
        "product_id", "merchant", "product_name", "brand", "category",
        "availability", "condition", "offer", "source_url", "manufacturer",
        "manufacturer_number", "categories_raw", "asins", "upc", "ean",
        "weight", "currency", "shipping", "observed_at", "date_added",
        "date_updated", "is_sale", "is_cheapest", "is_most_expensive",
    }
    for col in df.columns:
        if col not in non_numeric:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    logger.info(
        "Competitive features loaded from: %s (%d rows)", input_path, len(df)
    )
    return df
