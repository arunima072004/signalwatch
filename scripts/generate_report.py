#!/usr/bin/env python
"""
scripts/generate_report.py
===========================
Generate a human-readable Markdown report from an EventAssessment JSON file.

Usage:
  # Single event
  python scripts/generate_report.py data/assessments/evt_835c783f6785e8bf_assessment.json

  # All assessments in a directory -> one report per file + index
  python scripts/generate_report.py --all data/assessments/

  # Write to a specific output path
  python scripts/generate_report.py <assessment.json> --out reports/evt_835c.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _pct(v: Optional[float]) -> str:
    if v is None:
        return "?"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.1f}%"


def _price(v: Optional[float]) -> str:
    if v is None:
        return "?"
    return f"USD {v:.2f}"


def _direction_arrow(direction: str) -> str:
    return {"decrease": "↓", "increase": "↑", "no_change": "→"}.get(direction, "?")


SUPPORT_EMOJI = {
    "SUPPORTS": "✅",
    "PARTIALLY_SUPPORTS": "🟡",
    "CONSISTENT_WITH": "🔵",
    "INSUFFICIENT_EVIDENCE": "⬜",
    "CONTRADICTS": "❌",
}

SOURCE_INDEPENDENCE_LABEL = {
    "INDEPENDENT": "independent",
    "DUPLICATED": "duplicated",
    "SYNDICATED": "syndicated/shared",
    "CONTRADICTING": "contradicting",
    "INDEPENDENCE_UNCERTAIN": "uncertain",
}


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------

def generate_report(data: Dict[str, Any]) -> str:
    """Generate a Markdown report string from a deserialized assessment dict."""
    lines: List[str] = []
    es = data.get("event_summary", {})
    ha_list = data.get("hypothesis_assessments", [])
    evidence_list = data.get("evidence", [])
    uncertainty = data.get("uncertainty_factors", [])
    ev_verifications = data.get("evidence_verifications", [])

    # Index evidence and verifications by ID for fast lookup
    ev_by_id: Dict[str, Dict] = {e["evidence_id"]: e for e in evidence_list}
    vr_by_evid: Dict[str, Dict] = {v["evidence_id"]: v for v in ev_verifications}

    # -----------------------------------------------------------------------
    # Header
    # -----------------------------------------------------------------------
    product = es.get("product_name", data.get("event_id", "Unknown"))
    merchant = es.get("merchant", "?")
    date = (es.get("observed_at", ""))[:10]
    direction = es.get("change_direction", "?")
    pct = es.get("price_change_pct")
    prev = es.get("previous_price")
    curr = es.get("current_price")
    arrow = _direction_arrow(direction)

    lines.append(f"# SignalWatch Investigation Report")
    lines.append(f"")
    lines.append(f"**Event:** {data['event_id']}  ")
    lines.append(f"**Assessed:** {data.get('assessed_at', '?')[:19].replace('T', ' ')} UTC  ")
    lines.append(f"**Provider:** {data.get('agent_failures', [''])[0][:40] if data.get('agent_failures') else 'see assessment'}")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Event Summary")
    lines.append(f"")
    lines.append(f"| Field | Value |")
    lines.append(f"|---|---|")
    lines.append(f"| Product | {product} |")
    lines.append(f"| Merchant | {merchant} |")
    lines.append(f"| Date | {date} |")
    lines.append(f"| Price change | {_price(prev)} {arrow} {_price(curr)} ({_pct(pct)}) |")
    lines.append(f"| Category | {es.get('category', '?')} |")
    lines.append(f"| Brand | {es.get('brand', '?')} |")
    lines.append(f"")

    # -----------------------------------------------------------------------
    # Query stats
    # -----------------------------------------------------------------------
    lines.append(f"**Queries generated:** {data.get('queries_generated', 0)}  ")
    lines.append(f"**Search results retrieved:** {data.get('results_retrieved', 0)}  ")
    lines.append(f"**Evidence items extracted:** {len(evidence_list)}  ")
    lines.append(f"**Independent sources:** {data.get('independent_source_count', 0)}  ")
    lines.append(f"**Duplicated/syndicated:** {data.get('duplicated_source_count', 0)}  ")
    lines.append(f"")

    # -----------------------------------------------------------------------
    # Hypothesis assessments
    # -----------------------------------------------------------------------
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Hypothesis Assessments")
    lines.append(f"")

    for ha in ha_list:
        h_type = ha["hypothesis_type"]
        support = ha["support_level"]
        emoji = SUPPORT_EMOJI.get(support, "?")
        explanation = ha.get("explanation", "")
        supporting = ha.get("supporting_evidence_ids", [])
        contradicting = ha.get("contradicting_evidence_ids", [])
        ind = ha.get("independent_source_count", 0)
        dup = ha.get("duplicated_source_count", 0)
        cs = ha.get("component_scores", {})

        lines.append(f"### {emoji} {h_type} — {support}")
        lines.append(f"")
        lines.append(f"{explanation}")
        lines.append(f"")

        if cs and any(v > 0 for v in cs.values()):
            lines.append(f"<details>")
            lines.append(f"<summary>Component scores</summary>")
            lines.append(f"")
            lines.append(f"| Dimension | Score |")
            lines.append(f"|---|---|")
            for k, v in cs.items():
                lines.append(f"| {k.replace('_', ' ').title()} | {v:.3f} |")
            lines.append(f"")
            lines.append(f"</details>")
            lines.append(f"")

        if supporting:
            lines.append(f"**Supporting evidence ({len(supporting)} item(s)):**")
            lines.append(f"")
            for ev_id in supporting[:5]:  # cap at 5 for readability
                ev = ev_by_id.get(ev_id, {})
                vr = vr_by_evid.get(ev_id, {})
                url = ev.get("source_url", "?")
                domain = ev.get("source_domain", "?")
                pub = ev.get("publication_date") or "?"
                claim = ev.get("claim", "")[:120]
                ind_cls = vr.get("independence_class", "?")
                ind_label = SOURCE_INDEPENDENCE_LABEL.get(ind_cls, ind_cls)
                lines.append(f"- **[{domain}]** ({pub}) [{ind_label}]  ")
                lines.append(f"  > {claim}")
                lines.append(f"  [Source]({url})")
                lines.append(f"")

        if contradicting:
            lines.append(f"**Contradicting evidence ({len(contradicting)} item(s)):**")
            lines.append(f"")
            for ev_id in contradicting[:3]:
                ev = ev_by_id.get(ev_id, {})
                url = ev.get("source_url", "?")
                domain = ev.get("source_domain", "?")
                claim = ev.get("claim", "")[:120]
                lines.append(f"- **[{domain}]** {claim}  ")
                lines.append(f"  [Source]({url})")
                lines.append(f"")

        if not supporting and not contradicting:
            lines.append(f"*No evidence items reached supporting or contradicting threshold.*")
            lines.append(f"")

    # -----------------------------------------------------------------------
    # Uncertainty
    # -----------------------------------------------------------------------
    if uncertainty:
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## Uncertainty Factors")
        lines.append(f"")
        for u in uncertainty:
            lines.append(f"- {u}")
        lines.append(f"")

    # -----------------------------------------------------------------------
    # Full source list
    # -----------------------------------------------------------------------
    if evidence_list:
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## All Evidence Sources")
        lines.append(f"")
        lines.append(f"| # | Hypothesis | Domain | Published | Independence | Relevance | Claim |")
        lines.append(f"|---|---|---|---|---|---|---|")
        for i, ev in enumerate(evidence_list, 1):
            ev_id = ev["evidence_id"]
            vr = vr_by_evid.get(ev_id, {})
            ind_cls = vr.get("independence_class", "?")
            ind_label = SOURCE_INDEPENDENCE_LABEL.get(ind_cls, ind_cls)
            claim = ev.get("claim", "")[:60].replace("|", "/")
            domain = ev.get("source_domain", "?")
            pub = ev.get("publication_date") or "?"
            hyp = ev.get("hypothesis_type", "?")
            rel = ev.get("relevance_score", 0)
            url = ev.get("source_url", "?")
            lines.append(f"| {i} | {hyp} | [{domain}]({url}) | {pub} | {ind_label} | {rel:.2f} | {claim} |")
        lines.append(f"")

    # -----------------------------------------------------------------------
    # Footer
    # -----------------------------------------------------------------------
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"*Report generated by SignalWatch. Assessment ID: {data['assessment_id']}.*")
    lines.append(f"")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def process_file(assessment_path: Path, output_path: Optional[Path] = None) -> Path:
    """Generate a Markdown report for one assessment JSON file."""
    data = json.loads(assessment_path.read_text(encoding="utf-8"))
    report = generate_report(data)

    if output_path is None:
        output_path = assessment_path.with_suffix(".md")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Markdown report from EventAssessment JSON")
    parser.add_argument(
        "assessment",
        nargs="?",
        help="Path to a single assessment JSON file",
    )
    parser.add_argument(
        "--all",
        metavar="DIR",
        help="Process all *_assessment.json files in DIR",
    )
    parser.add_argument(
        "--out",
        metavar="PATH",
        help="Output path for the Markdown report (single-file mode only)",
    )
    args = parser.parse_args()

    if args.all:
        directory = Path(args.all)
        files = sorted(directory.glob("*_assessment.json"))
        if not files:
            print(f"No assessment JSON files found in {directory}")
            sys.exit(1)
        print(f"Processing {len(files)} assessment(s) in {directory} ...")
        for f in files:
            out = process_file(f)
            print(f"  {f.name} -> {out.name}")
        print(f"Done. {len(files)} report(s) written to {directory}")

    elif args.assessment:
        assessment_path = Path(args.assessment)
        if not assessment_path.exists():
            print(f"File not found: {assessment_path}")
            sys.exit(1)
        out_path = Path(args.out) if args.out else None
        out = process_file(assessment_path, out_path)
        print(f"Report written to: {out}")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
