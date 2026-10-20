"""
scripts/db_stats.py
====================
Print accumulation statistics from the SignalWatch SQLite database.
This is the visible proof that live data is growing.

Usage:
  python scripts/db_stats.py
  python scripts/db_stats.py --db data/replay_demo.db
"""
from __future__ import annotations
import argparse, json, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="SignalWatch database statistics")
    parser.add_argument("--db", default=str(ROOT / "data" / "signalwatch.db"),
                        help="Path to the SQLite database")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    print("=" * 70)
    print("SignalWatch Database Statistics")
    print("=" * 70)
    print(f"Database:      {db_path.resolve()}")
    print(f"Size:          {db_path.stat().st_size / 1024:.1f} KB")
    print()

    # --- Total observations ---
    total = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    first_ts = conn.execute("SELECT MIN(observed_at) FROM observations").fetchone()[0]
    last_ts  = conn.execute("SELECT MAX(observed_at) FROM observations").fetchone()[0]
    print(f"Total observations: {total}")
    print(f"First observation:  {first_ts or 'none'}")
    print(f"Last  observation:  {last_ts  or 'none'}")
    print()

    # --- Per product ---
    print("Observations per product:")
    rows = conn.execute(
        "SELECT product_id, COUNT(*) as n, MIN(observed_at) as first, MAX(observed_at) as last "
        "FROM observations GROUP BY product_id ORDER BY n DESC"
    ).fetchall()
    # Lookup names from watchlist
    wl = {r["product_id"]: r["product_name"]
          for r in conn.execute("SELECT product_id, product_name FROM watchlist").fetchall()}
    for r in rows:
        name = wl.get(r["product_id"], r["product_id"])[:40]
        print(f"  {r['product_id']:<12} {r['n']:>4} obs   {name}")
    print()

    # --- Per merchant ---
    print("Observations per merchant (top 15):")
    rows = conn.execute(
        "SELECT merchant, COUNT(*) as n FROM observations GROUP BY merchant ORDER BY n DESC LIMIT 15"
    ).fetchall()
    for r in rows:
        print(f"  {str(r['merchant']):<30} {r['n']:>4} obs")
    print()

    # --- Pipeline runs ---
    runs = conn.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]
    print(f"Pipeline cycles run: {runs}")
    if runs > 0:
        print("Recent cycles:")
        recent = conn.execute(
            "SELECT run_id, started_at, observations_ingested, events_created, "
            "events_investigated, channel3_calls_used, search_queries_used "
            "FROM pipeline_runs ORDER BY started_at DESC LIMIT 10"
        ).fetchall()
        print(f"  {'started_at':<22} {'obs':>5} {'events':>7} {'invest':>7} {'ch3':>4} {'queries':>8}")
        print("  " + "-"*60)
        for r in recent:
            print(f"  {str(r['started_at'])[:19]:<22} "
                  f"{r['observations_ingested']:>5} "
                  f"{r['events_created']:>7} "
                  f"{r['events_investigated']:>7} "
                  f"{r['channel3_calls_used']:>4} "
                  f"{r['search_queries_used']:>8}")
    print()

    # --- Change events ---
    ev_total = conn.execute("SELECT COUNT(*) FROM change_events").fetchone()[0]
    print(f"Change events total: {ev_total}")
    if ev_total > 0:
        rows = conn.execute(
            "SELECT status, COUNT(*) as n FROM change_events GROUP BY status"
        ).fetchall()
        for r in rows:
            print(f"  {r['status']:<20} {r['n']}")
    print()

    # --- Assessments ---
    asmnt = conn.execute("SELECT COUNT(*) FROM assessments").fetchone()[0]
    print(f"Assessments stored: {asmnt}")

    conn.close()


if __name__ == "__main__":
    main()
