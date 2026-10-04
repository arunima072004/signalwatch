"""
src/data/preprocessing.py
==========================
Transforms the raw Datafiniti CSV into a clean, flat, analysis-ready
DataFrame where every row represents one (product, merchant, timestamp)
observation.

Pipeline steps — in order
--------------------------
1.  Rename columns to clean snake_case names.
2.  Explode prices.dateSeen — each comma-separated timestamp becomes its
    own row, duplicating all other column values for that raw row.
3.  Parse timestamps (prices.dateSeen → observed_at as tz-aware UTC).
4.  Parse price fields (amountMin, amountMax → float).
5.  Derive ``price`` as amountMin, falling back to amountMax when amountMin
    is missing.  Both original fields are preserved.
6.  Drop rows with unparseable / missing timestamps.
7.  Drop rows with non-positive or missing prices.
8.  Normalise currency — keep only rows where currency is 'USD' (or
    missing, which the dataset treats as USD).  Any non-USD rows are
    logged and dropped.
9.  Normalise isSale to bool.
10. Strip and normalise free-text fields (merchant, brand, name, …).
11. Drop exact duplicates on (product_id, merchant, observed_at, price).
12. Log every filtering decision with before/after counts.
13. Return the cleaned DataFrame and a filtering log.

Output column schema
--------------------
product_id          str     original 'id' field
product_name        str     product display name
brand               str
manufacturer        str
manufacturer_number str
category            str     primaryCategories (first value if multiple)
categories_raw      str     full categories string
asins               str
upc                 str
ean                 str
weight              str
merchant            str
currency            str
price               float   primary analysis price (amountMin preferred)
price_min           float   prices.amountMin
price_max           float   prices.amountMax
observed_at         datetime64[ns, UTC]
is_sale             bool
availability        str
condition           str
shipping            str
offer               str     prices.sourceURLs (used as offer proxy)
source_url          str     sourceURLs (product-level)
date_added          datetime64[ns, UTC]
date_updated        datetime64[ns, UTC]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Column rename map  raw_name → clean_name
# ---------------------------------------------------------------------------
_RENAME: dict[str, str] = {
    "id": "product_id",
    "prices.amountMax": "price_max",
    "prices.amountMin": "price_min",
    "prices.availability": "availability",
    "prices.condition": "condition",
    "prices.currency": "currency",
    "prices.dateSeen": "dates_seen_raw",
    "prices.isSale": "is_sale_raw",
    "prices.merchant": "merchant",
    "prices.shipping": "shipping",
    "prices.sourceURLs": "offer",
    "asins": "asins",
    "brand": "brand",
    "categories": "categories_raw",
    "dateAdded": "date_added_raw",
    "dateUpdated": "date_updated_raw",
    "ean": "ean",
    "imageURLs": "image_urls",
    "keys": "keys",
    "manufacturer": "manufacturer",
    "manufacturerNumber": "manufacturer_number",
    "name": "product_name",
    "primaryCategories": "category",
    "sourceURLs": "source_url",
    "upc": "upc",
    "weight": "weight",
}

# Columns to carry forward into the cleaned output
_OUTPUT_COLUMNS: list[str] = [
    "product_id",
    "product_name",
    "brand",
    "manufacturer",
    "manufacturer_number",
    "category",
    "categories_raw",
    "asins",
    "upc",
    "ean",
    "weight",
    "merchant",
    "currency",
    "price",
    "price_min",
    "price_max",
    "observed_at",
    "is_sale",
    "availability",
    "condition",
    "shipping",
    "offer",
    "source_url",
    "date_added",
    "date_updated",
]


# ---------------------------------------------------------------------------
# Filtering log
# ---------------------------------------------------------------------------
@dataclass
class FilteringLog:
    """Records every row-dropping decision with before/after counts."""
    steps: list[dict] = field(default_factory=list)

    def record(self, step: str, reason: str, before: int, after: int) -> None:
        dropped = before - after
        self.steps.append(
            {
                "step": step,
                "reason": reason,
                "rows_before": before,
                "rows_after": after,
                "rows_dropped": dropped,
                "pct_dropped": round(100.0 * dropped / max(before, 1), 2),
            }
        )
        logger.info(
            "[FILTER] %s — %s: %d → %d rows (−%d, %.1f%%)",
            step,
            reason,
            before,
            after,
            dropped,
            100.0 * dropped / max(before, 1),
        )

    def summary(self) -> str:
        lines = ["Filtering Log:", "-" * 60]
        for s in self.steps:
            lines.append(
                f"  [{s['step']}] {s['reason']}"
                f" | {s['rows_before']:,} → {s['rows_after']:,}"
                f" (−{s['rows_dropped']:,}, {s['pct_dropped']:.1f}%)"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------

def _rename_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename raw column names to clean snake_case equivalents."""
    present = {k: v for k, v in _RENAME.items() if k in df.columns}
    df = df.rename(columns=present)
    # Ensure all expected output columns exist (fill with NA if absent)
    for col in [
        "product_id", "product_name", "brand", "manufacturer",
        "manufacturer_number", "category", "categories_raw", "asins",
        "upc", "ean", "weight", "merchant", "currency", "dates_seen_raw",
        "is_sale_raw", "availability", "condition", "shipping", "offer",
        "source_url", "date_added_raw", "date_updated_raw", "price_min",
        "price_max", "image_urls", "keys",
    ]:
        if col not in df.columns:
            df[col] = pd.NA
    return df


