"""
scripts/import_assessments.py
================================
Load existing EventAssessment JSON files from data/assessments/
into the replay (or any target) database.

This lets already-cached investigation results appear in the replay
database without re-running investigation.

Usage:
  python scripts/import_assessments.py
  python scripts/import_assessments.py --db data/replay_demo.db
  python scripts/import_assessments.py --assessments-dir data/assessments --db data/replay_demo.db
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
    parser = argparse.ArgumentParser(description="Import assessment JSON files into database")
    parser.add_argument("--db", default=str(ROOT / "data" / "replay_demo.db"))
    parser.add_argument("--assessments-dir", default=str(ROOT / "data" / "assessments"))
    args = parser.parse_args()

    from src.storage.sqlite_repository import SqliteRepository
    from src.events.event_generator import ChangeEvent

    repo = SqliteRepository(args.db)
    assessments_dir = Path(args.assessments_dir)

    json_files = sorted(assessments_dir.glob("*_assessment.json"))
    print(f"Found {len(json_files)} assessment JSON files in {assessments_dir}")

    imported_events = 0
    imported_assessments = 0

    for f in json_files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            event_id = data.get("event_id", "")
            if not event_id:
                print(f"  SKIP {f.name}: no event_id")
                continue

            # Reconstruct ChangeEvent from event_summary in assessment
            es = data.get("event_summary", {})
            if es:
                # Check if we can reconstruct a minimal ChangeEvent for the DB
                # Load from change_events.json if available
                events_json = ROOT / "data" / "events" / "change_events.json"
                event_dict = None
                if events_json.exists():
                    all_events = json.loads(events_json.read_text(encoding="utf-8"))
                    event_dict = next((e for e in all_events if e["event_id"] == event_id), None)

                if event_dict:
                    repo.save_change_event(event_dict)
                    imported_events += 1
                    repo.update_event_status(event_id, "INVESTIGATED")

            # Save the assessment
            repo.save_assessment(event_id, data)
            imported_assessments += 1
            print(f"  Imported: {event_id}")

        except Exception as exc:
            print(f"  ERROR {f.name}: {exc}")

    print()
    print(f"Imported: {imported_events} events, {imported_assessments} assessments")
    repo.close()


if __name__ == "__main__":
    main()
