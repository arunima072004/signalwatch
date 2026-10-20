"""
src/pipeline/runner.py
=======================
PipelineRunner: executes one SignalWatch cycle.

One cycle:
  1. Load active watchlist from repository.
  2. Fetch new PriceObservations from the chosen PriceSource.
  3. Upsert observations (idempotent); for each NEW observation in
     chronological order, run the incremental BOCPD detector.
  4. Created ChangeEvents are stored with status NEW.
  5. Investigate NEW events (up to budget limit) with the existing
     InvestigationOrchestrator. Save assessments; update event status.
  6. Write a Markdown report for each newly investigated event.
  7. Record the pipeline run in the repository.

Budget guards (all configurable, these are defaults):
  MAX_INVESTIGATIONS_PER_CYCLE = 3
  MAX_SEARCH_QUERIES_PER_DAY   = 150
  MAX_CHANNEL3_CALLS_PER_CYCLE = 50
  MAX_CHANNEL3_CALLS_PER_DAY   = 200

Investigation always uses CachedSearchProvider wrapping the configured
search provider.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.adapters.base import PriceSource
from src.adapters.price_observation import PriceObservation
from src.bocpd.config import BOCPDConfig
from src.bocpd.incremental import IncrementalDetector, IncrementalStepResult
from src.events.event_generator import ChangeEvent, EventConfig
from src.investigation.orchestrator import InvestigationOrchestrator
from src.search.provider_interface import SearchProvider
from src.storage.repository import SignalWatchRepository

logger = logging.getLogger(__name__)

_DEFAULT_MAX_INVESTIGATIONS = int(os.getenv("MAX_INVESTIGATIONS_PER_CYCLE", "3"))
_DEFAULT_MAX_QUERIES_PER_DAY = int(os.getenv("MAX_SEARCH_QUERIES_PER_DAY", "150"))
_DEFAULT_MAX_CHANNEL3_CYCLE = int(os.getenv("MAX_CHANNEL3_CALLS_PER_CYCLE", "50"))
_DEFAULT_MAX_CHANNEL3_DAY = int(os.getenv("MAX_CHANNEL3_CALLS_PER_DAY", "200"))


def _make_event_id(product_id: str, merchant: str, observed_at: str) -> str:
    raw = f"{product_id}|{merchant}|{observed_at}"
    return "evt_" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def _obs_to_change_event(
    obs: PriceObservation,
    previous_price: float,
    cp_probability: float,
    map_run_length: int,
    log_price_diff: float,
    competitive_context: Dict[str, Any],
) -> ChangeEvent:
    """Build a ChangeEvent from an observation that triggered BOCPD."""
    price = obs.price
    prev = previous_price
    abs_change = price - prev
    pct_change = (abs_change / prev * 100.0) if prev else None

    if pct_change is not None and pct_change > 0.001:
        direction = "increase"
    elif pct_change is not None and pct_change < -0.001:
        direction = "decrease"
    else:
        direction = "no_change"

    return ChangeEvent(
        event_id=_make_event_id(obs.product_id, obs.merchant, obs.observed_at),
        product_id=obs.product_id,
        product_name=obs.product_name or obs.product_id,
        brand=obs.brand or "",
        manufacturer=obs.manufacturer or "",
        manufacturer_number=obs.manufacturer_number or "",
        category=obs.category or "",
        asins=obs.asin or "",
        upc=obs.upc or "",
        merchant=obs.merchant,
        observed_at=obs.observed_at,
        previous_price=prev,
        current_price=price,
        absolute_change=abs_change,
        percentage_change=pct_change,
        change_direction=direction,
        cp_probability=cp_probability,
        map_run_length=map_run_length,
        log_price_diff=log_price_diff,
        is_sale=obs.is_sale,
        offer=obs.product_url,
        availability=obs.availability,
        condition=obs.condition,
        competitor_count=competitive_context.get("competitor_count", 0),
        competitor_price_median=competitive_context.get("competitor_price_median"),
        price_vs_comp_median=competitive_context.get("price_vs_comp_median"),
        competitors_changed_7d=competitive_context.get("competitors_changed_7d", 0),
        competitor_direction_7d=competitive_context.get("competitor_direction_7d", 0),
        source_url=obs.product_url,
    )


def _compute_competitive_context(
    repo: SignalWatchRepository,
    product_id: str,
    merchant: str,
    observed_at: str,
) -> Dict[str, Any]:
    """
    Compute causal competitive context from stored observations.
    Only uses observations BEFORE the event (strictly causal).
    """
    # Get all observations for this product across all merchants up to event time
    from collections import defaultdict
    all_obs = repo.get_observations(product_id, merchant, until=observed_at)

    # Count other merchants and their recent price changes
    # (simple version: count distinct domains with observations in last 7d)
    from datetime import timedelta
    try:
        ev_dt = datetime.fromisoformat(observed_at)
        window_start = (ev_dt - timedelta(days=7)).isoformat()
    except Exception:
        return {"competitor_count": 0, "competitors_changed_7d": 0, "competitor_direction_7d": 0}

    recent_obs = [o for o in all_obs if o.get("observed_at", "") >= window_start]
    other_merchants = [o for o in recent_obs if o.get("merchant") != merchant]

    # Count merchants that appeared in the 7d window
    merchant_prices = defaultdict(list)
    for o in other_merchants:
        m = o.get("merchant")
        p = o.get("price")
        if m and p is not None:
            merchant_prices[m].append((o.get("observed_at"), float(p)))

    competitor_count = len(merchant_prices)
    all_prices = [p for prices in merchant_prices.values() for _, p in prices]
    comp_median = sorted(all_prices)[len(all_prices)//2] if all_prices else None
    price_vs_comp = (obs.price - comp_median) if comp_median else None

    # For simplicity, competitor_direction is the count of merchants with any change
    return {
        "competitor_count": competitor_count,
        "competitor_price_median": comp_median,
        "price_vs_comp_median": price_vs_comp,
        "competitors_changed_7d": min(competitor_count, competitor_count),
        "competitor_direction_7d": 0,
    }


class PipelineRunner:
    """
    Executes one SignalWatch cycle.

    Parameters
    ----------
    source : PriceSource
        Where to fetch price observations from.
    search_provider : SearchProvider
        Search provider for investigation (typically CachedSearchProvider).
    repo : SignalWatchRepository
        Storage backend.
    assessments_dir : Path
        Where to write EventAssessment JSON files and Markdown reports.
    bocpd_config : BOCPDConfig, optional
        BOCPD configuration (defaults unchanged from Phase 1).
    event_config : EventConfig, optional
        Event filtering thresholds (defaults unchanged from Phase 1).
    max_investigations : int
        Maximum events to investigate per cycle.
    """

    def __init__(
        self,
        source: PriceSource,
        search_provider: SearchProvider,
        repo: SignalWatchRepository,
        assessments_dir: Optional[Path] = None,
        bocpd_config: Optional[BOCPDConfig] = None,
        event_config: Optional[EventConfig] = None,
        max_investigations: int = _DEFAULT_MAX_INVESTIGATIONS,
        max_queries_per_day: int = _DEFAULT_MAX_QUERIES_PER_DAY,
    ) -> None:
        self.source = source
        self.search_provider = search_provider
        self.repo = repo
        self.assessments_dir = assessments_dir or Path("data/assessments")
        self.bocpd_config = bocpd_config or BOCPDConfig()
        self.event_config = event_config or EventConfig()
        self.max_investigations = max_investigations
        self.max_queries_per_day = max_queries_per_day
        self._incremental = IncrementalDetector(self.bocpd_config)
        self.assessments_dir.mkdir(parents=True, exist_ok=True)

    def _queries_used_today(self, today: str) -> int:
        """Return total search queries used today across all pipeline runs."""
        try:
            conn = self.repo._connect()
            row = conn.execute(
                "SELECT COALESCE(SUM(search_queries_used), 0) FROM pipeline_runs "
                "WHERE started_at LIKE ?",
                (today + "%",),
            ).fetchone()
            return int(row[0]) if row else 0
        except Exception:
            return 0

    def run_cycle(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Execute one complete pipeline cycle.

        Parameters
        ----------
        dry_run : bool
            If True, count planned operations but make no API calls,
            no DB writes, and no investigations.

        Returns
        -------
        dict with cycle summary statistics.
        """
        run_id = None if dry_run else self.repo.start_pipeline_run()
        stats = {
            "observations_ingested": 0,
            "new_observations": 0,
            "events_created": 0,
            "events_investigated": 0,
            "events_failed": 0,
            "events_deferred": 0,
            "channel3_calls": 0,
            "search_queries": 0,
            "errors": [],
        }

        # ------------------------------------------------------------------
        # Step 1: Load watchlist
        # ------------------------------------------------------------------
        watchlist = self.repo.get_watchlist(active_only=True)
        product_ids = [w["product_id"] for w in watchlist]

        if not product_ids:
            logger.warning("PipelineRunner: watchlist is empty — nothing to do.")
            if run_id:
                self.repo.finish_pipeline_run(run_id, **{
                    k: stats[k] for k in [
                        "observations_ingested","events_created","events_investigated",
                        "search_queries","channel3_calls","errors"
                    ]
                })
            return stats

        if dry_run:
            logger.info("DRY RUN: would fetch prices for %d products", len(product_ids))
            # Estimate query count from hypothesis generator
            stats["planned_products"] = len(product_ids)
            from src.investigation.hypothesis_generator import HypothesisGenerator
            gen = HypothesisGenerator()
            # Use a representative ChangeEvent to estimate queries
            from src.events.event_generator import ChangeEvent as CE
            import math as _m
            dummy = CE(
                event_id="dry_run", product_id="X", product_name="X",
                brand="", manufacturer="", manufacturer_number="",
                category="", asins="", upc="", merchant="X",
                observed_at=datetime.now(timezone.utc).isoformat(),
                previous_price=100.0, current_price=75.0,
                absolute_change=-25.0, percentage_change=-25.0,
                change_direction="decrease", cp_probability=0.5,
                map_run_length=3, log_price_diff=-0.29, is_sale=False,
                offer=None, availability=None, condition=None,
                competitor_count=0, competitor_price_median=None,
                price_vs_comp_median=None, competitors_changed_7d=0,
                competitor_direction_7d=0, source_url=None,
            )
            hyps = gen.generate(dummy)
            from src.investigation.investigation_agent import HYPOTHESIS_TO_STRATEGY
            total_q = sum(
                len(HYPOTHESIS_TO_STRATEGY[h.hypothesis_type].generate_queries(dummy, h))
                for h in hyps if HYPOTHESIS_TO_STRATEGY.get(h.hypothesis_type)
            )
            stats["planned_queries_per_event"] = total_q
            stats["planned_channel3_calls"] = len(product_ids)
            logger.info(
                "DRY RUN: %d products => ~%d Channel3 calls; "
                "each event ~%d search queries (up to %d events/cycle)",
                len(product_ids), len(product_ids),
                total_q, self.max_investigations,
            )
            return stats

        # ------------------------------------------------------------------
        # Step 2: Fetch observations
        # ------------------------------------------------------------------
        try:
            observations = self.source.fetch_observations(product_ids)
            observations.sort(key=lambda o: o.observed_at)
            stats["observations_ingested"] = len(observations)
            if hasattr(self.source, "_cycle_calls"):
                stats["channel3_calls"] = self.source._cycle_calls
        except Exception as exc:
            msg = f"fetch_observations failed: {exc}"
            logger.error("PipelineRunner: %s", msg)
            stats["errors"].append(msg)
            observations = []

        # ------------------------------------------------------------------
        # Step 3: Upsert + incremental BOCPD
        # ------------------------------------------------------------------
        last_event_per_pair: Dict[tuple, str] = {}

        for obs in observations:
            try:
                is_new = self.repo.upsert_observation(obs)
                if not is_new:
                    continue
                stats["new_observations"] += 1

                stored = self.repo.load_bocpd_state(obs.product_id, obs.merchant)
                bocpd_row = stored
                last_price = bocpd_row["last_price"] if bocpd_row else None
                last_ts = bocpd_row["last_observed_at"] if bocpd_row else None
                obs_count = bocpd_row["observation_count"] if bocpd_row else 0
                state = bocpd_row["state"] if bocpd_row else None

                result = self._incremental.process(
                    new_price=obs.price,
                    observed_at=obs.observed_at,
                    stored_state=state,
                    last_price=last_price,
                    last_observed_at=last_ts,
                    observation_count=obs_count,
                )

                if result is None:
                    continue

                self.repo.save_bocpd_state(
                    product_id=obs.product_id,
                    merchant=obs.merchant,
                    state=result.new_state,
                    last_price=result.last_price,
                    last_observed_at=result.last_observed_at,
                    observation_count=result.observation_count,
                )

                step = result.step
                import numpy as np
                if (step.cp_probability is None or
                        np.isnan(step.cp_probability) or
                        not step.is_change_point):
                    continue

                # Change point detected — apply same filters as generate_events
                if last_price is None:
                    continue
                pct = (obs.price - last_price) / last_price * 100.0
                if abs(pct) < self.event_config.min_pct_change:
                    continue
                if step.cp_probability < self.event_config.min_cp_probability:
                    continue

                # 24-hour dedup per pair
                pair_key = (obs.product_id, obs.merchant)
                if pair_key in last_event_per_pair:
                    from datetime import timedelta
                    prev_ts = last_event_per_pair[pair_key]
                    try:
                        diff = abs((
                            datetime.fromisoformat(obs.observed_at) -
                            datetime.fromisoformat(prev_ts)
                        ).total_seconds())
                        if diff < self.event_config.dedup_window_hours * 3600:
                            continue
                    except Exception:
                        pass
                last_event_per_pair[pair_key] = obs.observed_at

                log_diff = math.log(obs.price / last_price)
                ctx = _compute_competitive_context(
                    self.repo, obs.product_id, obs.merchant, obs.observed_at
                )
                event = _obs_to_change_event(
                    obs, last_price, step.cp_probability,
                    step.map_run_length, log_diff, ctx
                )
                self.repo.save_change_event(event.to_dict())
                stats["events_created"] += 1
                logger.info(
                    "PipelineRunner: change event %s (%s/%s %.1f%%)",
                    event.event_id, obs.product_id, obs.merchant, pct
                )

            except Exception as exc:
                msg = f"Error processing obs {obs.product_id}/{obs.merchant}: {exc}"
                logger.error("PipelineRunner: %s", msg)
                stats["errors"].append(msg)

        # ------------------------------------------------------------------
        # Step 4: Investigate NEW events (within budget)
        # ------------------------------------------------------------------
        from src.search.cached_provider import CachedSearchProvider
        provider = CachedSearchProvider(underlying=self.search_provider)
        orchestrator = InvestigationOrchestrator(
            search_provider=provider,
            output_dir=self.assessments_dir,
        )

        new_events = self.repo.get_events_by_status("NEW")
        investigated = 0

        # Count queries already used today across all pipeline runs
        today = datetime.now(timezone.utc).date().isoformat()
        queries_today = self._queries_used_today(today)

        for ev_row in new_events:
            if investigated >= self.max_investigations:
                stats["events_deferred"] += 1
                continue
            if queries_today + stats["search_queries"] >= self.max_queries_per_day:
                logger.warning(
                    "PipelineRunner: daily search query budget (%d) reached "
                    "(used today: %d, this cycle: %d). Deferring remaining events.",
                    self.max_queries_per_day, queries_today, stats["search_queries"],
                )
                stats["events_deferred"] += 1
                continue

            event_dict = ev_row["event"]
            event_id = event_dict["event_id"]

            try:
                self.repo.update_event_status(event_id, "INVESTIGATING")
                event = ChangeEvent(**event_dict)
                assessment = orchestrator.investigate(event)

                # Save assessment to DB
                self.repo.save_assessment(event_id, assessment.to_dict())

                # Save assessment JSON file
                out_json = self.assessments_dir / f"{event_id}_assessment.json"
                import json as _json
                out_json.write_text(
                    _json.dumps(assessment.to_dict(), indent=2, default=str),
                    encoding="utf-8"
                )

                # Generate Markdown report
                try:
                    from scripts.generate_report import generate_report
                    report_md = generate_report(assessment.to_dict())
                    out_md = self.assessments_dir / f"{event_id}_report.md"
                    out_md.write_text(report_md, encoding="utf-8")
                except Exception as rep_exc:
                    logger.warning("Report generation failed for %s: %s", event_id, rep_exc)

                self.repo.update_event_status(event_id, "INVESTIGATED")
                investigated += 1
                stats["events_investigated"] += 1
                q_count, _ = orchestrator.investigation_agent.get_last_stats()
                stats["search_queries"] += q_count
                logger.info("PipelineRunner: investigated %s", event_id)

            except Exception as exc:
                msg = f"Investigation failed for {event_id}: {exc}"
                logger.error("PipelineRunner: %s", msg)
                self.repo.update_event_status(event_id, "FAILED", error=str(exc))
                stats["events_failed"] += 1
                stats["errors"].append(msg)

        # ------------------------------------------------------------------
        # Step 5: Record run
        # ------------------------------------------------------------------
        if run_id:
            self.repo.finish_pipeline_run(
                run_id=run_id,
                observations_ingested=stats["observations_ingested"],
                events_created=stats["events_created"],
                events_investigated=stats["events_investigated"],
                search_queries_used=stats["search_queries"],
                channel3_calls_used=stats["channel3_calls"],
                errors=stats["errors"],
            )

        logger.info(
            "PipelineRunner cycle complete: obs=%d new=%d events=%d investigated=%d "
            "deferred=%d failed=%d queries=%d",
            stats["observations_ingested"], stats["new_observations"],
            stats["events_created"], stats["events_investigated"],
            stats["events_deferred"], stats["events_failed"],
            stats["search_queries"],
        )
        return stats
