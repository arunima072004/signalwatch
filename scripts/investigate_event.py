"""
scripts/investigate_event.py
Historical event investigation entry point.

Usage:
  python scripts/investigate_event.py --event-id evt_835c783f6785e8bf
  python scripts/investigate_event.py --event-id evt_835c783f6785e8bf --provider mock
  python scripts/investigate_event.py --event-id evt_835c783f6785e8bf --provider tavily
  python scripts/investigate_event.py --event-id evt_835c783f6785e8bf --provider cached
  python scripts/investigate_event.py --list
"""
from __future__ import annotations
import argparse, json, logging, os, sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Load .env if present (no error if file missing)
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass  # python-dotenv not installed — environment variables must be set manually

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("investigate_event")

EVENTS_FILE = ROOT / "data" / "events" / "change_events.json"
OUTPUT_DIR  = ROOT / "data" / "assessments"


def load_events() -> list[dict]:
    with open(EVENTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def get_event(event_id: str) -> dict | None:
    for e in load_events():
        if e["event_id"] == event_id:
            return e
    return None


def build_change_event(raw: dict):
    from src.events.event_generator import ChangeEvent
    return ChangeEvent(**raw)


def build_provider(name: str):
    """
    Construct the appropriate SearchProvider.

    mock   : MockSearchProvider  — canned results, no API key
    tavily : TavilySearchProvider — live Tavily API (requires TAVILY_API_KEY)
    cached : CachedSearchProvider wrapping TavilySearchProvider
             Serves from disk cache; calls Tavily on a miss if TAVILY_API_KEY is set.
             Run with --provider tavily first to populate the cache.
    """
    if name == "mock":
        from src.search.mock_provider import MockSearchProvider
        return MockSearchProvider()

    if name == "tavily":
        from src.search.tavily_provider import TavilySearchProvider
        depth = os.getenv("TAVILY_SEARCH_DEPTH", "basic")
        return TavilySearchProvider(search_depth=depth)

    if name == "cached":
        from src.search.cached_provider import CachedSearchProvider
        api_key = os.getenv("TAVILY_API_KEY")
        if api_key:
            from src.search.tavily_provider import TavilySearchProvider
            depth = os.getenv("TAVILY_SEARCH_DEPTH", "basic")
            underlying = TavilySearchProvider(api_key=api_key, search_depth=depth)
        else:
            underlying = None
            logger.warning(
                "No TAVILY_API_KEY found — cached provider will return [] on cache misses. "
                "Set TAVILY_API_KEY or run with --provider tavily first to populate the cache."
            )
        return CachedSearchProvider(underlying=underlying)

    raise ValueError(f"Unknown provider: {name!r}. Supported: mock, tavily, cached")


def main() -> None:
    parser = argparse.ArgumentParser(description="Investigate a SignalWatch change event")
    parser.add_argument("--event-id", help="event_id from change_events.json")
    parser.add_argument(
        "--provider",
        default=os.getenv("SEARCH_PROVIDER", "mock"),
        choices=["mock", "tavily", "cached"],
        help="Search provider (default: SEARCH_PROVIDER env var, or mock)",
    )
    parser.add_argument("--list", action="store_true", help="List available event IDs")
    args = parser.parse_args()

    if args.list:
        events = load_events()
        print(f"Available events ({len(events)}):")
        for e in events:
            eid = e.get("event_id", "?")
            pname = e.get("product_name", "?")[:60]
            merchant = e.get("merchant", "?")
            direction = e.get("change_direction", "?")
            pct = e.get("percentage_change", 0) or 0
            print(f"  {eid}  {pname:<62}  {merchant:<20}  {direction} {abs(pct):.1f}%")
        return

    if not args.event_id:
        parser.error("--event-id is required unless --list is used")

    raw = get_event(args.event_id)
    if raw is None:
        logger.error("Event %r not found in %s", args.event_id, EVENTS_FILE)
        sys.exit(1)

    logger.info("Loaded event: %s", args.event_id)
    event = build_change_event(raw)
    provider = build_provider(args.provider)

    from src.investigation.orchestrator import InvestigationOrchestrator
    orchestrator = InvestigationOrchestrator(
        search_provider=provider,
        output_dir=OUTPUT_DIR,
    )

    logger.info("Running investigation with provider=%s ...", args.provider)
    assessment = orchestrator.investigate(event)
    out_path = orchestrator.save(assessment)

    print()
    print("=" * 60)
    print("INVESTIGATION COMPLETE")
    print("=" * 60)
    print(f"Event:      {event.event_id}")
    print(f"Product:    {event.product_name}")
    print(f"Merchant:   {event.merchant}")
    print(f"Change:     {event.change_direction} {abs(event.percentage_change or 0):.1f}%")
    print(f"Date:       {event.observed_at[:10]}")
    print()
    print(f"Provider:   {provider.provider_name()}")
    print(f"Queries:    {assessment.queries_generated}")
    print(f"Results:    {assessment.results_retrieved}")
    print(f"Evidence:   {len(assessment.evidence)} items")
    print()
    for ha in assessment.hypothesis_assessments:
        print(f"  {ha.hypothesis_type:<28} -> {ha.support_level.value}")
        print(f"    {ha.explanation}")
    print()
    if assessment.uncertainty_factors:
        print("Uncertainty factors:")
        for u in assessment.uncertainty_factors:
            print(f"  - {u}")
    print()
    print(f"Assessment saved to: {out_path}")

    # Print cache stats if using cached provider
    if args.provider == "cached":
        from src.search.cached_provider import CachedSearchProvider
        if isinstance(provider, CachedSearchProvider):
            stats = provider.cache_stats()
            print()
            print(f"Cache: {stats['hits']} hits / {stats['misses']} misses "
                  f"({stats['hit_rate']*100:.0f}% hit rate) | "
                  f"{stats['cache_files']} files in {stats['cache_dir']}")


if __name__ == "__main__":
    main()
