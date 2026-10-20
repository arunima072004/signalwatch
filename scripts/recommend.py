"""
scripts/recommend.py
=====================
Generate a pricing recommendation for an investigated event.

Usage:
  python scripts/recommend.py --event-id evt_31dae025e57ac2d6
  python scripts/recommend.py --event-id evt_835c783f6785e8bf --db data/replay_demo.db
  python scripts/recommend.py --event-id evt_835c783f6785e8bf --margin 0.20 --elasticity -2.0
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate pricing recommendation")
    parser.add_argument("--event-id", required=True, help="ChangeEvent event_id")
    parser.add_argument("--db", default=str(ROOT / "data" / "replay_demo.db"),
                        help="Database path (default: replay_demo.db)")
    parser.add_argument("--cost-ratio", type=float, default=0.80,
                        help="Cost as fraction of median pre-event price (default 0.80 = 80%%)")
    parser.add_argument("--beta", type=float, default=5.0,
                        help="Demand sensitivity beta (default 5.0; higher = more elastic)")
    parser.add_argument("--our-price", type=float, default=None,
                        help="Override assumed own price (default = pre-event price)")
    parser.add_argument("--save", action="store_true",
                        help="Save recommendation JSON to data/assessments/")
    args = parser.parse_args()

    from src.storage.sqlite_repository import SqliteRepository
    from src.decision.recommender import recommend

    repo = SqliteRepository(args.db)

    # Find event
    event_dict = None
    for status in ["INVESTIGATED", "NEW", "INVESTIGATING", "FAILED"]:
        rows = repo.get_events_by_status(status)
        for row in rows:
            ev = row.get("event") or row
            if isinstance(ev, dict) and ev.get("event_id") == args.event_id:
                event_dict = ev
                break
        if event_dict:
            break

    if event_dict is None:
        # Try change_events.json fallback
        events_json = ROOT / "data" / "events" / "change_events.json"
        if events_json.exists():
            all_events = json.loads(events_json.read_text())
            event_dict = next((e for e in all_events if e["event_id"] == args.event_id), None)

    if event_dict is None:
        print(f"Event {args.event_id!r} not found in {args.db}")
        sys.exit(1)

    # Find assessment
    asmnt = repo.get_assessment(args.event_id)
    if asmnt:
        assessment_dict = asmnt["assessment"]
    else:
        # Try loading from file
        asmnt_file = ROOT / "data" / "assessments" / f"{args.event_id}_assessment.json"
        if asmnt_file.exists():
            assessment_dict = json.loads(asmnt_file.read_text())
        else:
            print(f"No assessment found for {args.event_id}. Run investigation first.")
            assessment_dict = {"hypothesis_assessments": []}

    rec = recommend(
        event_dict=event_dict,
        assessment_dict=assessment_dict,
        repo=repo,
        our_price=args.our_price,
        cost_ratio=args.cost_ratio,
        beta=args.beta,
    )

    rec.print_summary()

    if args.save:
        out = ROOT / "data" / "assessments" / f"{args.event_id}_recommendation.json"
        out.write_text(json.dumps(rec.to_dict(), indent=2, default=str), encoding="utf-8")
        print(f"Saved: {out}")

        # Also save to DB
        conn = repo._connect()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS recommendations (event_id TEXT PRIMARY KEY, rec_json TEXT, created_at TEXT)",
        )
        import json as _json
        from datetime import datetime, timezone
        conn.execute(
            "INSERT OR REPLACE INTO recommendations (event_id, rec_json, created_at) VALUES (?,?,?)",
            (args.event_id, _json.dumps(rec.to_dict(), default=str), datetime.now(timezone.utc).isoformat()),
        )
        print(f"Saved recommendation to database.")

    repo.close()


if __name__ == "__main__":
    main()
