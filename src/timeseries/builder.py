"""
src/timeseries/builder.py
=========================
Constructs chronological product-merchant price time series from the
cleaned DataFrame produced by preprocessing.py.

Design principles
-----------------
* The fundamental unit is (product_id, merchant).
* Observations are sorted strictly by observed_at (ascending).
* No date interpolation or gap-filling is performed — the dataset
  contains irregular timestamps and we must respect actual observation
  times.
* Lag/diff features (previous_price, absolute_change, etc.) are
  calculated within each group in chronological order so that at
  position i only observations 0..i are visible.  This mirrors the
  online-detection constraint.
* Groups with fewer than MIN_OBSERVATIONS observations are flagged but
  not silently discarded — the caller decides the threshold.

Output columns (per observation, sorted within group)
------------------------------------------------------
product_id
merchant
observed_at
price
price_min
price_max
is_sale
availability
condition
offer
product_name
brand
manufacturer
manufacturer_number
category
source_url

Derived per-observation columns
--------------------------------
previous_price          price at t-1 (NaN for first observation)
absolute_change         price - previous_price
percentage_change       (price - previous_price) / previous_price * 100
days_since_previous     calendar days between observed_at[i] and [i-1]
observation_index       0-based position within the PM group
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum number of observations for a PM pair to be included in the
# "usable for BOCPD" subset.  Lower counts are retained in the full
# series catalogue but flagged.
MIN_OBSERVATIONS_FOR_BOCPD: int = 5

# Columns carried through from the cleaned data into each time series
_SERIES_COLUMNS: list[str] = [
    "product_id",
    "merchant",
    "observed_at",
    "price",
    "price_min",
    "price_max",
    "is_sale",
    "availability",
    "condition",
    "offer",
    "product_name",
    "brand",
    "manufacturer",
    "manufacturer_number",
    "category",
    "source_url",
]

# Columns added by the builder
_DERIVED_COLUMNS: list[str] = [
    "previous_price",
    "absolute_change",
    "percentage_change",
    "days_since_previous",
    "observation_index",
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TimeSeriesCatalogue:
    """
    Container for all product-merchant time series.

    Attributes
    ----------
    series_df : pd.DataFrame
        Full flat DataFrame with all PM observations + derived columns.
    summary : pd.DataFrame
        One row per (product_id, merchant) pair with summary statistics.
    usable_pairs : pd.DataFrame
        Subset of summary where n_observations >= MIN_OBSERVATIONS_FOR_BOCPD.
    """
    series_df: pd.DataFrame
    summary: pd.DataFrame
    usable_pairs: pd.DataFrame


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _derive_per_group(group: pd.DataFrame) -> pd.DataFrame:
    """
    Add lag/diff columns to a single (product_id, merchant) group.

    The group must already be sorted ascending by observed_at.
    """
    g = group.copy()
    g = g.sort_values("observed_at").reset_index(drop=True)

    g["observation_index"] = range(len(g))
    g["previous_price"] = g["price"].shift(1)
    g["absolute_change"] = g["price"] - g["previous_price"]
    g["percentage_change"] = (
        g["absolute_change"] / g["previous_price"] * 100.0
    )

    # days_since_previous — works with tz-aware datetimes
    time_diff = g["observed_at"].diff()
    g["days_since_previous"] = time_diff.dt.total_seconds() / 86400.0

    return g


def _build_summary(series_df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-PM-pair summary statistics from the flat series DataFrame."""
    agg = (
        series_df.groupby(["product_id", "merchant"], sort=False)
        .agg(
            n_observations=("price", "count"),
            first_observed=("observed_at", "min"),
            last_observed=("observed_at", "max"),
            price_min=("price", "min"),
            price_max=("price", "max"),
            price_mean=("price", "mean"),
            price_std=("price", "std"),
            price_median=("price", "median"),
            n_sale_observations=("is_sale", "sum"),
            product_name=("product_name", "first"),
            brand=("brand", "first"),
            category=("category", "first"),
        )
        .reset_index()
    )

    # Span in days
    agg["span_days"] = (
        (agg["last_observed"] - agg["first_observed"]).dt.total_seconds() / 86400.0
    )

    # Usable flag
    agg["usable_for_bocpd"] = agg["n_observations"] >= MIN_OBSERVATIONS_FOR_BOCPD

    # Price range
    agg["price_range"] = agg["price_max"] - agg["price_min"]

    # Round floats for readability
    for col in ["price_mean", "price_std", "price_median", "price_range", "span_days"]:
        agg[col] = agg[col].round(4)

    return agg.sort_values("n_observations", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_time_series(
    cleaned_df: pd.DataFrame,
    min_observations: int = MIN_OBSERVATIONS_FOR_BOCPD,
) -> TimeSeriesCatalogue:
    """
    Build the full product-merchant time series catalogue.

    Parameters
    ----------
    cleaned_df:
        Cleaned DataFrame from preprocessing.load_cleaned() or
        preprocessing.preprocess()[0].
    min_observations:
        Threshold below which a PM pair is flagged as not usable for
        BOCPD.  Default is 5.

    Returns
    -------
    TimeSeriesCatalogue
        .series_df   — flat DataFrame, one row per observation.
        .summary     — one row per PM pair with statistics.
        .usable_pairs — summary rows with n_observations >= min_observations.
    """
    logger.info(
        "Building time series from %d cleaned observations", len(cleaned_df)
    )

    # Select and order columns; fill any absent ones with NA
    available = [c for c in _SERIES_COLUMNS if c in cleaned_df.columns]
    df = cleaned_df[available].copy()

    # Ensure observed_at is UTC datetime
    if not pd.api.types.is_datetime64_any_dtype(df["observed_at"]):
        df["observed_at"] = pd.to_datetime(df["observed_at"], errors="coerce", utc=True)

    # Drop rows where observed_at is still NaT after coercion
    before = len(df)
    df = df.dropna(subset=["observed_at"]).reset_index(drop=True)
    if len(df) < before:
        logger.warning(
            "Dropped %d rows with NaT observed_at during time-series build",
            before - len(df),
        )

    # Apply per-group derivation
    logger.info("Computing per-group lag features …")
    result_parts: list[pd.DataFrame] = []
    for (pid, merch), group in df.groupby(
        ["product_id", "merchant"], sort=False
    ):
        result_parts.append(_derive_per_group(group))

    if not result_parts:
        logger.warning("No product-merchant groups found — returning empty catalogue.")
        empty = pd.DataFrame(columns=_SERIES_COLUMNS + _DERIVED_COLUMNS)
        return TimeSeriesCatalogue(
            series_df=empty,
            summary=pd.DataFrame(),
            usable_pairs=pd.DataFrame(),
        )

    series_df = pd.concat(result_parts, ignore_index=True)
    series_df = series_df.sort_values(
        ["product_id", "merchant", "observed_at"]
    ).reset_index(drop=True)

    # Build summary
    summary = _build_summary(series_df)

    total_pairs = len(summary)
    usable = summary[summary["n_observations"] >= min_observations].copy()
    unusable = total_pairs - len(usable)

    logger.info(
        "Time series built: %d total PM pairs | %d usable (≥%d obs) | "
        "%d below threshold (retained in catalogue, excluded from BOCPD)",
        total_pairs,
        len(usable),
        min_observations,
        unusable,
    )
    if unusable > 0:
        logger.info(
            "LIMITATION: %d PM pairs have fewer than %d observations. "
            "These are insufficient for reliable BOCPD and are excluded "
            "from detection. No data fabrication is performed.",
            unusable,
            min_observations,
        )

    return TimeSeriesCatalogue(
        series_df=series_df,
        summary=summary,
        usable_pairs=usable.reset_index(drop=True),
    )


def get_series(
    catalogue: TimeSeriesCatalogue,
    product_id: str,
    merchant: str,
) -> pd.DataFrame:
    """
    Extract the time series for a single (product_id, merchant) pair.

    Returns an empty DataFrame if the pair is not found.
    """
    mask = (
        (catalogue.series_df["product_id"] == product_id) &
        (catalogue.series_df["merchant"] == merchant)
    )
    result = catalogue.series_df[mask].sort_values("observed_at").reset_index(drop=True)
    if result.empty:
        logger.warning("No series found for product_id=%s, merchant=%s", product_id, merchant)
    return result


def iter_usable_series(
    catalogue: TimeSeriesCatalogue,
) -> Iterator[tuple[str, str, pd.DataFrame]]:
    """
    Iterate over all usable (product_id, merchant) time series.

    Yields
    ------
    (product_id, merchant, series_df)
        Each series_df is sorted ascending by observed_at.
    """
    usable_keys = set(
        zip(
            catalogue.usable_pairs["product_id"],
            catalogue.usable_pairs["merchant"],
        )
    )
    for (pid, merch), group in catalogue.series_df.groupby(
        ["product_id", "merchant"], sort=False
    ):
        if (pid, merch) in usable_keys:
            yield pid, merch, group.sort_values("observed_at").reset_index(drop=True)


def save_series(catalogue: TimeSeriesCatalogue, output_dir: str | Path) -> None:
    """Save series_df and summary to the output directory."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    series_path = output_dir / "price_series.csv"
    summary_path = output_dir / "series_summary.csv"
    usable_path = output_dir / "usable_pairs.csv"

    catalogue.series_df.to_csv(series_path, index=False)
    catalogue.summary.to_csv(summary_path, index=False)
    catalogue.usable_pairs.to_csv(usable_path, index=False)

    logger.info("Series saved → %s", series_path)
    logger.info("Summary saved → %s", summary_path)
    logger.info("Usable pairs saved → %s", usable_path)


def load_series(output_dir: str | Path) -> TimeSeriesCatalogue:
    """Load a previously saved TimeSeriesCatalogue from the output directory."""
    output_dir = Path(output_dir)

    def _load(name: str) -> pd.DataFrame:
        p = output_dir / name
        df = pd.read_csv(p)
        for col in ["observed_at", "first_observed", "last_observed",
                    "date_added", "date_updated"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
        for col in ["price", "price_min", "price_max", "previous_price",
                    "absolute_change", "percentage_change",
                    "days_since_previous"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "is_sale" in df.columns:
            df["is_sale"] = df["is_sale"].astype(str).str.upper().isin(["TRUE", "1"])
        return df

    series_df = _load("price_series.csv")
    summary = _load("series_summary.csv")
    usable_pairs = _load("usable_pairs.csv")

    logger.info(
        "Series loaded from %s: %d observations, %d PM pairs",
        output_dir,
        len(series_df),
        len(summary),
    )
    return TimeSeriesCatalogue(
        series_df=series_df,
        summary=summary,
        usable_pairs=usable_pairs,
    )
