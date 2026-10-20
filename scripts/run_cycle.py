"""
scripts/run_cycle.py
=====================
Run one or more SignalWatch pipeline cycles.

Usage examples:
  # One cycle, mock search, replay source
  python scripts/run_cycle.py --source replay --provider mock

  # 20 cycles (simulates weeks of data offline)
  python scripts/run_cycle.py --source replay --provider mock --cycles 20

  # Real Channel3 + cached search (continuous, 60-min intervals)
  python scripts/run_cycle.py --source channel3 --provider cached --loop --interval-minutes 60

  # Dry-run: count planned calls without touching any API
  python scripts/run_cycle.py --source channel3 --provider mock --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_cycle")

DB_PATH = ROOT / "data" / "signalwatch.db"
_REPLAY_WINDOW_DAYS = 14
ASSESSMENTS_DIR = ROOT / "data" / "assessments"
CSV_PATH = ROOT / "data" / "processed" / "cleaned_data.csv"


def build_source(name: str):
    if name == "replay":
        from src.adapters.csv_adapter import CsvAdapter
        from src.adapters.replay_source import ReplaySource
        if not CSV_PATH.exists():
            logger.error("cleaned_data.csv not found at %s", CSV_PATH)
            sys.exit(1)
        adapter = CsvAdapter(str(CSV_PATH))
        obs = adapter.all_observations_sorted()
        logger.info("ReplaySource: %d total observations loaded", len(obs))
        return ReplaySource(obs, window_days=_REPLAY_WINDOW_DAYS)

    if name == "channel3":
        from src.adapters.channel3_adapter import Channel3Source
        return Channel3Source()

    raise ValueError(f"Unknown source: {name!r}. Supported: replay, channel3")


def build_search_provider(name: str):
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
            underlying = TavilySearchProvider(api_key=api_key)
        else:
            underlying = None
        return CachedSearchProvider(underlying=underlying)

    raise ValueError(f"Unknown provider: {name!r}. Supported: mock, tavily, cached")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SignalWatch pipeline cycle(s)")
    parser.add_argument("--source", default="replay", choices=["replay", "channel3"],
                        help="Price data source")
    parser.add_argument("--provider", default=os.getenv("SEARCH_PROVIDER", "mock"),
                        choices=["mock", "tavily", "cached"],
                        help="Search provider for investigation")
    parser.add_argument("--cycles", type=int, default=1,
                        help="Number of cycles to run (default 1)")
    parser.add_argument("--loop", action="store_true",
                        help="Run continuously until interrupted")
    parser.add_argument("--interval-minutes", type=float, default=60.0,
                        help="Minutes between cycles in loop mode (default 60)")
    parser.add_argument("--window-days", type=float, default=14.0,
                        help="Days per replay window (default 14)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Count planned operations without executing")
    parser.add_argument("--db", default=str(DB_PATH),
                        help=f"SQLite database path (default: {DB_PATH})")
    args = parser.parse_args()

    from src.storage.sqlite_repository import SqliteRepository
    from src.pipeline.runner import PipelineRunner

    repo = SqliteRepository(args.db)
    global _REPLAY_WINDOW_DAYS
    _REPLAY_WINDOW_DAYS = args.window_days
    source = build_source(args.source)
    search_provider = build_search_provider(args.provider)

    runner = PipelineRunner(
        source=source,
        search_provider=search_provider,
        repo=repo,
        assessments_dir=ASSESSMENTS_DIR,
    )

    n_cycles = args.cycles
    cycle_num = 0

    def run_one():
        nonlocal cycle_num
        cycle_num += 1
        logger.info("=== Cycle %d starting (source=%s provider=%s dry_run=%s) ===",
                    cycle_num, args.source, args.provider, args.dry_run)

        # Advance ReplaySource for each cycle
        if args.source == "replay" and cycle_num > 1:
            source.advance()

        stats = runner.run_cycle(dry_run=args.dry_run)

        print()
        print(f"Cycle {cycle_num} complete:")
        for k, v in stats.items():
            print(f"  {k}: {v}")
        print()

    if args.loop:
        logger.info("Loop mode: interval=%s min. Press Ctrl+C to stop.", args.interval_minutes)
        try:
            while True:
                run_one()
                if not args.dry_run:
                    time.sleep(args.interval_minutes * 60)
        except KeyboardInterrupt:
            logger.info("Loop interrupted by user.")
    else:
        for _ in range(n_cycles):
            run_one()
            if args.source == "replay" and hasattr(source, "has_more") and not source.has_more():
                logger.info("ReplaySource exhausted after cycle %d", cycle_num)
                break

    repo.close()


if __name__ == "__main__":
    main()
