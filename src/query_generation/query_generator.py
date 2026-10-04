"""
src/query_generation/query_generator.py
=========================================
Deterministic, template-based search query generator.

THIS IS THE FINAL STAGE OF THE CURRENT IMPLEMENTATION.
No web search, no LLM API, no internet access.

Purpose
-------
For every detected ChangeEvent (with weak labels), generate a structured
set of targeted search queries that a future multi-agent web-search layer
can execute.  Queries are grouped by agent type so each specialised agent
can be dispatched with its own query set.

Query philosophy
----------------
Queries are designed to DISCOVER EVIDENCE, not confirm a hypothesis.
For a price decrease we generate queries that investigate:
  - promotions / discounts / sales
  - competitor movements
  - product events (new version, discontinuation)
  - retailer events (clearance, Black Friday, etc.)
  - news (recalls, reviews, press coverage)

For a price increase:
  - supply constraints / shortages
  - cost increases / tariffs
  - competitor movements
  - product demand events
  - retailer events
  - news

Query generation logic
----------------------
1. Extract: product_name, brand, merchant, category, date_str,
   change_direction, pct_change, weak_labels from the LabelledEvent.
2. Build a query context object.
3. Apply template groups for each agent type.
4. Substitute context values into templates.
5. Deduplicate and clean.
6. Return structured QueryGroup dict.

Template design
---------------
Templates are Python f-string-style with named placeholders.
The `_fill` helper substitutes values safely, skipping templates that
reference missing fields rather than producing malformed queries.

Interface contract
------------------
QueryGenerator.generate_queries(labelled_event) → dict
  {
    "event_id": str,
    "investigation_target": { ... },
    "queries": {
      "promotion_agent": [...],
      "competitor_agent": [...],
      "product_event_agent": [...],
      "news_agent": [...],
      "retailer_event_agent": [...],
      "supply_agent": [...]  (for price increases only)
    }
  }

This output is directly consumable by a future multi-agent system.

Future extension point
----------------------
Replace or augment this class with an LLM-based planner by:
  class LLMQueryGenerator(QueryGenerator):
      def generate_queries(self, labelled_event):
          # call LLM API here
          ...
The interface stays identical.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from ..weak_supervision.label_generator import LabelledEvent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Query context extraction
# ---------------------------------------------------------------------------

def _extract_context(le: LabelledEvent) -> dict[str, Any]:
    """
    Extract and normalise all fields needed for query generation from a
    LabelledEvent.  Returns a flat dict of context values.
    """
    e = le.event

    # Date string: year-month is more useful for search than full ISO
    ts = e.observed_at or ""
    date_str = ""
    year_str = ""
    month_str = ""
    if ts:
        try:
            import pandas as pd
            t = pd.to_datetime(ts, errors="coerce", utc=True)
            if pd.notna(t):
                date_str = t.strftime("%B %Y")       # e.g. "March 2017"
                year_str = str(t.year)
                month_str = t.strftime("%B")          # e.g. "March"
        except Exception:
            pass
    if not date_str:
        date_str = ts[:7] if len(ts) >= 7 else ts    # fallback: "2017-03"

    # Clean product name — remove excessively long spec strings
    product_name = (e.product_name or "").strip()
    if len(product_name) > 120:
        product_name = product_name[:120].rsplit(" ", 1)[0]

    brand = (e.brand or "").strip()
    merchant = (e.merchant or "").strip()
    # Normalise merchant name: remove .com/.co.uk suffixes for readability
    merchant_clean = re.sub(r"\.(com|co\.uk|net|org)$", "", merchant, flags=re.I).strip()

    category = (e.category or "").strip()
    # Use first category if comma-separated
    if "," in category:
        category = category.split(",")[0].strip()

    pct = e.percentage_change
    pct_str = f"{abs(pct):.1f}%" if pct is not None else ""
    direction = e.change_direction  # "increase" | "decrease" | "no_change" | "unknown"
    direction_word = (
        "price drop" if direction == "decrease"
        else "price increase" if direction == "increase"
        else "price change"
    )
    direction_verb = (
        "dropped" if direction == "decrease"
        else "increased" if direction == "increase"
        else "changed"
    )

    prev_price = f"${e.previous_price:.2f}" if e.previous_price else ""
    curr_price = f"${e.current_price:.2f}" if e.current_price else ""
    price_movement = (
        f"{prev_price} to {curr_price}" if prev_price and curr_price else curr_price
    )

    return {
        "product_name": product_name,
        "brand": brand,
        "merchant": merchant,
        "merchant_clean": merchant_clean,
        "category": category,
        "date_str": date_str,
        "year_str": year_str,
        "month_str": month_str,
        "direction": direction,
        "direction_word": direction_word,
        "direction_verb": direction_verb,
        "pct_str": pct_str,
        "price_movement": price_movement,
        "curr_price": curr_price,
        "prev_price": prev_price,
        "is_sale": e.is_sale,
        "weak_labels": le.labels,
        "competitor_count": e.competitor_count,
        "competitors_changed_7d": e.competitors_changed_7d,
    }


# ---------------------------------------------------------------------------
# Template groups
# ---------------------------------------------------------------------------

# Each template is a string with {key} placeholders.
# A template is skipped if any required placeholder value is empty.

_PROMOTION_TEMPLATES_DECREASE = [
    "{product_name} {merchant_clean} sale {date_str}",
    "{product_name} {merchant_clean} discount {month_str} {year_str}",
    "{product_name} {brand} promotion {date_str}",
    "{product_name} price drop {date_str}",
    "{brand} {category} sale {date_str}",
    "{merchant_clean} {category} discount {month_str} {year_str}",
    "{product_name} clearance {merchant_clean} {year_str}",
    "{product_name} deal {date_str}",
]

_PROMOTION_TEMPLATES_INCREASE = [
    "{product_name} {merchant_clean} price increase {date_str}",
    "{product_name} {brand} price hike {year_str}",
    "{brand} {category} price increase {date_str}",
    "{merchant_clean} {category} price change {date_str}",
]

_COMPETITOR_TEMPLATES = [
    "{product_name} competitor price comparison {date_str}",
    "{product_name} {brand} price {merchant_clean} vs competitors {year_str}",
    "{brand} {category} price war {date_str}",
    "{product_name} best price {month_str} {year_str}",
    "{brand} {category} pricing competition {year_str}",
    "{product_name} retailer price comparison {date_str}",
]

_PRODUCT_EVENT_TEMPLATES = [
    "{product_name} new version {year_str}",
    "{product_name} successor replacement {year_str}",
    "{brand} {product_name} discontinued {year_str}",
    "{product_name} launch release {date_str}",
    "{brand} new product announcement {date_str}",
    "{product_name} updated model {year_str}",
    "{product_name} end of life {year_str}",
]

_NEWS_TEMPLATES = [
    "{product_name} {brand} news {date_str}",
    "{product_name} review {year_str}",
    "{brand} {category} news {month_str} {year_str}",
    "{brand} pricing strategy {year_str}",
    "{product_name} {merchant_clean} news {date_str}",
]

_RETAILER_EVENT_TEMPLATES = [
    "{merchant_clean} sale event {date_str}",
    "{merchant_clean} {month_str} {year_str} deals",
    "{merchant_clean} Black Friday Cyber Monday {year_str}",
    "{merchant_clean} clearance event {year_str}",
    "{merchant_clean} price match {year_str}",
    "{merchant_clean} promotional event {date_str}",
]

_SUPPLY_TEMPLATES_INCREASE = [
    "{product_name} supply shortage {date_str}",
    "{brand} {category} supply chain {year_str}",
    "{product_name} stock availability {date_str}",
    "{brand} {category} production issue {year_str}",
    "{product_name} tariff import cost {year_str}",
    "{brand} component shortage {year_str}",
]


# ---------------------------------------------------------------------------
# Template filling
# ---------------------------------------------------------------------------

def _fill(template: str, ctx: dict[str, Any]) -> Optional[str]:
    """
    Fill a template string with context values.

    Returns None if any placeholder is empty/missing (avoids generating
    queries like "price drop  2017" when merchant is unknown).
    """
    try:
        filled = template.format(**ctx)
    except KeyError:
        return None

    # Check for empty placeholder values in the result
    parts = filled.split()
    if not parts:
        return None

    # Clean extra whitespace
    filled = " ".join(parts)
    return filled if len(filled) > 5 else None


def _apply_templates(
    templates: list[str],
    ctx: dict[str, Any],
    max_queries: int = 6,
) -> list[str]:
    """Apply a list of templates to context, return deduplicated results."""
    queries: list[str] = []
    seen: set[str] = set()
    for tpl in templates:
        q = _fill(tpl, ctx)
        if q and q.lower() not in seen:
            seen.add(q.lower())
            queries.append(q)
        if len(queries) >= max_queries:
            break
    return queries


# ---------------------------------------------------------------------------
# Query generator
# ---------------------------------------------------------------------------

class QueryGenerator:
    """
    Deterministic, template-based query generator.

    Interface is designed so it can be subclassed with an LLM-based
    implementation later without changing the caller.

    Usage:
        qg = QueryGenerator()
        result = qg.generate_queries(labelled_event)
    """

    def generate_queries(
        self,
        labelled_event: LabelledEvent,
        max_per_agent: int = 6,
    ) -> dict[str, Any]:
        """
        Generate structured investigation queries for one LabelledEvent.

        Parameters
        ----------
        labelled_event:
            A LabelledEvent (ChangeEvent + weak labels).
        max_per_agent:
            Maximum queries per agent group.

        Returns
        -------
        dict
            Structured query object ready for a multi-agent system.
        """
        ctx = _extract_context(labelled_event)
        e = labelled_event.event
        direction = ctx["direction"]
        labels = ctx["weak_labels"]

        # ------------------------------------------------------------------
        # Promotion agent queries
        # ------------------------------------------------------------------
        if direction == "decrease":
            promo_templates = _PROMOTION_TEMPLATES_DECREASE
        else:
            promo_templates = _PROMOTION_TEMPLATES_INCREASE

        # Add label-boosted templates
        if "promotion_related" in labels and direction == "decrease":
            promo_templates = promo_templates + [
                "{product_name} {merchant_clean} offer {date_str}",
                "{brand} {product_name} coupon {date_str}",
                "{product_name} flash sale {date_str}",
            ]
        promotion_queries = _apply_templates(promo_templates, ctx, max_per_agent)

        # ------------------------------------------------------------------
        # Competitor agent queries
        # ------------------------------------------------------------------
        competitor_queries = _apply_templates(
            _COMPETITOR_TEMPLATES, ctx, max_per_agent
        )
        # If we know competitors moved, add a targeted query
        if ctx["competitors_changed_7d"] > 0:
            extra = _fill(
                "{product_name} {brand} price match competitor {date_str}", ctx
            )
            if extra and extra not in competitor_queries:
                competitor_queries.insert(0, extra)
                competitor_queries = competitor_queries[:max_per_agent]

        # ------------------------------------------------------------------
        # Product event agent queries
        # ------------------------------------------------------------------
        product_event_queries = _apply_templates(
            _PRODUCT_EVENT_TEMPLATES, ctx, max_per_agent
        )

        # ------------------------------------------------------------------
        # News agent queries
        # ------------------------------------------------------------------
        news_queries = _apply_templates(_NEWS_TEMPLATES, ctx, max_per_agent)

        # ------------------------------------------------------------------
        # Retailer event agent queries
        # ------------------------------------------------------------------
        retailer_queries = _apply_templates(
            _RETAILER_EVENT_TEMPLATES, ctx, max_per_agent
        )

        # ------------------------------------------------------------------
        # Supply agent queries (price increases only)
        # ------------------------------------------------------------------
        supply_queries: list[str] = []
        if direction == "increase":
            supply_queries = _apply_templates(
                _SUPPLY_TEMPLATES_INCREASE, ctx, max_per_agent
            )

        # ------------------------------------------------------------------
        # Assemble investigation target
        # ------------------------------------------------------------------
        investigation_target = {
            "product_id": e.product_id,
            "product_name": ctx["product_name"],
            "brand": ctx["brand"],
            "merchant": ctx["merchant"],
            "category": ctx["category"],
            "observed_at": e.observed_at,
            "change_direction": direction,
            "percentage_change": e.percentage_change,
            "previous_price": e.previous_price,
            "current_price": e.current_price,
            "cp_probability": e.cp_probability,
            "weak_labels": labels,
            "competitor_count": e.competitor_count,
            "competitors_changed_7d": e.competitors_changed_7d,
        }

        # ------------------------------------------------------------------
        # Build query groups — only include agent groups with queries
        # ------------------------------------------------------------------
        query_groups: dict[str, list[str]] = {}
        if promotion_queries:
            query_groups["promotion_agent"] = promotion_queries
        if competitor_queries:
            query_groups["competitor_agent"] = competitor_queries
        if product_event_queries:
            query_groups["product_event_agent"] = product_event_queries
        if news_queries:
            query_groups["news_agent"] = news_queries
        if retailer_queries:
            query_groups["retailer_event_agent"] = retailer_queries
        if supply_queries:
            query_groups["supply_agent"] = supply_queries

        return {
            "event_id": e.event_id,
            "investigation_target": investigation_target,
            "queries": query_groups,
        }

    def generate_all_queries(
        self,
        labelled_events: list[LabelledEvent],
        max_per_agent: int = 6,
    ) -> list[dict[str, Any]]:
        """
        Generate queries for every LabelledEvent in the list.

        Returns a list of query dicts, one per event.
        """
        results: list[dict[str, Any]] = []
        for le in labelled_events:
            try:
                q = self.generate_queries(le, max_per_agent=max_per_agent)
                results.append(q)
            except Exception as exc:
                logger.warning(
                    "Query generation failed for event %s: %s",
                    le.event.event_id,
                    exc,
                )
        total_queries = sum(
            sum(len(v) for v in r["queries"].values()) for r in results
        )
        logger.info(
            "Query generation complete: %d events → %d query groups → "
            "%d total queries",
            len(results),
            sum(len(r["queries"]) for r in results),
            total_queries,
        )
        return results


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def save_queries(
    query_results: list[dict[str, Any]],
    output_path: str | Path,
) -> None:
    """Save the structured query list to a JSON file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(query_results, fh, indent=2, default=str)
    logger.info(
        "Investigation queries saved to: %s (%d events)",
        output_path,
        len(query_results),
    )


def load_queries(input_path: str | Path) -> list[dict[str, Any]]:
    """Load a previously saved query JSON file."""
    with open(input_path, "r", encoding="utf-8") as fh:
        return json.load(fh)
