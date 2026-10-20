"""
src/adapters/csv_adapter.py
============================
CsvAdapter converts existing Phase 1 cleaned data (cleaned_data.csv)
into PriceObservation objects.

Phase 1 outputs are NOT modified.  This adapter reads them read-only.
"""
from __future__ import annotations

import logging
from datetime import timezone
from typing import List, Optional

import pandas as pd

from src.adapters.base import PriceSource
from src.adapters.price_observation import PriceObservation

logger = logging.getLogger(__name__)

_BOOL_MAP = {"true": True, "false": False, "1": True, "0": False}


def _to_optional_bool(val) -> Optional[bool]:
    """Convert is_sale to True/False/None. None = unknown, never default False."""
    if pd.isna(val) or val is None:
        return None
    s = str(val).strip().lower()
    return _BOOL_MAP.get(s)


def _nonempty(val) -> Optional[str]:
    """Return stripped string or None if empty/NaN."""
    if pd.isna(val) or val is None:
        return None
    s = str(val).strip()
    return s if s else None


class CsvAdapter(PriceSource):
    """
    Reads the Phase 1 cleaned_data.csv and returns PriceObservation objects.

    Parameters
    ----------
    csv_path : str or Path
        Path to cleaned_data.csv (or any Phase 1 cleaned CSV with the
        expected column schema).
    """

    def __init__(self, csv_path: str) -> None:
        self._csv_path = str(csv_path)
        self._df: Optional[pd.DataFrame] = None

    @property
    def source_name(self) -> str:
        return "csv"

    def _load(self) -> pd.DataFrame:
        if self._df is None:
            logger.info("CsvAdapter: loading %s", self._csv_path)
            self._df = pd.read_csv(
                self._csv_path,
                parse_dates=["observed_at"],
                low_memory=False,
            )
        return self._df

    def fetch_observations(
        self,
        watchlist: List[str],
        since: Optional[str] = None,
    ) -> List[PriceObservation]:
        """Return all observations for watchlist product_ids."""
        df = self._load()

        if watchlist:
            df = df[df["product_id"].isin(watchlist)]

        if since:
            cutoff = pd.to_datetime(since, utc=True)
            df = df[pd.to_datetime(df["observed_at"], utc=True) > cutoff]

        observations: List[PriceObservation] = []
        for _, row in df.iterrows():
            price_val = row.get("price")
            if pd.isna(price_val):
                continue

            obs_at = row.get("observed_at")
            if pd.isna(obs_at):
                continue
            ts = pd.to_datetime(obs_at, utc=True)
            observed_at_str = ts.isoformat()

            observations.append(PriceObservation(
                product_id=str(row["product_id"]),
                product_name=_nonempty(row.get("product_name")) or str(row["product_id"]),
                merchant=str(row["merchant"]),
                observed_at=observed_at_str,
                price=float(price_val),
                currency=_nonempty(row.get("currency")) or "USD",
                availability=_nonempty(row.get("availability")),
                condition=_nonempty(row.get("condition")),
                is_sale=_to_optional_bool(row.get("is_sale")),
                shipping=_nonempty(row.get("shipping")),
                product_url=_nonempty(row.get("source_url")),
                brand=_nonempty(row.get("brand")),
                category=_nonempty(row.get("category")),
                manufacturer=_nonempty(row.get("manufacturer")),
                asin=_nonempty(row.get("asins")),
                ean=_nonempty(row.get("ean")),
                upc=_nonempty(row.get("upc")),
                manufacturer_number=_nonempty(row.get("manufacturer_number")),
                source="csv",
            ))
        logger.info("CsvAdapter: returned %d observations", len(observations))
        return observations

    def all_observations_sorted(self) -> List[PriceObservation]:
        """Return all observations sorted chronologically (for replay use)."""
        obs = self.fetch_observations(watchlist=[])
        obs.sort(key=lambda o: o.observed_at)
        return obs
