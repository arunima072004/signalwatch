"""
tests/storage/test_sqlite_repository.py
=========================================
Stage 2 tests for SqliteRepository using in-memory SQLite.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.adapters.price_observation import PriceObservation
from src.storage.sqlite_repository import SqliteRepository


@pytest.fixture
def repo():
    r = SqliteRepository(":memory:")
    yield r
    r.close()


def _obs(product_id="P1", merchant="shop.com", price=99.99,
         observed_at="2017-01-15T12:00:00+00:00", is_sale=None) -> PriceObservation:
    return PriceObservation(
        product_id=product_id,
        product_name="Test Product",
        merchant=merchant,
        observed_at=observed_at,
        price=price,
        currency="USD",
        is_sale=is_sale,
        availability="InStock",
        source="test",
    )


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

class TestWatchlist:

    def test_add_and_get(self, repo):
        repo.add_to_watchlist("P1", "Product One")
        wl = repo.get_watchlist()
        assert len(wl) == 1
        assert wl[0]["product_id"] == "P1"
        assert wl[0]["active"] == 1

    def test_add_is_idempotent(self, repo):
        repo.add_to_watchlist("P1", "Product One")
        repo.add_to_watchlist("P1", "Product One Updated")
        wl = repo.get_watchlist()
        assert len(wl) == 1
        assert wl[0]["product_name"] == "Product One Updated"

    def test_remove_deactivates(self, repo):
        repo.add_to_watchlist("P1", "Product One")
        repo.remove_from_watchlist("P1")
        wl = repo.get_watchlist(active_only=True)
        assert len(wl) == 0
        wl_all = repo.get_watchlist(active_only=False)
        assert len(wl_all) == 1
        assert wl_all[0]["active"] == 0

    def test_re_adding_reactivates(self, repo):
        repo.add_to_watchlist("P1", "Product One")
        repo.remove_from_watchlist("P1")
        repo.add_to_watchlist("P1", "Product One")
        wl = repo.get_watchlist(active_only=True)
        assert len(wl) == 1


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------

class TestObservations:

    def test_upsert_returns_true_for_new(self, repo):
        inserted = repo.upsert_observation(_obs())
        assert inserted is True

    def test_upsert_idempotent_returns_false_for_duplicate(self, repo):
        repo.upsert_observation(_obs())
        inserted_again = repo.upsert_observation(_obs())
        assert inserted_again is False

    def test_get_observations_returns_inserted(self, repo):
        repo.upsert_observation(_obs("P1", "shop.com", 99.99, "2017-01-15T12:00:00+00:00"))
        rows = repo.get_observations("P1", "shop.com")
        assert len(rows) == 1
        assert rows[0]["price"] == 99.99

    def test_is_sale_null_preserved(self, repo):
        repo.upsert_observation(_obs(is_sale=None))
        rows = repo.get_observations("P1", "shop.com")
        assert rows[0]["is_sale"] is None

    def test_is_sale_true_preserved(self, repo):
        repo.upsert_observation(_obs(is_sale=True))
        rows = repo.get_observations("P1", "shop.com")
        assert rows[0]["is_sale"] is True

    def test_is_sale_false_preserved(self, repo):
        repo.upsert_observation(_obs(is_sale=False))
        rows = repo.get_observations("P1", "shop.com")
        assert rows[0]["is_sale"] is False

    def test_since_filter(self, repo):
        repo.upsert_observation(_obs(observed_at="2017-01-10T00:00:00+00:00"))
        repo.upsert_observation(_obs(observed_at="2017-01-20T00:00:00+00:00"))
        rows = repo.get_observations("P1", "shop.com", since="2017-01-15T00:00:00+00:00")
        assert len(rows) == 1
        assert "2017-01-20" in rows[0]["observed_at"]

    def test_different_merchants_stored_separately(self, repo):
        repo.upsert_observation(_obs("P1", "shop1.com"))
        repo.upsert_observation(_obs("P1", "shop2.com"))
        assert len(repo.get_observations("P1", "shop1.com")) == 1
        assert len(repo.get_observations("P1", "shop2.com")) == 1


# ---------------------------------------------------------------------------
# BOCPD state
# ---------------------------------------------------------------------------

class TestBocpdState:

    def _sample_state(self):
        return {
            "mu": [0.0, 0.1],
            "kappa": [1.0, 2.0],
            "alpha": [1.0, 1.5],
            "beta": [0.04, 0.05],
            "run_length_posterior": [0.01, 0.99],
            "t": 5,
        }

    def test_save_and_load_round_trip(self, repo):
        state = self._sample_state()
        repo.save_bocpd_state("P1", "shop.com", state, 99.99, "2017-01-15T12:00:00+00:00", 5)
        loaded = repo.load_bocpd_state("P1", "shop.com")
        assert loaded is not None
        assert loaded["state"]["t"] == 5
        assert loaded["last_price"] == 99.99
        assert loaded["observation_count"] == 5

    def test_load_nonexistent_returns_none(self, repo):
        assert repo.load_bocpd_state("MISSING", "shop.com") is None

    def test_save_overwrites_previous(self, repo):
        state1 = self._sample_state()
        repo.save_bocpd_state("P1", "shop.com", state1, 100.0, "2017-01-15T12:00:00+00:00", 5)
        state2 = {**state1, "t": 10}
        repo.save_bocpd_state("P1", "shop.com", state2, 110.0, "2017-01-20T12:00:00+00:00", 10)
        loaded = repo.load_bocpd_state("P1", "shop.com")
        assert loaded["state"]["t"] == 10
        assert loaded["last_price"] == 110.0

    def test_arrays_preserved_exactly(self, repo):
        state = self._sample_state()
        repo.save_bocpd_state("P1", "shop.com", state, 99.99, "2017-01-15T12:00:00+00:00", 5)
        loaded = repo.load_bocpd_state("P1", "shop.com")
        assert loaded["state"]["mu"] == [0.0, 0.1]
        assert loaded["state"]["run_length_posterior"] == [0.01, 0.99]


# ---------------------------------------------------------------------------
# Change events
# ---------------------------------------------------------------------------

class TestChangeEvents:

    def _event(self, event_id="evt_001"):
        return {
            "event_id": event_id,
            "product_id": "P1",
            "merchant": "shop.com",
            "product_name": "Test Product",
            "observed_at": "2017-01-15T12:00:00+00:00",
            "change_direction": "decrease",
            "percentage_change": -15.0,
        }

    def test_save_and_retrieve_by_status(self, repo):
        repo.save_change_event(self._event())
        rows = repo.get_events_by_status("NEW")
        assert len(rows) == 1
        assert rows[0]["event"]["event_id"] == "evt_001"

    def test_save_is_idempotent(self, repo):
        repo.save_change_event(self._event())
        repo.save_change_event(self._event())
        rows = repo.get_events_by_status("NEW")
        assert len(rows) == 1

    def test_status_transitions(self, repo):
        repo.save_change_event(self._event())
        repo.update_event_status("evt_001", "INVESTIGATING")
        assert len(repo.get_events_by_status("NEW")) == 0
        assert len(repo.get_events_by_status("INVESTIGATING")) == 1

        repo.update_event_status("evt_001", "INVESTIGATED")
        assert len(repo.get_events_by_status("INVESTIGATING")) == 0
        assert len(repo.get_events_by_status("INVESTIGATED")) == 1

    def test_failed_status_stores_error(self, repo):
        repo.save_change_event(self._event())
        repo.update_event_status("evt_001", "FAILED", error="search timed out")
        rows = repo.get_events_by_status("FAILED")
        assert len(rows) == 1
        assert rows[0]["error"] == "search timed out"

    def test_invalid_status_raises(self, repo):
        repo.save_change_event(self._event())
        with pytest.raises(ValueError, match="Invalid status"):
            repo.update_event_status("evt_001", "UNKNOWN_STATUS")


# ---------------------------------------------------------------------------
# Assessments
# ---------------------------------------------------------------------------

class TestAssessments:

    def test_save_and_get_assessment(self, repo):
        assessment = {"assessment_id": "asmnt_001", "event_id": "evt_001", "summary": "test"}
        repo.save_assessment("evt_001", assessment)
        loaded = repo.get_assessment("evt_001")
        assert loaded is not None
        assert loaded["assessment"]["assessment_id"] == "asmnt_001"

    def test_get_nonexistent_returns_none(self, repo):
        assert repo.get_assessment("missing") is None

    def test_save_replaces_existing(self, repo):
        repo.save_assessment("evt_001", {"v": 1})
        repo.save_assessment("evt_001", {"v": 2})
        loaded = repo.get_assessment("evt_001")
        assert loaded["assessment"]["v"] == 2


# ---------------------------------------------------------------------------
# Pipeline runs
# ---------------------------------------------------------------------------

class TestPipelineRuns:

    def test_start_and_finish(self, repo):
        run_id = repo.start_pipeline_run()
        assert run_id.startswith("run_")
        repo.finish_pipeline_run(
            run_id=run_id,
            observations_ingested=10,
            events_created=2,
            events_investigated=1,
            search_queries_used=15,
            channel3_calls_used=3,
            errors=[],
        )
        row = repo._connect().execute(
            "SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        assert row is not None
        assert row["observations_ingested"] == 10
        assert row["events_created"] == 2
        assert row["finished_at"] is not None
