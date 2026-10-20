"""
src/storage/repository.py
==========================
Abstract repository interface for SignalWatch Phase 3 storage.

All pipeline components depend on this interface, never on the SQLite
implementation directly.  Swapping to PostgreSQL later requires only a
new implementation class.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from src.adapters.price_observation import PriceObservation


class SignalWatchRepository(ABC):

    # ------------------------------------------------------------------
    # Watchlist
    # ------------------------------------------------------------------

    @abstractmethod
    def add_to_watchlist(self, product_id: str, product_name: str) -> None:
        """Add a product to the watchlist (idempotent)."""
        ...

    @abstractmethod
    def remove_from_watchlist(self, product_id: str) -> None:
        ...

    @abstractmethod
    def get_watchlist(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """Return watchlist rows as dicts."""
        ...

    # ------------------------------------------------------------------
    # Observations
    # ------------------------------------------------------------------

    @abstractmethod
    def upsert_observation(self, obs: PriceObservation) -> bool:
        """
        Insert observation.  Idempotent: a duplicate (same product_id,
        merchant, observed_at) is silently ignored.
        Returns True if a new row was inserted, False if it was a duplicate.
        """
        ...

    @abstractmethod
    def get_observations(
        self,
        product_id: str,
        merchant: str,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        ...

    # ------------------------------------------------------------------
    # BOCPD state
    # ------------------------------------------------------------------

    @abstractmethod
    def save_bocpd_state(
        self,
        product_id: str,
        merchant: str,
        state: Dict[str, Any],
        last_price: float,
        last_observed_at: str,
        observation_count: int,
    ) -> None:
        ...

    @abstractmethod
    def load_bocpd_state(
        self, product_id: str, merchant: str
    ) -> Optional[Dict[str, Any]]:
        """Return the stored state dict or None if no state exists yet."""
        ...

    # ------------------------------------------------------------------
    # Change events
    # ------------------------------------------------------------------

    @abstractmethod
    def save_change_event(self, event_dict: Dict[str, Any]) -> None:
        """Store a ChangeEvent dict with status NEW (idempotent on event_id)."""
        ...

    @abstractmethod
    def get_events_by_status(self, status: str) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def update_event_status(self, event_id: str, status: str, error: Optional[str] = None) -> None:
        """Valid statuses: NEW, INVESTIGATING, INVESTIGATED, FAILED."""
        ...

    # ------------------------------------------------------------------
    # Assessments
    # ------------------------------------------------------------------

    @abstractmethod
    def save_assessment(self, event_id: str, assessment_dict: Dict[str, Any]) -> None:
        """Save EventAssessment dict (idempotent on event_id)."""
        ...

    @abstractmethod
    def get_assessment(self, event_id: str) -> Optional[Dict[str, Any]]:
        ...

    # ------------------------------------------------------------------
    # Pipeline runs
    # ------------------------------------------------------------------

    @abstractmethod
    def start_pipeline_run(self) -> str:
        """Create a pipeline_runs row and return its run_id."""
        ...

    @abstractmethod
    def finish_pipeline_run(
        self,
        run_id: str,
        observations_ingested: int,
        events_created: int,
        events_investigated: int,
        search_queries_used: int,
        channel3_calls_used: int,
        errors: List[str],
    ) -> None:
        ...
