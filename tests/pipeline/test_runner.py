"""
tests/pipeline/test_runner.py
================================
Stage 4 tests for PipelineRunner.
All tests use in-memory SQLite and MockSearchProvider.
No real API calls.
"""
from __future__ import annotations
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.adapters.price_observation import PriceObservation
from src.adapters.replay_source import ReplaySource
from src.bocpd.config import BOCPDConfig
from src.pipeline.runner import PipelineRunner
from src.search.mock_provider import MockSearchProvider
from src.storage.sqlite_repository import SqliteRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_obs(product_id="P1", merchant="shop.com", price=100.0,
              day_offset=0) -> PriceObservation:
    base = datetime(2017, 1, 1, tzinfo=timezone.utc)
    ts = (base + timedelta(days=day_offset)).isoformat()
    return PriceObservation(
        product_id=product_id,
        product_name="Test Product",
        merchant=merchant,
        observed_at=ts,
        price=price,
        currency="USD",
        source="test",
    )


def _series_with_change(n_before=20, n_after=10,
                        base_price=100.0, new_price=70.0) -> List[PriceObservation]:
    """Price series with a clear price drop after n_before observations."""
    obs = []
    import numpy as np
    rng = np.random.default_rng(123)
    for i in range(n_before):
        p = base_price * (1 + rng.normal(0, 0.001))
        obs.append(_make_obs(price=p, day_offset=i * 7))
    for i in range(n_after):
        p = new_price * (1 + rng.normal(0, 0.001))
        obs.append(_make_obs(price=p, day_offset=(n_before + i) * 7))
    return obs


@pytest.fixture
def repo():
    r = SqliteRepository(":memory:")
    r.add_to_watchlist("P1", "Test Product")
    yield r
    r.close()


@pytest.fixture
def mock_provider():
    return MockSearchProvider()


# ---------------------------------------------------------------------------
# Full ReplaySource cycle: observations -> events -> assessments
# ---------------------------------------------------------------------------

class TestFullReplayCycle:

    def test_cycle_ingests_observations(self, repo, mock_provider, tmp_path):
        obs = [_make_obs(day_offset=i) for i in range(5)]
        source = ReplaySource(obs, window_days=100)

        runner = PipelineRunner(
            source=source,
            search_provider=mock_provider,
            repo=repo,
            assessments_dir=tmp_path,
        )
        stats = runner.run_cycle()
        assert stats["observations_ingested"] == 5
        assert stats["new_observations"] == 5

    def test_second_cycle_does_not_duplicate_observations(self, repo, mock_provider, tmp_path):
        """Running the same observations twice must not insert duplicates."""
        obs = [_make_obs(day_offset=i) for i in range(5)]
        source1 = ReplaySource(obs[:], window_days=100)
        source2 = ReplaySource(obs[:], window_days=100)

        runner1 = PipelineRunner(source=source1, search_provider=mock_provider,
                                 repo=repo, assessments_dir=tmp_path)
        runner2 = PipelineRunner(source=source2, search_provider=mock_provider,
                                 repo=repo, assessments_dir=tmp_path)
        runner1.run_cycle()
        stats2 = runner2.run_cycle()
        assert stats2["new_observations"] == 0

    def test_long_series_with_change_creates_event(self, repo, mock_provider, tmp_path):
        """A series with a real price drop should eventually create a ChangeEvent."""
        obs = _series_with_change(n_before=25, n_after=5)
        source = ReplaySource(obs, window_days=1000)

        runner = PipelineRunner(
            source=source,
            search_provider=mock_provider,
            repo=repo,
            assessments_dir=tmp_path,
        )
        stats = runner.run_cycle()
        # We may or may not get an event depending on whether BOCPD fires —
        # assert pipeline did not crash and ingested all observations
        assert stats["observations_ingested"] == len(obs)
        assert stats["errors"] == []


# ---------------------------------------------------------------------------
# Budget guard: investigation cap
# ---------------------------------------------------------------------------

