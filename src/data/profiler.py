"""
src/data/profiler.py
====================
Dataset profiling — produces a structured summary of the raw DataFrame and
prints/saves a human-readable report.  No data is modified here.

Profiling covers
----------------
* Shape (rows, columns)
* Column names and inferred dtypes
* Missing-value counts per column
* Duplicate row count
* prices.dateSeen explosion statistics
  - rows with a single timestamp vs. multiple timestamps
  - total observations after explosion
  - product-merchant pair statistics
* Unique counts: products, merchants, brands, categories, currencies
* Price field statistics (amountMin, amountMax as numerics)
* Date range
* isSale distribution
* Top-10 most-observed product-merchant pairs
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_numeric(series: pd.Series) -> pd.Series:
    """Coerce a string Series to float, coercing errors to NaN."""
    return pd.to_numeric(series, errors="coerce")


def _explode_dates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return a DataFrame where each row is one (id, merchant, timestamp).
    Used purely for profiling statistics — does not mutate the input.
    """
    rows: list[dict[str, str]] = []
    for _, row in df.iterrows():
        pid = str(row.get("id", "")).strip()
        merchant = str(row.get("prices.merchant", "")).strip()
        dates_raw = str(row.get("prices.dateSeen", "")).strip()
        for d in dates_raw.split(","):
            d = d.strip()
            if d:
                rows.append({"product_id": pid, "merchant": merchant, "timestamp": d})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def profile(df: pd.DataFrame) -> dict[str, Any]:
    """
    Compute a comprehensive profile of the raw DataFrame.

    Parameters
    ----------
    df:
        Raw DataFrame as returned by ``loader.load_raw()``.

    Returns
    -------
    dict
        Nested dictionary with all profiling statistics.
    """
    report: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # 1. Shape
    # ------------------------------------------------------------------
    report["shape"] = {"rows": int(len(df)), "columns": int(len(df.columns))}

    # ------------------------------------------------------------------
    # 2. Column names
    # ------------------------------------------------------------------
    report["columns"] = list(df.columns)

    # ------------------------------------------------------------------
    # 3. Missing values per column
    # ------------------------------------------------------------------
    missing: dict[str, Any] = {}
    for col in df.columns:
        n_null = int(df[col].isna().sum())
        n_empty = int((df[col].astype(str).str.strip() == "").sum())
        missing[col] = {
            "null_count": n_null,
            "empty_string_count": n_empty,
            "total_missing": n_null + n_empty,
            "pct_missing": round(100.0 * (n_null + n_empty) / max(len(df), 1), 2),
        }
    report["missing_values"] = missing

    # ------------------------------------------------------------------
    # 4. Duplicate rows
    # ------------------------------------------------------------------
    n_dup = int(df.duplicated().sum())
    report["duplicate_rows"] = {
        "count": n_dup,
        "pct": round(100.0 * n_dup / max(len(df), 1), 2),
    }

    # ------------------------------------------------------------------
    # 5. Unique counts
    # ------------------------------------------------------------------
    def _nunique(col: str) -> int:
        if col not in df.columns:
            return 0
        return int(df[col].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique())

    report["unique_counts"] = {
        "products (id)": _nunique("id"),
        "merchants (prices.merchant)": _nunique("prices.merchant"),
        "brands": _nunique("brand"),
        "primary_categories": _nunique("primaryCategories"),
        "currencies": _nunique("prices.currency"),
        "conditions": _nunique("prices.condition"),
    }

    # ------------------------------------------------------------------
    # 6. Price statistics
    # ------------------------------------------------------------------
    price_min = _safe_numeric(df.get("prices.amountMin", pd.Series(dtype=float)))
    price_max = _safe_numeric(df.get("prices.amountMax", pd.Series(dtype=float)))
    report["price_statistics"] = {
        "amountMin": {
            "valid_count": int(price_min.notna().sum()),
            "null_count": int(price_min.isna().sum()),
            "min": float(price_min.min()) if price_min.notna().any() else None,
            "max": float(price_min.max()) if price_min.notna().any() else None,
            "mean": round(float(price_min.mean()), 4) if price_min.notna().any() else None,
            "median": float(price_min.median()) if price_min.notna().any() else None,
            "std": round(float(price_min.std()), 4) if price_min.notna().any() else None,
        },
        "amountMax": {
            "valid_count": int(price_max.notna().sum()),
            "null_count": int(price_max.isna().sum()),
            "min": float(price_max.min()) if price_max.notna().any() else None,
            "max": float(price_max.max()) if price_max.notna().any() else None,
            "mean": round(float(price_max.mean()), 4) if price_max.notna().any() else None,
            "median": float(price_max.median()) if price_max.notna().any() else None,
            "std": round(float(price_max.std()), 4) if price_max.notna().any() else None,
        },
    }

    # ------------------------------------------------------------------
    # 7. isSale distribution
    # ------------------------------------------------------------------
    if "prices.isSale" in df.columns:
        sale_counts = (
            df["prices.isSale"]
            .astype(str)
            .str.strip()
            .str.upper()
            .value_counts()
            .to_dict()
        )
    else:
        sale_counts = {}
    report["is_sale_distribution"] = sale_counts

    # ------------------------------------------------------------------
    # 8. Availability distribution
    # ------------------------------------------------------------------
    if "prices.availability" in df.columns:
        avail_counts = (
            df["prices.availability"]
            .astype(str)
            .str.strip()
            .value_counts()
            .head(15)
            .to_dict()
        )
    else:
        avail_counts = {}
    report["availability_distribution"] = avail_counts

    # ------------------------------------------------------------------
    # 9. Date fields
    # ------------------------------------------------------------------
    for col in ["dateAdded", "dateUpdated"]:
        if col in df.columns:
            parsed = pd.to_datetime(df[col], errors="coerce", utc=True)
            report[f"{col}_range"] = {
                "min": str(parsed.min()) if parsed.notna().any() else None,
                "max": str(parsed.max()) if parsed.notna().any() else None,
                "null_count": int(parsed.isna().sum()),
            }

    # ------------------------------------------------------------------
    # 10. prices.dateSeen explosion statistics
    # ------------------------------------------------------------------
    dates_col = df.get("prices.dateSeen", pd.Series(dtype=str)).astype(str)
    multi_date_rows = int((dates_col.str.contains(",", na=False)).sum())
    single_date_rows = int((~dates_col.str.contains(",", na=False) & dates_col.str.strip().ne("")).sum())

    # Explode to individual observations
    exploded = _explode_dates(df)
    total_observations = len(exploded)

    # Parse timestamps for range
    parsed_ts = pd.to_datetime(exploded["timestamp"], errors="coerce", utc=True)
    ts_range = {
        "min": str(parsed_ts.min()) if parsed_ts.notna().any() else None,
        "max": str(parsed_ts.max()) if parsed_ts.notna().any() else None,
        "null_after_parse": int(parsed_ts.isna().sum()),
    }

    # Product-merchant pair statistics
    pm_counts = (
        exploded.groupby(["product_id", "merchant"])
        .size()
        .reset_index(name="n_observations")
    )
    pm_stats = {
        "total_pairs": int(len(pm_counts)),
        "pairs_ge_2": int((pm_counts["n_observations"] >= 2).sum()),
        "pairs_ge_3": int((pm_counts["n_observations"] >= 3).sum()),
        "pairs_ge_5": int((pm_counts["n_observations"] >= 5).sum()),
        "pairs_ge_10": int((pm_counts["n_observations"] >= 10).sum()),
        "pairs_ge_20": int((pm_counts["n_observations"] >= 20).sum()),
        "max_observations_per_pair": int(pm_counts["n_observations"].max()),
        "median_observations_per_pair": float(pm_counts["n_observations"].median()),
        "mean_observations_per_pair": round(float(pm_counts["n_observations"].mean()), 2),
    }

    # Top-10 richest pairs
    top10 = pm_counts.nlargest(10, "n_observations")[
        ["product_id", "merchant", "n_observations"]
    ].to_dict(orient="records")

    report["date_seen_statistics"] = {
        "rows_with_multiple_timestamps": multi_date_rows,
        "rows_with_single_timestamp": single_date_rows,
        "total_observations_after_explosion": total_observations,
        "timestamp_range": ts_range,
        "product_merchant_pair_statistics": pm_stats,
        "top_10_richest_pairs": top10,
    }

    # ------------------------------------------------------------------
    # 11. Currency distribution
    # ------------------------------------------------------------------
    if "prices.currency" in df.columns:
        curr_counts = (
            df["prices.currency"]
            .astype(str)
            .str.strip()
            .value_counts()
            .to_dict()
        )
    else:
        curr_counts = {}
    report["currency_distribution"] = curr_counts

    # ------------------------------------------------------------------
    # 12. Sample product names
    # ------------------------------------------------------------------
    if "name" in df.columns:
        sample_names = (
            df["name"]
            .dropna()
            .astype(str)
            .str.strip()
            .replace("", pd.NA)
            .dropna()
            .unique()[:10]
            .tolist()
        )
    else:
        sample_names = []
    report["sample_product_names"] = sample_names

    return report