def _explode_dates(df: pd.DataFrame, log: FilteringLog) -> pd.DataFrame:
    """
    Explode the comma-separated dates_seen_raw column so every row
    represents one (product, merchant, timestamp) observation.

    After explosion the 'observed_at_raw' column contains a single
    ISO-8601 timestamp string per row.
    """
    before = len(df)

    # Split the comma-separated string into a list, then explode
    df = df.copy()
    df["observed_at_raw"] = (
        df["dates_seen_raw"]
        .astype(str)
        .str.strip()
        .str.split(",")
    )
    df = df.explode("observed_at_raw")
    df["observed_at_raw"] = df["observed_at_raw"].astype(str).str.strip()

    # Drop rows where the timestamp string is empty after splitting
    before_empty = len(df)
    df = df[df["observed_at_raw"].ne("") & df["observed_at_raw"].ne("nan")]
    log.record(
        "explode_dates",
        "Remove empty timestamp strings after explosion",
        before_empty,
        len(df),
    )

    log.record("explode_dates", f"Raw rows {before} → exploded rows", before, len(df))
    df = df.drop(columns=["dates_seen_raw"], errors="ignore")
    df = df.reset_index(drop=True)
    return df


def _parse_timestamps(df: pd.DataFrame, log: FilteringLog) -> pd.DataFrame:
    """Parse observed_at_raw to tz-aware UTC datetime."""
    before = len(df)
    df["observed_at"] = pd.to_datetime(
        df["observed_at_raw"], errors="coerce", utc=True
    )
    df = df.drop(columns=["observed_at_raw"], errors="ignore")
    after = df["observed_at"].notna().sum()
    df = df[df["observed_at"].notna()].reset_index(drop=True)
    log.record(
        "parse_timestamps",
        "Drop rows where timestamp could not be parsed",
        before,
        len(df),
    )
    return df