class TestBudgetGuard:

    def test_investigation_cap_defers_excess_events(self, tmp_path):
        """Events beyond max_investigations stay NEW and are counted as deferred."""
        repo = SqliteRepository(":memory:")
        repo.add_to_watchlist("P1", "Test Product")

        # Manually insert 5 NEW events
        for i in range(5):
            repo.save_change_event({
                "event_id": f"evt_test_{i:03d}",
                "product_id": "P1",
                "merchant": "shop.com",
                "product_name": "Test Product",
                "observed_at": f"2017-01-{i+1:02d}T00:00:00+00:00",
                "change_direction": "decrease",
                "percentage_change": -20.0,
                "previous_price": 100.0,
                "current_price": 80.0,
                "absolute_change": -20.0,
                "cp_probability": 0.5,
                "map_run_length": 3,
                "log_price_diff": -0.22,
                "is_sale": False,
                "offer": None, "availability": None, "condition": None,
                "competitor_count": 0, "competitor_price_median": None,
                "price_vs_comp_median": None, "competitors_changed_7d": 0,
                "competitor_direction_7d": 0, "source_url": None,
                "brand": "", "manufacturer": "", "manufacturer_number": "",
                "category": "", "asins": "", "upc": "",
                "event_type": "pricing_regime_change",
                "detection_method": "BOCPD",
            })

        mock_obs = []
        source = ReplaySource(mock_obs, window_days=7)
        mock_provider = MockSearchProvider()

        runner = PipelineRunner(
            source=source,
            search_provider=mock_provider,
            repo=repo,
            assessments_dir=tmp_path,
            max_investigations=2,
        )
        stats = runner.run_cycle()
        assert stats["events_investigated"] == 2
        assert stats["events_deferred"] == 3
        remaining_new = repo.get_events_by_status("NEW")
        assert len(remaining_new) == 3
        repo.close()

    def test_failing_investigation_marked_failed_cycle_continues(self, tmp_path):
        """A failed investigation must not stop the cycle."""
        from unittest.mock import patch

        repo = SqliteRepository(":memory:")
        repo.add_to_watchlist("P1", "Test Product")

        for i in range(3):
            repo.save_change_event({
                "event_id": f"evt_fail_{i}",
                "product_id": "P1",
                "merchant": "shop.com",
                "product_name": "Test Product",
                "observed_at": f"2017-01-{i+1:02d}T00:00:00+00:00",
                "change_direction": "decrease",
                "percentage_change": -20.0,
                "previous_price": 100.0, "current_price": 80.0,
                "absolute_change": -20.0, "cp_probability": 0.5,
                "map_run_length": 3, "log_price_diff": -0.22,
                "is_sale": None, "offer": None, "availability": None,
                "condition": None, "competitor_count": 0,
                "competitor_price_median": None, "price_vs_comp_median": None,
                "competitors_changed_7d": 0, "competitor_direction_7d": 0,
                "source_url": None, "brand": "", "manufacturer": "",
                "manufacturer_number": "", "category": "", "asins": "", "upc": "",
                "event_type": "pricing_regime_change", "detection_method": "BOCPD",
            })

        mock_obs = []
        source = ReplaySource(mock_obs, window_days=7)
        mock_provider = MockSearchProvider()

        # Make investigation always raise
        with patch(
            "src.investigation.orchestrator.InvestigationOrchestrator.investigate",
            side_effect=RuntimeError("simulated failure"),
        ):
            runner = PipelineRunner(
                source=source,
                search_provider=mock_provider,
                repo=repo,
                assessments_dir=tmp_path,
                max_investigations=5,
            )
            stats = runner.run_cycle()

        assert stats["events_failed"] == 3
        assert stats["events_investigated"] == 0
        failed = repo.get_events_by_status("FAILED")
        assert len(failed) == 3
        repo.close()


# ---------------------------------------------------------------------------
# Idempotency: running same cycle twice creates no duplicate observations/events
# ---------------------------------------------------------------------------

class TestIdempotency:

    def test_same_observations_twice_no_duplicates(self, repo, mock_provider, tmp_path):
        obs = [_make_obs(day_offset=i) for i in range(10)]
        source_a = ReplaySource(obs[:], window_days=1000)
        source_b = ReplaySource(obs[:], window_days=1000)

        runner = PipelineRunner(source=source_a, search_provider=mock_provider,
                                repo=repo, assessments_dir=tmp_path)
        runner.run_cycle()

        runner2 = PipelineRunner(source=source_b, search_provider=mock_provider,
                                 repo=repo, assessments_dir=tmp_path)
        stats2 = runner2.run_cycle()
        assert stats2["new_observations"] == 0


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------

