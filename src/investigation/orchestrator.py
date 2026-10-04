"""
src/investigation/orchestrator.py
Coordinates the full investigation pipeline for one ChangeEvent.
"""
from __future__ import annotations
import hashlib, json, logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from src.events.event_generator import ChangeEvent
from src.models.assessment import EventAssessment
from src.models.evidence import Evidence
from src.models.verification import SupportLevel
from src.investigation.hypothesis_generator import HypothesisGenerator
from src.investigation.investigation_agent import InvestigationAgent
from src.investigation.verification_agent import VerificationAgent
from src.search.provider_interface import SearchProvider

logger = logging.getLogger(__name__)


def _build_event_summary(event: ChangeEvent) -> Dict[str, Any]:
    """Extract a structured snapshot from a ChangeEvent for the assessment record."""
    return {
        "event_id": event.event_id,
        "product_name": event.product_name,
        "brand": event.brand,
        "merchant": event.merchant,
        "previous_price": event.previous_price,
        "current_price": event.current_price,
        "price_change_pct": event.percentage_change,
        "change_direction": event.change_direction,
        "observed_at": event.observed_at,
        "category": event.category,
    }


class InvestigationOrchestrator:
    """
    Runs the full Phase 2 pipeline:
      ChangeEvent -> Hypotheses -> InvestigationAgent -> Search -> Evidence -> Verify -> Assessment
    """

    def __init__(self,
                 search_provider: SearchProvider,
                 output_dir: Optional[Path] = None,
                 max_retries: int = 2) -> None:
        self.search_provider = search_provider
        self.output_dir = output_dir or Path("data/assessments")
        self.max_retries = max_retries
        self.hypothesis_gen = HypothesisGenerator()
        self.investigation_agent = InvestigationAgent(search_provider)
        self.verifier = VerificationAgent()

    def investigate(self, event: ChangeEvent) -> EventAssessment:
        """Run the full pipeline for one event. Never raises."""
        now = datetime.now(timezone.utc).isoformat()
        logger.info("Starting investigation for event %s", event.event_id)

        agent_failures: List[str] = []
        search_failures: List[str] = []
        all_evidence: List[Evidence] = []
        total_queries = 0
        total_search_results = 0

        # Step 1: Generate hypotheses
        try:
            hypotheses = self.hypothesis_gen.generate(event)
        except Exception as exc:
            logger.error("Hypothesis generation failed: %s", exc)
            hypotheses = []
            agent_failures.append(f"HypothesisGenerator: {exc}")

        # Step 2: Run all strategies via InvestigationAgent
        if hypotheses:
            try:
                evidence = self.investigation_agent.investigate_event(event, hypotheses)
                all_evidence.extend(evidence)
                q_count, r_count = self.investigation_agent.get_last_stats()
                total_queries += q_count
                total_search_results += r_count
            except Exception as exc:
                logger.warning("InvestigationAgent failed: %s", exc)
                agent_failures.append(f"InvestigationAgent: {exc}")

        # Step 3: Verify evidence
        ev_verifications, ha_list = [], []
        if all_evidence and hypotheses:
            try:
                ev_verifications, ha_list = self.verifier.verify(all_evidence, hypotheses, event)
            except Exception as exc:
                logger.error("Verification failed: %s", exc)
                agent_failures.append(f"VerificationAgent: {exc}")

        # Step 4: Build uncertainty factors
        uncertainty: List[str] = []
        if not all_evidence:
            uncertainty.append("No evidence was retrieved.")
        ind_count = sum(1 for ha in ha_list if ha.independent_source_count > 0)
        if ind_count == 0 and all_evidence:
            uncertainty.append("Source independence could not be confirmed for any evidence.")
        if agent_failures:
            uncertainty.append(f"{len(agent_failures)} agent/search failure(s) occurred.")

        # Step 5: Build summaries
        summary = self._build_summary(event, ha_list, all_evidence)
        event_summary = _build_event_summary(event)

        # Step 6: Assemble assessment
        assessment_id = "asmnt_" + hashlib.sha256((
            event.event_id + now).encode()).hexdigest()[:12]

        total_ind = sum(ha.independent_source_count for ha in ha_list)
        total_dup = sum(ha.duplicated_source_count for ha in ha_list)

        assessment = EventAssessment(
            assessment_id=assessment_id,
            event_id=event.event_id,
            assessed_at=now,
            hypotheses=hypotheses,
            queries_generated=total_queries,
            results_retrieved=total_search_results,
            evidence=all_evidence,
            evidence_verifications=ev_verifications,
            hypothesis_assessments=ha_list,
            independent_source_count=total_ind,
            duplicated_source_count=total_dup,
            uncertainty_factors=uncertainty,
            summary=summary,
            event_summary=event_summary,
            agent_failures=agent_failures,
            search_failures=search_failures,
        )

        logger.info(
            "Investigation complete for %s: %d hypotheses, %d evidence items",
            event.event_id, len(hypotheses), len(all_evidence)
        )
        return assessment

    def save(self, assessment: EventAssessment) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{assessment.event_id}_assessment.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(assessment.to_dict(), f, indent=2, default=str)
        logger.info("Assessment saved to %s", path)
        return path

    def _build_summary(self, event: ChangeEvent, ha_list, evidence) -> str:
        direction = event.change_direction
        pct = abs(event.percentage_change or 0)
        lines = [
            f"Event {event.event_id}: {event.product_name} at {event.merchant}.",
            f"Observed {direction} of {pct:.1f}% on {event.observed_at[:10]}.",
        ]
        if ha_list:
            lines.append("Hypothesis assessments:")
            for ha in ha_list:
                lines.append(f"  {ha.hypothesis_type}: {ha.support_level.value}")
        else:
            lines.append("No hypotheses could be assessed.")
        if not evidence:
            lines.append("No evidence was retrieved.")
        else:
            lines.append(f"{len(evidence)} evidence item(s) collected.")
        return " ".join(lines)
