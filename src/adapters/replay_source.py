"""
src/adapters/replay_source.py
==============================
ReplaySource: streams historical PriceObservations in strict chronological
order, simulating a live polling cycle without touching any paid API.

Design
------
The source maintains an internal simulated clock.  Each call to
fetch_observations() advances the clock by window_days and returns
only observations that fall within [clock, clock + window_days).

The future is never exposed: observations after the current simulated
clock are withheld until the clock advances past them.

Usage
-----
    source = ReplaySource(all_observations, window_days=7)
    while source.has_more():
        batch = source.fetch_observations(watchlist=[])
        process(batch)
        source.advance()
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from src.adapters.base import PriceSource
from src.adapters.price_observation import PriceObservation

logger = logging.getLogger(__name__)


class ReplaySource(PriceSource):
    """
    Streams historical observations in windows, never leaking future data.

    Parameters
    ----------
    observations : list[PriceObservation]
        All historical observations, in any order.  ReplaySource sorts them.
    window_days : float
        How many days of data to release per cycle. Default 7.
    start_at : str, optional
        ISO-8601 UTC timestamp to start from.
        Defaults to the earliest observation timestamp.
    """

    def __init__(
        self,
        observations: List[PriceObservation],
        window_days: float = 7.0,
        start_at: Optional[str] = None,
    ) -> None:
        self._all = sorted(observations, key=lambda o: o.observed_at)
        self._window = timedelta(days=window_days)
        self._cursor: int = 0

        if not self._all:
            self._clock = datetime.now(timezone.utc)
        elif start_at:
            self._clock = datetime.fromisoformat(start_at)
            if self._clock.tzinfo is None:
                self._clock = self._clock.replace(tzinfo=timezone.utc)
        else:
            self._clock = datetime.fromisoformat(self._all[0].observed_at)
            if self._clock.tzinfo is None:
                self._clock = self._clock.replace(tzinfo=timezone.utc)

    @property
    def source_name(self) -> str:
        return "replay"

    @property
    def current_clock(self) -> datetime:
        return self._clock

    def has_more(self) -> bool:
        """True if there are more observations to release."""
        return self._cursor < len(self._all)

    def fetch_observations(
        self,
        watchlist: List[str],
        since: Optional[str] = None,
    ) -> List[PriceObservation]:
        """
        Return observations in [clock, clock + window_days).
        Advances the cursor but NOT the clock — call advance() to move time.
        """
        window_end = self._clock + self._window
        batch: List[PriceObservation] = []

        for obs in self._all[self._cursor:]:
            obs_dt = datetime.fromisoformat(obs.observed_at)
            if obs_dt.tzinfo is None:
                obs_dt = obs_dt.replace(tzinfo=timezone.utc)
            if obs_dt >= window_end:
                break
            if obs_dt >= self._clock:
                if not watchlist or obs.product_id in watchlist:
                    batch.append(obs)
                self._cursor += 1

        logger.debug(
            "ReplaySource: clock=%s window_end=%s released=%d",
            self._clock.isoformat(), window_end.isoformat(), len(batch),
        )
        return batch

    def advance(self) -> None:
        """Advance the simulated clock by one window."""
        self._clock += self._window