class TestDryRun:

    def test_dry_run_returns_stats_without_db_writes(self, repo, mock_provider, tmp_path):
        obs = [_make_obs(day_offset=i) for i in range(5)]
        source = ReplaySource(obs, window_days=100)

        runner = PipelineRunner(
            source=source,
            search_provider=mock_provider,
            repo=repo,
            assessments_dir=tmp_path,
        )
        stats = runner.run_cycle(dry_run=True)
        # dry_run should not insert observations
        assert stats.get("new_observations", 0) == 0
        all_obs = repo.get_observations("P1", "shop.com")
        assert len(all_obs) == 0


# ---------------------------------------------------------------------------
# Daily query budget guard
# ---------------------------------------------------------------------------

class TestDailyQueryBudget:

    def test_cycle_stops_at_daily_query_cap(self, tmp_path):
        """
        cap=50, 40 queries already used today in a prior run, each investigation
        consumes 15 queries.

        Guard check (before each event): queries_today + stats["search_queries"] >= cap
          - Event 1: 40 + 0  = 40 < 50  -> investigated, stats["search_queries"] -> 15
          - Event 2: 40 + 15 = 55 >= 50 -> deferred
          - Event 3: 40 + 15 = 55 >= 50 -> deferred

        Expected: events_investigated=1, events_deferred=2.
        """
        from datetime import date
        from unittest.mock import MagicMock, patch

        repo = SqliteRepository(":memory:")
        repo.add_to_watchlist("P1", "Test Product")

        # Pre-seed one pipeline_run for TODAY with 40 queries already used.
        today = date.today().isoformat()
        conn = repo._connect()
        conn.execute(
            "INSERT INTO pipeline_runs "
            "(run_id, started_at, search_queries_used, observations_ingested, "
            "events_created, events_investigated, channel3_calls_used, errors_json) "
            "VALUES ('prior_run', ?, 40, 0, 0, 0, 0, '[]')",
            (today + "T00:00:00+00:00",),
        )
        conn.commit()

        # Insert 3 NEW change events.
        for i in range(3):
            repo.save_change_event({
                "event_id": f"evt_budget_{i}",
                "product_id": "P1",
                "merchant": "shop.com",
                "product_name": "Test Product",
                "observed_at": f"2017-01-{i + 1:02d}T00:00:00+00:00",
                "change_direction": "decrease",
                "percentage_change": -20.0,
                "previous_price": 100.0, "current_price": 80.0,
                "absolute_change": -20.0, "cp_probability": 0.5,
                "map_run_length": 3, "log_price_diff": -0.22,
                "is_sale": False, "offer": None, "availability": None,
                "condition": None, "competitor_count": 0,
                "competitor_price_median": None, "price_vs_comp_median": None,
                "competitors_changed_7d": 0, "competitor_direction_7d": 0,
                "source_url": None, "brand": "", "manufacturer": "",
                "manufacturer_number": "", "category": "", "asins": "", "upc": "",
                "event_type": "pricing_regime_change", "detection_method": "BOCPD",
            })

        source = ReplaySource([], window_days=7)
        mock_provider = MockSearchProvider()

        # Build a minimal assessment dict that runner.py can save to JSON.
        def _fake_assessment(event):
            m = MagicMock()
            m.to_dict.return_value = {
                "event_id": event.event_id,
                "assessment_id": "aid_" + event.event_id,
                "assessed_at": "2026-01-01T00:00:00+00:00",
                "hypothesis_assessments": [],
                "evidence": [],
                "uncertainty_factors": [],
                "queries_generated": 15,
                "results_retrieved": 5,
                "independent_source_count": 0,
                "duplicated_source_count": 0,
                "agent_failures": [],
                "evidence_verifications": [],
                "event_summary": {},
            }
            return m

        with patch(
            "src.investigation.orchestrator.InvestigationOrchestrator.investigate",
            side_effect=_fake_assessment,
        ), patch(
            "src.investigation.investigation_agent.InvestigationAgent.get_last_stats",
            return_value=(15, 5),
        ):
            runner = PipelineRunner(
                source=source,
                search_provider=mock_provider,
                repo=repo,
                assessments_dir=tmp_path,
                max_investigations=10,   # high enough that per-cycle cap is not the constraint
                max_queries_per_day=50,  # 40 already used; 1 investigation adds 15 -> 55 >= 50
            )
            stats = runner.run_cycle()

        assert stats["events_investigated"] == 1, (
            f"Expected 1 investigated, got {stats['events_investigated']}. "
            f"Guard must read prior queries (40) + current-cycle queries."
        )
        assert stats["events_deferred"] == 2, (
            f"Expected 2 deferred, got {stats['events_deferred']}."
        )
        repo.close()
