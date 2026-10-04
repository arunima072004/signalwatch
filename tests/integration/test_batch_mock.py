"""tests/integration/test_batch_mock.py
Integration test: all 24 historical events through InvestigationOrchestrator
with MockSearchProvider.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.events.event_generator import ChangeEvent
from src.investigation.orchestrator import InvestigationOrchestrator
from src.models.verification import SupportLevel
from src.search.mock_provider import MockSearchProvider

EVENTS_FILE = ROOT / "data" / "events" / "change_events.json"


@pytest.fixture(scope="module")
def all_events():
    raw = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    return [ChangeEvent(**e) for e in raw]


@pytest.fixture(scope="module")
def all_assessments(tmp_path_factory, all_events):
    output_dir = tmp_path_factory.mktemp("assessments")
    provider = MockSearchProvider()
    results = []
    for event in all_events:
        orc = InvestigationOrchestrator(search_provider=provider, output_dir=output_dir)
        results.append(orc.investigate(event))
    return results


class TestBatchMockPipeline:

    def test_24_events_produce_assessments(self, all_events, all_assessments):
        assert len(all_assessments) == 24

    def test_no_assessment_is_none(self, all_assessments):
        for a in all_assessments:
            assert a is not None

    def test_every_assessment_has_event_id(self, all_events, all_assessments):
        event_ids = {e.event_id for e in all_events}
        for a in all_assessments:
            assert a.event_id in event_ids

    def test_every_assessment_has_at_least_one_hypothesis(self, all_assessments):
        for a in all_assessments:
            assert len(a.hypotheses) >= 1, "Event " + a.event_id + " produced no hypotheses"

    def test_every_assessment_has_hypothesis_assessments(self, all_assessments):
        for a in all_assessments:
            assert len(a.hypothesis_assessments) >= 1

    def test_all_support_levels_valid(self, all_assessments):
        valid = {sl.value for sl in SupportLevel}
        for a in all_assessments:
            for ha in a.hypothesis_assessments:
                assert ha.support_level.value in valid

    def test_every_evidence_item_has_provenance(self, all_assessments):
        for a in all_assessments:
            for ev in a.evidence:
                assert ev.evidence_id
                assert ev.event_id == a.event_id
                assert ev.query_id
                assert ev.source_url
                assert ev.hypothesis_type

    def test_every_evidence_item_has_strategy_tag(self, all_assessments):
        for a in all_assessments:
            for ev in a.evidence:
                assert ev.strategy, "Evidence " + ev.evidence_id + " missing strategy"

    def test_assessment_serializes_to_json(self, all_assessments):
        for a in all_assessments:
            d = a.to_dict()
            restored = json.loads(json.dumps(d, default=str))
            assert restored["event_id"] == a.event_id
            assert "hypothesis_assessments" in restored

    def test_queries_generated_is_positive(self, all_assessments):
        for a in all_assessments:
            assert a.queries_generated > 0

    def test_assessment_has_event_summary(self, all_assessments):
        required = {"event_id", "product_name", "merchant", "change_direction"}
        for a in all_assessments:
            for key in required:
                assert key in a.event_summary

    def test_no_provider_failures(self, all_assessments):
        for a in all_assessments:
            provider_fails = [f for f in a.agent_failures
                              if "search" in f.lower() or "provider" in f.lower()]
            assert not provider_fails, "Event " + a.event_id + " had provider failures"