def print_report(report: dict[str, Any]) -> None:
    """Pretty-print the profiling report to stdout."""
    sep = "=" * 70

    print(f"\n{sep}")
    print("  SIGNALWATCH — DATASET PROFILING REPORT")
    print(sep)

    s = report.get("shape", {})
    print(f"\nShape: {s.get('rows', '?'):,} rows × {s.get('columns', '?')} columns")

    print("\nColumns:")
    for c in report.get("columns", []):
        mv = report.get("missing_values", {}).get(c, {})
        print(
            f"  {c:<35s}  missing={mv.get('total_missing', '?'):>6,}  "
            f"({mv.get('pct_missing', '?'):>5.1f}%)"
        )

    dup = report.get("duplicate_rows", {})
    print(f"\nDuplicate rows: {dup.get('count', '?'):,} ({dup.get('pct', '?'):.2f}%)")

    print("\nUnique counts:")
    for k, v in report.get("unique_counts", {}).items():
        print(f"  {k:<45s}  {v:>6,}")

    print("\nPrice statistics:")
    for field, stats in report.get("price_statistics", {}).items():
        print(
            f"  {field}: valid={stats.get('valid_count'):,}  "
            f"min={stats.get('min')}  max={stats.get('max')}  "
            f"mean={stats.get('mean')}  std={stats.get('std')}"
        )

    print("\nisSale distribution:")
    for k, v in report.get("is_sale_distribution", {}).items():
        print(f"  {k}: {v:,}")

    print("\nAvailability distribution (top 15):")
    for k, v in report.get("availability_distribution", {}).items():
        print(f"  {k!r:40s}: {v:,}")

    ds = report.get("date_seen_statistics", {})
    print(f"\nprices.dateSeen — explosion statistics:")
    print(f"  Rows with multiple timestamps : {ds.get('rows_with_multiple_timestamps', '?'):,}")
    print(f"  Rows with single timestamp    : {ds.get('rows_with_single_timestamp', '?'):,}")
    print(f"  Total observations (exploded) : {ds.get('total_observations_after_explosion', '?'):,}")
    tr = ds.get("timestamp_range", {})
    print(f"  Timestamp range               : {tr.get('min')} to {tr.get('max')}")

    pm = ds.get("product_merchant_pair_statistics", {})
    print(f"\nProduct-Merchant pair statistics:")
    print(f"  Total pairs     : {pm.get('total_pairs', '?'):,}")
    print(f"  Pairs with >=2  obs: {pm.get('pairs_ge_2', '?'):,}")
    print(f"  Pairs with >=3  obs: {pm.get('pairs_ge_3', '?'):,}")
    print(f"  Pairs with >=5  obs: {pm.get('pairs_ge_5', '?'):,}")
    print(f"  Pairs with >=10 obs: {pm.get('pairs_ge_10', '?'):,}")
    print(f"  Pairs with >=20 obs: {pm.get('pairs_ge_20', '?'):,}")
    print(f"  Max obs per pair  : {pm.get('max_observations_per_pair', '?'):,}")
    print(f"  Median obs/pair   : {pm.get('median_observations_per_pair', '?')}")
    print(f"  Mean obs/pair     : {pm.get('mean_observations_per_pair', '?')}")

    print(f"\nTop-10 richest product-merchant pairs:")
    for row in ds.get("top_10_richest_pairs", []):
        print(
            f"  id={row['product_id'][:16]:<16s}  "
            f"merchant={str(row['merchant'])[:30]:<30s}  "
            f"n={row['n_observations']:>4}"
        )

    print("\nCurrency distribution:")
    for k, v in report.get("currency_distribution", {}).items():
        print(f"  {k}: {v:,}")

    print(f"\n{sep}\n")


def save_report(report: dict[str, Any], output_path: str | Path) -> None:
    """Serialise the report dict to a JSON file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    logger.info("Profiling report saved to: %s", output_path)
