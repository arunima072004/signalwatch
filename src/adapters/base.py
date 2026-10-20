"""
src/adapters/base.py
=====================
PriceSource abstract interface.

Every data source adapter implements this interface.  The pipeline
runner calls fetch_observations() once per cycle and processes
the returned list in chronological order.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from src.adapters.price_observation import PriceObservation


class PriceSource(ABC):
    """
    Abstract base for all price data sources.

    Parameters
    ----------
    watchlist : list[str]
        Product IDs (in whatever format the source uses) to monitor.
    """

    @abstractmethod
    def fetch_observations(
        self,
        watchlist: List[str],
        since: Optional[str] = None,
    ) -> List[PriceObservation]:
        """
        Fetch current price observations for all watchlist products.

        Parameters
        ----------
        watchlist : list[str]
            Product IDs to fetch prices for.
        since : str, optional
            ISO-8601 UTC timestamp.  If provided, the source MAY return
            only observations newer than this timestamp (best-effort;
            sources that only provide current prices ignore this).

        Returns
        -------
        list[PriceObservation]
            Observations in no guaranteed order.  Caller must sort
            chronologically before feeding to the incremental detector.
        """
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Short identifier used in logging and provenance tracking."""
        ...