def _parse_prices(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce price_min and price_max to float."""
    df["price_min"] = pd.to_numeric(df["price_min"], errors="coerce")
    df["price_max"] = pd.to_numeric(df["price_max"], errors="coerce")
    return df


def _derive_price(df: pd.DataFrame, log: FilteringLog) -> pd.DataFrame:
    """
    Derive a single ``price`` column.

    Logic:
      price = price_min   if price_min is valid and positive
      price = price_max   if price_min is missing/invalid but price_max is valid
      price = NaN         otherwise → row will be dropped

    Rationale: price_min represents the lowest observed listed price for that
    product/merchant row, which is the most representative single price to
    track.  price_max is used as a fallback only.
    """
    df["price"] = df["price_min"].where(
        df["price_min"].notna() & (df["price_min"] > 0),
        other=df["price_max"],
    )
    before = len(df)
    df = df[df["price"].notna() & (df["price"] > 0)].reset_index(drop=True)
    log.record(
        "derive_price",
        "Drop rows with non-positive or missing price",
        before,
        len(df),
    )
    return df


def _normalise_currency(df: pd.DataFrame, log: FilteringLog) -> pd.DataFrame:
    """
    Retain only rows with currency == 'USD' (or blank, treated as USD).

    This dataset is overwhelmingly USD.  Mixing currencies without
    conversion would corrupt price-change calculations.
    """
    before = len(df)
    currency_clean = (
        df["currency"].astype(str).str.strip().str.upper().replace("NAN", "")
    )
    mask = currency_clean.isin(["USD", ""])
    non_usd = (~mask).sum()
    if non_usd > 0:
        non_usd_vals = (
            df.loc[~mask, "currency"]
            .value_counts()
            .head(10)
            .to_dict()
        )
        logger.warning(
            "Dropping %d rows with non-USD currencies: %s", non_usd, non_usd_vals
        )
    df = df[mask].copy()
    df["currency"] = "USD"
    log.record(
        "normalise_currency",
        "Keep only USD (or blank) currency rows",
        before,
        len(df),
    )
    return df


def _normalise_is_sale(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert is_sale_raw (string 'TRUE'/'FALSE'/'nan'/…) to bool.

    Missing/unknown values default to False.
    """
    raw = df["is_sale_raw"].astype(str).str.strip().str.upper()
    df["is_sale"] = raw.isin(["TRUE", "1", "YES"])
    df = df.drop(columns=["is_sale_raw"], errors="ignore")
    return df


def _normalise_text_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Strip whitespace from free-text categorical columns."""
    text_cols = [
        "product_id", "product_name", "brand", "manufacturer",
        "manufacturer_number", "category", "merchant", "availability",
        "condition", "shipping",
    ]
    for col in text_cols:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.strip()
                .replace({"nan": "", "None": "", "NaN": ""})
            )
    return df


def _parse_metadata_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Parse date_added_raw and date_updated_raw to UTC datetime."""
    for raw_col, clean_col in [
        ("date_added_raw", "date_added"),
        ("date_updated_raw", "date_updated"),
    ]:
        if raw_col in df.columns:
            df[clean_col] = pd.to_datetime(df[raw_col], errors="coerce", utc=True)
            df = df.drop(columns=[raw_col], errors="ignore")
        else:
            df[clean_col] = pd.NaT
    return df


def _drop_same_timestamp_dupes(df: pd.DataFrame, log: FilteringLog) -> pd.DataFrame:
    """
    When the same (product_id, merchant) has multiple observations at the
    EXACT same timestamp with different prices, keep the most common price.
    This handles a known Datafiniti data quality issue where the $2 /
    erroneous placeholder price appears alongside the true price at the
    same timestamp.  Keeping the MAX price (most common in correct data)
    is a conservative, documented choice.
    """
    before = len(df)
    # Sort by price descending so keep='first' retains the highest price
    df = df.sort_values(
        ["product_id", "merchant", "observed_at", "price"],
        ascending=[True, True, True, False],
    )
    df = df.drop_duplicates(
        subset=["product_id", "merchant", "observed_at"],
        keep="first",
    ).reset_index(drop=True)
    log.record(
        "drop_same_timestamp_dupes",
        "Keep max price when same (product_id, merchant, observed_at) has "
        "multiple prices (data quality issue — placeholder $2 prices removed)",
        before,
        len(df),
    )
    return df


def _drop_price_outliers(df: pd.DataFrame, log: FilteringLog,
                          max_ratio: float = 100.0) -> pd.DataFrame:
    """
    Within each (product_id, merchant) group, drop observations where the
    price is more than max_ratio times smaller than the median price for
    that group.  This removes placeholder/erroneous prices like $2 for a
    $3000 product (ratio 1500x) while preserving legitimate sale prices.

    A ratio of 100 means: drop if price < median_price / 100.
    This is deliberately conservative — a 99% discount would survive.
    """
    before = len(df)
    keep_indices = []
    for (pid, merch), group in df.groupby(["product_id", "merchant"], sort=False):
        median_price = group["price"].median()
        threshold = median_price / max_ratio
        keep = group.index[group["price"] >= threshold].tolist()
        keep_indices.extend(keep)
    df = df.loc[sorted(keep_indices)].reset_index(drop=True)
    log.record(
        "drop_price_outliers",
        "Drop prices < median/100 within each PM group (removes placeholder prices)",
        before,
        len(df),
    )
    return df



    """
    Drop exact duplicates on (product_id, merchant, observed_at, price).

    These arise when the same product row has the same timestamp listed
    multiple times in prices.dateSeen (occasionally the Datafiniti export
    duplicates timestamps).
    """
    before = len(df)
    df = df.drop_duplicates(
        subset=["product_id", "merchant", "observed_at", "price"],
        keep="first",
    ).reset_index(drop=True)
    log.record(
        "drop_exact_duplicates",
        "Remove duplicate (product_id, merchant, observed_at, price) rows",
        before,
        len(df),
    )
    return df


def _drop_exact_duplicates(df: pd.DataFrame, log: FilteringLog) -> pd.DataFrame:
    """
    Drop exact duplicates on (product_id, merchant, observed_at, price).

    These arise when the same product row has the same timestamp listed
    multiple times in prices.dateSeen (occasionally the Datafiniti export
    duplicates timestamps).
    """
    before = len(df)
    df = df.drop_duplicates(
        subset=["product_id", "merchant", "observed_at", "price"],
        keep="first",
    ).reset_index(drop=True)
    log.record(
        "drop_exact_duplicates",
        "Remove duplicate (product_id, merchant, observed_at, price) rows",
        before,
        len(df),
    )
    return df


def _drop_invalid_ids(df: pd.DataFrame, log: FilteringLog) -> pd.DataFrame:
    """Drop rows where product_id or merchant is empty."""
    before = len(df)
    df = df[
        df["product_id"].str.strip().ne("") &
        df["merchant"].str.strip().ne("")
    ].reset_index(drop=True)
    log.record(
        "drop_invalid_ids",
        "Remove rows with empty product_id or merchant",
        before,
        len(df),
    )
    return df


def _select_output_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only the declared output columns, in order."""
    present = [c for c in _OUTPUT_COLUMNS if c in df.columns]
    missing = [c for c in _OUTPUT_COLUMNS if c not in df.columns]
    if missing:
        logger.debug("Output columns not found in data (will be NaN): %s", missing)
        for c in missing:
            df[c] = pd.NA
    return df[_OUTPUT_COLUMNS].copy()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def preprocess(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, FilteringLog]:
    """
    Run the full preprocessing pipeline on the raw DataFrame.

    Parameters
    ----------
    df:
        Raw DataFrame as returned by ``loader.load_raw()``.

    Returns
    -------
    cleaned : pd.DataFrame
        Flat, analysis-ready DataFrame.  One row = one
        (product, merchant, timestamp) observation.
    log : FilteringLog
        Every filtering decision with before/after row counts.
    """
    log = FilteringLog()
    initial_rows = len(df)
    logger.info("Preprocessing started — %d raw rows", initial_rows)

    df = _rename_columns(df)
    df = _explode_dates(df, log)
    df = _parse_timestamps(df, log)
    df = _parse_prices(df)
    df = _derive_price(df, log)
    df = _normalise_currency(df, log)
    df = _normalise_is_sale(df)
    df = _normalise_text_fields(df)
    df = _parse_metadata_dates(df)
    df = _drop_invalid_ids(df, log)
    df = _drop_same_timestamp_dupes(df, log)
    df = _drop_price_outliers(df, log)
    df = _drop_exact_duplicates(df, log)
    df = _select_output_columns(df)

    logger.info(
        "Preprocessing complete — %d rows retained from %d raw rows (%.1f%%)",
        len(df),
        initial_rows,
        100.0 * len(df) / max(initial_rows, 1),
    )
    return df, log


def save_cleaned(
    df: pd.DataFrame,
    output_path: str | Path,
) -> None:
    """Save the cleaned DataFrame to CSV."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    logger.info("Cleaned data saved to: %s (%d rows)", output_path, len(df))


def load_cleaned(input_path: str | Path) -> pd.DataFrame:
    """
    Load the cleaned CSV back into a DataFrame with correct dtypes.

    This is used by downstream modules so they don't repeat
    the preprocessing step.
    """
    input_path = Path(input_path)
    df = pd.read_csv(
        input_path,
        dtype={
            "product_id": str,
            "product_name": str,
            "brand": str,
            "manufacturer": str,
            "manufacturer_number": str,
            "category": str,
            "categories_raw": str,
            "asins": str,
            "upc": str,
            "ean": str,
            "weight": str,
            "merchant": str,
            "currency": str,
            "availability": str,
            "condition": str,
            "shipping": str,
            "offer": str,
            "source_url": str,
        },
    )
    # Re-parse datetimes
    for col in ["observed_at", "date_added", "date_updated"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
    # Re-parse numerics
    for col in ["price", "price_min", "price_max"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # Re-parse bool
    if "is_sale" in df.columns:
        df["is_sale"] = df["is_sale"].astype(str).str.upper().isin(["TRUE", "1"])
    logger.info("Cleaned data loaded from: %s (%d rows)", input_path, len(df))
    return df
