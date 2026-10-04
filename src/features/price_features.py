"""
src/features/price_features.py
================================
Computes per-observation price features for every product-merchant time
series.  All features are computed strictly in causal order: at observation
index i only observations 0..i are visible.  This mirrors the constraints
of online change-point detection.

Feature catalogue
-----------------
Directly from the time series:
  price                   raw price
  price_min               raw prices.amountMin
  price_max               raw prices.amountMax
  previous_price          price at t-1
  absolute_change         price[i] - price[i-1]
  percentage_change       absolute_change / previous_price * 100
  days_since_previous     calendar days between obs[i] and obs[i-1]

Log-price features:
  log_price               log(price)  — natural log
  log_price_diff          log_price[i] - log_price[i-1]  (log-return)

Rationale for log_price_diff as BOCPD input
--------------------------------------------
  Raw prices span several orders of magnitude across products (e.g. a
  $5 cable vs a $2000 laptop).  Log-price differences (log-returns) are:
  * approximately scale-invariant across price levels,
  * symmetric around zero for equal up/down percentage moves,
  * closer to Gaussian than raw price differences on real-world retail
    data (log-normal price assumption is standard in finance and retail
    economics).
  BOCPD with a Gaussian observation model is therefore more appropriate
  on log_price_diff than on raw absolute or percentage changes.
  We compute both and let the caller/BOCPD config choose.

Rolling statistics (computed on log_price, window sizes are configurable):
  rolling_mean_N          rolling mean of log_price over last N obs
  rolling_std_N           rolling std  of log_price over last N obs
  rolling_median_N        rolling median of log_price over last N obs
  rolling_mean_price_N    rolling mean of raw price (for interpretation)

Price volatility:
  rolling_volatility_N    rolling std of log_price_diff over last N obs

Sale / offer flags (passed through from builder):
  is_sale
  availability
  condition
  offer

Default window sizes: [3, 5, 10]
(Justified by dataset: median PM pair has ~4-10 obs, so small windows
 are appropriate.  Larger windows are computed where data allows.)

All rolling calculations use min_periods=2 so they produce NaN rather
than a spurious value when fewer than 2 observations are available.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_WINDOWS: list[int] = [3, 5, 10]


# ---------------------------------------------------------------------------
# Core feature computation
# ---------------------------------------------------------------------------

def compute_price_features(
    series_df: pd.DataFrame,
    windows: Sequence[int] = DEFAULT_WINDOWS,
) -> pd.DataFrame:
    """
    Compute price features for a single (product_id, merchant) time series.

    Parameters
    ----------
    series_df:
        Chronologically sorted DataFrame for one PM pair.
        Must contain at minimum: ``price``, ``observed_at``.
    windows:
        Rolling window sizes.  Only windows ≤ len(series_df) will produce
        non-NaN results for the full window, but NaN values for partial
        windows are expected and correct.

    Returns
    -------
    pd.DataFrame
        Input columns preserved, feature columns appended.
        Sorted ascending by observed_at.
    """
    df = series_df.sort_values("observed_at").reset_index(drop=True).copy()

    n = len(df)

    # ------------------------------------------------------------------
    # Log-price
    # ------------------------------------------------------------------
    # Guard against zero or negative prices (should not occur after
    # preprocessing, but defensive coding is warranted).
    price_safe = df["price"].clip(lower=1e-9)
    df["log_price"] = np.log(price_safe)

    # Log-price difference (log-return): causal shift of 1
    df["log_price_diff"] = df["log_price"].diff()

    # ------------------------------------------------------------------
    # Rolling statistics on log_price
    # ------------------------------------------------------------------
    for w in windows:
        col_mean = f"rolling_mean_{w}"
        col_std = f"rolling_std_{w}"
        col_med = f"rolling_median_{w}"
        col_mean_raw = f"rolling_mean_price_{w}"

        roll_log = df["log_price"].rolling(window=w, min_periods=2)
        df[col_mean] = roll_log.mean()
        df[col_std] = roll_log.std()
        df[col_med] = df["log_price"].rolling(window=w, min_periods=2).median()

        df[col_mean_raw] = df["price"].rolling(window=w, min_periods=2).mean()

    # ------------------------------------------------------------------
    # Price volatility — rolling std of log_price_diff
    # ------------------------------------------------------------------
    for w in windows:
        col_vol = f"rolling_volatility_{w}"
        df[col_vol] = df["log_price_diff"].rolling(window=w, min_periods=2).std()

    # ------------------------------------------------------------------
    # Price deviation from rolling mean
    # ------------------------------------------------------------------
    for w in windows:
        mean_col = f"rolling_mean_{w}"
        if mean_col in df.columns:
            df[f"price_deviation_{w}"] = df["log_price"] - df[mean_col]

    # ------------------------------------------------------------------
    # Z-score of log_price within the series up to each point
    # (expanding window — uses all history up to t)
    # ------------------------------------------------------------------
    expanding = df["log_price"].expanding(min_periods=3)
    exp_mean = expanding.mean()
    exp_std = expanding.std()
    df["expanding_zscore"] = (df["log_price"] - exp_mean) / exp_std.replace(0, np.nan)

    # ------------------------------------------------------------------
    # Price direction flag
    # ------------------------------------------------------------------
    df["price_direction"] = np.where(
        df["absolute_change"].isna(), 0,
        np.where(df["absolute_change"] > 0, 1,
                 np.where(df["absolute_change"] < 0, -1, 0))
    ).astype(int)

    # ------------------------------------------------------------------
    # Cumulative price change from first observation
    # ------------------------------------------------------------------
    first_price = df["log_price"].iloc[0]
    df["cumulative_log_change"] = df["log_price"] - first_price

    return df


def compute_all_price_features(
    series_df: pd.DataFrame,
    windows: Sequence[int] = DEFAULT_WINDOWS,
    min_observations: int = 2,
) -> pd.DataFrame:
    """
    Compute price features for every (product_id, merchant) group in the
    flat series DataFrame.

    Parameters
    ----------
    series_df:
        Full flat series DataFrame from TimeSeriesCatalogue.series_df.
    windows:
        Rolling window sizes passed to compute_price_features.
    min_observations:
        Groups with fewer observations are included but will have mostly
        NaN feature values.  They are NOT dropped here — callers decide.

    Returns
    -------
    pd.DataFrame
        Same rows as input, feature columns added, sorted by
        (product_id, merchant, observed_at).
    """
    logger.info(
        "Computing price features for %d observations …", len(series_df)
    )
    parts: list[pd.DataFrame] = []

    for (pid, merch), group in series_df.groupby(
        ["product_id", "merchant"], sort=False
    ):
        if len(group) < min_observations:
            # Carry through without adding features (all NaN)
            g = group.sort_values("observed_at").reset_index(drop=True).copy()
            g["log_price"] = np.nan
            g["log_price_diff"] = np.nan
            g["expanding_zscore"] = np.nan
            g["price_direction"] = 0
            g["cumulative_log_change"] = np.nan
            for w in windows:
                for suffix in [
                    f"rolling_mean_{w}", f"rolling_std_{w}",
                    f"rolling_median_{w}", f"rolling_mean_price_{w}",
                    f"rolling_volatility_{w}", f"price_deviation_{w}",
                ]:
                    g[suffix] = np.nan
            parts.append(g)
        else:
            parts.append(compute_price_features(group, windows=windows))

    if not parts:
        logger.warning("No groups to compute features for.")
        return series_df.copy()

    result = pd.concat(parts, ignore_index=True)
    result = result.sort_values(
        ["product_id", "merchant", "observed_at"]
    ).reset_index(drop=True)

    logger.info(
        "Price features computed: %d rows, %d columns",
        len(result),
        len(result.columns),
    )
    return result


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def save_price_features(df: pd.DataFrame, output_path: str | Path) -> None:
    """Save the price features DataFrame to CSV."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    logger.info("Price features saved to: %s (%d rows)", output_path, len(df))


def load_price_features(input_path: str | Path) -> pd.DataFrame:
    """Load price features CSV with correct dtypes."""
    df = pd.read_csv(input_path)
    for col in ["observed_at", "date_added", "date_updated"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
    numeric_cols = [
        c for c in df.columns
        if c not in ["product_id", "merchant", "product_name", "brand",
                     "category", "availability", "condition", "offer",
                     "source_url", "manufacturer", "manufacturer_number",
                     "categories_raw", "asins", "upc", "ean", "weight",
                     "currency", "shipping", "observed_at",
                     "date_added", "date_updated"]
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "is_sale" in df.columns:
        df["is_sale"] = df["is_sale"].astype(str).str.upper().isin(["TRUE", "1"])
    logger.info("Price features loaded from: %s (%d rows)", input_path, len(df))
    return df
