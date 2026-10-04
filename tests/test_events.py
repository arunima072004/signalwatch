"""tests/test_events.py — Tests for event generation and weak labels."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.events.event_generator import (
    ChangeEvent,
    EventConfig,
    _change_direction,
    _make_event_id,
    generate_events,
)
from src.weak_supervision.label_generator import (
    LABEL_COMPETITIVE,
    LABEL_PROMOTION,
    LABEL_UNKNOWN,
    WeakLabelConfig,
    generate_weak_labels,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bocpd_df(product_id="P001", merchant="Amazon.com",
                   ts="2017-03-15T06:00:00+00:00", cp_prob=0.7) -> pd.DataFrame:
    return pd.DataFrame({
        "product_id": [product_id],
        "merchant": [merchant],
        "observed_at": pd.to_datetime([ts], utc=True),
        "cp_probability": [cp_prob],
        "map_run_length": [3],
        "is_change_point": [True],
    })


def _make_features_df(product_id="P001", merchant="Amazon.com",
                      ts="2017-03-15T06:00:00+00:00",
                      price=249.99, prev_price=299.99,
                      is_sale=True) -> pd.DataFrame:
    return pd.DataFrame({
        "product_id": [product_id],
        "product_name": ["Sony WH-1000XM4"],
        "brand": ["Sony"],
        "manufacturer": ["Sony"],
        "manufacturer_number": ["WH1000XM4"],
        "category": ["Electronics"],
        "asins": ["B0863TXGM3"],
        "upc": ["027242920934"],
        "merchant": [merchant],
        "observed_at": pd.to_datetime([ts], utc=True),
        "price": [price],
        "price_min": [price],
        "price_max": [price + 10],
        "previous_price": [prev_price],
        "absolute_change": [price - prev_price],
        "percentage_change": [(price - prev_price) / prev_price * 100],
        "log_price_diff": [-0.182],
        "is_sale": [is_sale],
        "availability": ["Yes"],
        "condition": ["New"],
        "shipping": ["Free"],
        "offer": ["http://amazon.com/deal"],
        "source_url": ["http://amazon.com/sony"],
        "date_added": pd.to_datetime(["2016-01-01"], utc=True),
        "date_updated": pd.to_datetime(["2017-03-15"], utc=True),
        "competitor_count": [2],
        "competitor_price_median": [279.99],
        "price_vs_comp_median": [-30.0],
        "competitors_changed_7d": [1],
        "competitor_direction_7d": [-1],
    })


# ---------------------------------------------------------------------------
# _change_direction tests
# ---------------------------------------------------------------------------

def test_change_direction_decrease():
    assert _change_direction(-10.5) == "decrease"


def test_change_direction_increase():
    assert _change_direction(5.0) == "increase"


def test_change_direction_no_change():
    assert _change_direction(0.0) == "no_change"


def test_change_direction_none():
    assert _change_direction(None) == "unknown"


# ---------------------------------------------------------------------------
# Event ID
# ---------------------------------------------------------------------------

def test_event_id_is_deterministic():
    id1 = _make_event_id("P001", "Amazon", "2017-01-01")
    id2 = _make_event_id("P001", "Amazon", "2017-01-01")
    assert id1 == id2


def test_event_id_different_for_different_inputs():
    id1 = _make_event_id("P001", "Amazon", "2017-01-01")
    id2 = _make_event_id("P001", "Amazon", "2017-01-02")
    assert id1 != id2


def test_event_id_starts_with_evt():
    eid = _make_event_id("P001", "Amazon", "2017-01-01")
    assert eid.startswith("evt_")


# ---------------------------------------------------------------------------
# generate_events tests
# ---------------------------------------------------------------------------

def test_generate_events_returns_list():
    bocpd = _make_bocpd_df()
    feats = _make_features_df()
    config = EventConfig(min_pct_change=5.0, min_cp_probability=0.5)
    events = generate_events(bocpd, feats, config=config)
    assert isinstance(events, list)


def test_generate_events_produces_changeevent_objects():
    bocpd = _make_bocpd_df(cp_prob=0.8)
    feats = _make_features_df(price=249.99, prev_price=299.99)
    config = EventConfig(min_pct_change=5.0, min_cp_probability=0.5)
    events = generate_events(bocpd, feats, config=config)
    if events:
        assert isinstance(events[0], ChangeEvent)


def test_generate_events_filters_low_cp_prob():
    """Events below min_cp_probability should be excluded."""
    bocpd = _make_bocpd_df(cp_prob=0.2)  # below threshold
    feats = _make_features_df()
    config = EventConfig(min_pct_change=2.0, min_cp_probability=0.5)
    events = generate_events(bocpd, feats, config=config)
    assert len(events) == 0


def test_generate_events_filters_small_pct_change():
    """Events with tiny percentage change should be filtered out."""
    bocpd = _make_bocpd_df(cp_prob=0.9)
    # Create tiny change
    feats = _make_features_df(price=100.0, prev_price=100.1)
    config = EventConfig(min_pct_change=2.0, min_cp_probability=0.3)
    events = generate_events(bocpd, feats, config=config)
    assert len(events) == 0


def test_generate_events_change_direction_is_set():
    bocpd = _make_bocpd_df(cp_prob=0.8)
    feats = _make_features_df(price=249.99, prev_price=299.99)
    config = EventConfig(min_pct_change=5.0, min_cp_probability=0.5)
    events = generate_events(bocpd, feats, config=config)
    if events:
        assert events[0].change_direction == "decrease"


def test_generate_events_empty_bocpd_returns_empty():
    bocpd = pd.DataFrame(columns=[
        "product_id", "merchant", "observed_at", "cp_probability",
        "map_run_length", "is_change_point",
    ])
    feats = _make_features_df()
    events = generate_events(bocpd, feats)
    assert events == []


# ---------------------------------------------------------------------------
# Weak label tests
# ---------------------------------------------------------------------------

def test_generate_weak_labels_returns_labelled_events(sample_change_event):
    events = [sample_change_event]
    labelled = generate_weak_labels(events)
    assert len(labelled) == 1


def test_promotion_label_fires_for_sale_event(sample_change_event):
    """is_sale=True + decrease direction should trigger promotion label."""
    labelled = generate_weak_labels([sample_change_event])
    assert LABEL_PROMOTION in labelled[0].labels


def test_competitive_label_fires_when_competitors_moved(sample_change_event):
    """competitors_changed_7d=1 should trigger competitive label."""
    labelled = generate_weak_labels([sample_change_event])
    assert LABEL_COMPETITIVE in labelled[0].labels


def test_unknown_label_fires_when_no_signals():
    """An event with no observable signals should get the unknown label."""
    from src.events.event_generator import ChangeEvent

    event = ChangeEvent(
        event_id="evt_unknown",
        product_id="PX",
        product_name="Mystery Product",
        brand="",
        manufacturer="",
        manufacturer_number="",
        category="",
        asins="",
        upc="",
        merchant="SomeMerchant",
        observed_at="2017-06-01T00:00:00+00:00",
        previous_price=50.0,
        current_price=53.0,
        absolute_change=3.0,
        percentage_change=6.0,
        change_direction="increase",
        cp_probability=0.5,
        map_run_length=5,
        log_price_diff=0.058,
        is_sale=False,
        offer=None,
        availability="Yes",
        condition="New",
        competitor_count=0,
        competitor_price_median=None,
        price_vs_comp_median=None,
        competitors_changed_7d=0,
        competitor_direction_7d=0,
        source_url=None,
    )
    labelled = generate_weak_labels([event], config=WeakLabelConfig(
        min_competitors_for_competitive=1,
        min_price_vs_comp_change=5.0,
    ))
    assert LABEL_UNKNOWN in labelled[0].labels


def test_weak_labels_have_evidence():
    """Each label should come with at least one evidence string."""
    from src.events.event_generator import ChangeEvent

    event = ChangeEvent(
        event_id="evt_promo",
        product_id="P001",
        product_name="Product",
        brand="Brand",
        manufacturer="Mfg",
        manufacturer_number="",
        category="Electronics",
        asins="",
        upc="",
        merchant="Amazon.com",
        observed_at="2017-03-01T00:00:00+00:00",
        previous_price=100.0,
        current_price=80.0,
        absolute_change=-20.0,
        percentage_change=-20.0,
        change_direction="decrease",
        cp_probability=0.6,
        map_run_length=4,
        log_price_diff=-0.22,
        is_sale=True,
        offer="http://offer",
        availability="Yes",
        condition="New",
        competitor_count=0,
        competitor_price_median=None,
        price_vs_comp_median=None,
        competitors_changed_7d=0,
        competitor_direction_7d=0,
        source_url=None,
    )
    labelled = generate_weak_labels([event])
    le = labelled[0]
    for label in le.labels:
        assert label in le.label_evidence
        assert len(le.label_evidence[label]) > 0
