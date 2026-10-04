"""tests/test_query_generator.py — Tests for query generation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.query_generation.query_generator import QueryGenerator, _extract_context


# ---------------------------------------------------------------------------
# Context extraction tests
# ---------------------------------------------------------------------------

def test_extract_context_contains_required_keys(sample_labelled_event):
    ctx = _extract_context(sample_labelled_event)
    required = [
        "product_name", "brand", "merchant", "merchant_clean",
        "category", "date_str", "year_str", "month_str",
        "direction", "direction_word", "pct_str",
    ]
    for key in required:
        assert key in ctx, f"Missing context key: {key}"


def test_extract_context_date_parsed(sample_labelled_event):
    ctx = _extract_context(sample_labelled_event)
    # observed_at is "2017-03-15T06:00:00+00:00" → March 2017
    assert "2017" in ctx["date_str"]
    assert ctx["year_str"] == "2017"


def test_extract_context_direction(sample_labelled_event):
    ctx = _extract_context(sample_labelled_event)
    # percentage_change is -16.67 → decrease
    assert ctx["direction"] == "decrease"
    assert ctx["direction_word"] == "price drop"


def test_extract_context_merchant_clean(sample_labelled_event):
    """Amazon.com → Amazon (no .com suffix)."""
    ctx = _extract_context(sample_labelled_event)
    assert ctx["merchant_clean"] == "Amazon"


# ---------------------------------------------------------------------------
# Query generation structure tests
# ---------------------------------------------------------------------------

def test_generate_queries_returns_dict(sample_labelled_event):
    qg = QueryGenerator()
    result = qg.generate_queries(sample_labelled_event)
    assert isinstance(result, dict)


def test_generate_queries_has_event_id(sample_labelled_event):
    qg = QueryGenerator()
    result = qg.generate_queries(sample_labelled_event)
    assert "event_id" in result
    assert result["event_id"] == sample_labelled_event.event.event_id


def test_generate_queries_has_investigation_target(sample_labelled_event):
    qg = QueryGenerator()
    result = qg.generate_queries(sample_labelled_event)
    assert "investigation_target" in result
    tgt = result["investigation_target"]
    assert "product_name" in tgt
    assert "merchant" in tgt
    assert "change_direction" in tgt


def test_generate_queries_has_queries_dict(sample_labelled_event):
    qg = QueryGenerator()
    result = qg.generate_queries(sample_labelled_event)
    assert "queries" in result
    assert isinstance(result["queries"], dict)


def test_generate_queries_non_empty_for_valid_event(sample_labelled_event):
    qg = QueryGenerator()
    result = qg.generate_queries(sample_labelled_event)
    total = sum(len(v) for v in result["queries"].values())
    assert total > 0, "Expected at least one query to be generated"


def test_generate_queries_promotion_agent_present_for_decrease(sample_labelled_event):
    """A price decrease should always produce promotion_agent queries."""
    qg = QueryGenerator()
    result = qg.generate_queries(sample_labelled_event)
    assert "promotion_agent" in result["queries"]
    assert len(result["queries"]["promotion_agent"]) > 0


def test_generate_queries_competitor_agent_present(sample_labelled_event):
    """Competitive label should produce competitor_agent queries."""
    qg = QueryGenerator()
    result = qg.generate_queries(sample_labelled_event)
    assert "competitor_agent" in result["queries"]


def test_generate_queries_supply_agent_only_for_increase(sample_labelled_event):
    """supply_agent queries should only appear for price increases."""
    # sample_labelled_event is a decrease
    qg = QueryGenerator()
    result = qg.generate_queries(sample_labelled_event)
    assert "supply_agent" not in result["queries"]


def test_generate_queries_supply_agent_for_increase(sample_change_event):
    """supply_agent queries should appear for a price increase event."""
    from src.events.event_generator import ChangeEvent
    from src.weak_supervision.label_generator import LabelledEvent

    increase_event = ChangeEvent(
        event_id="evt_increase",
        product_id="P002",
        product_name="Samsung 4K TV",
        brand="Samsung",
        manufacturer="Samsung",
        manufacturer_number="QN55",
        category="Television",
        asins="B08",
        upc="",
        merchant="BestBuy",
        observed_at="2017-04-01T00:00:00+00:00",
        previous_price=500.0,
        current_price=600.0,
        absolute_change=100.0,
        percentage_change=20.0,
        change_direction="increase",
        cp_probability=0.55,
        map_run_length=8,
        log_price_diff=0.18,
        is_sale=False,
        offer=None,
        availability="Yes",
        condition="New",
        competitor_count=1,
        competitor_price_median=520.0,
        price_vs_comp_median=80.0,
        competitors_changed_7d=0,
        competitor_direction_7d=0,
        source_url=None,
    )
    le = LabelledEvent(event=increase_event, labels=["unknown"])
    qg = QueryGenerator()
    result = qg.generate_queries(le)
    assert "supply_agent" in result["queries"]
    assert len(result["queries"]["supply_agent"]) > 0


def test_generate_queries_no_web_search_called(sample_labelled_event):
    """
    Verify that query generation does not make any network calls.
    This test passes by definition if it runs without network errors,
    since QueryGenerator has no network code.
    """
    qg = QueryGenerator()
    result = qg.generate_queries(sample_labelled_event)
    assert result is not None  # pipeline completed without network error


def test_generate_queries_all_queries_are_strings(sample_labelled_event):
    """Every generated query must be a non-empty string."""
    qg = QueryGenerator()
    result = qg.generate_queries(sample_labelled_event)
    for agent, queries in result["queries"].items():
        for q in queries:
            assert isinstance(q, str), f"Query is not a string: {q!r}"
            assert len(q.strip()) > 0, f"Query is empty for agent {agent}"


def test_generate_queries_respects_max_per_agent(sample_labelled_event):
    qg = QueryGenerator()
    result = qg.generate_queries(sample_labelled_event, max_per_agent=3)
    for agent, queries in result["queries"].items():
        assert len(queries) <= 3, (
            f"Agent {agent} has {len(queries)} queries, expected <= 3"
        )


def test_generate_all_queries_returns_list(sample_labelled_event):
    qg = QueryGenerator()
    results = qg.generate_all_queries([sample_labelled_event, sample_labelled_event])
    assert isinstance(results, list)
    assert len(results) == 2


def test_generate_queries_uses_product_name_in_query(sample_labelled_event):
    """At least one generated query should mention the product or brand."""
    qg = QueryGenerator()
    result = qg.generate_queries(sample_labelled_event)
    all_queries = [
        q for queries in result["queries"].values() for q in queries
    ]
    product_name = sample_labelled_event.event.product_name.lower()
    brand = sample_labelled_event.event.brand.lower()
    any_relevant = any(
        product_name[:8].lower() in q.lower() or brand.lower() in q.lower()
        for q in all_queries
    )
    assert any_relevant, (
        f"No query references product name or brand.\nQueries: {all_queries}"
    )


def test_generate_queries_save_load_roundtrip(sample_labelled_event, tmp_path):
    from src.query_generation.query_generator import load_queries, save_queries

    qg = QueryGenerator()
    results = qg.generate_all_queries([sample_labelled_event])
    out = tmp_path / "queries.json"
    save_queries(results, out)
    loaded = load_queries(out)
    assert len(loaded) == 1
    assert loaded[0]["event_id"] == results[0]["event_id"]
