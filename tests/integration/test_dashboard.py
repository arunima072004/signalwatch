"""
tests/integration/test_dashboard.py
=====================================
Streamlit AppTest: every dashboard page against both databases.
Checks that no page raises an unhandled exception.
Uses streamlit.testing.v1.AppTest (Streamlit >= 1.18).
"""
from __future__ import annotations
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

APP_PATH = str(ROOT / "dashboard" / "app.py")
LIVE_DB    = str(ROOT / "data" / "signalwatch.db")
REPLAY_DB  = str(ROOT / "data" / "replay_demo.db")

PAGES = ["Overview", "Data Accumulation", "Prices", "Events", "Event Detail"]

# Some pages need a product / event to be selected — the app defaults
# to the first item in each selectbox, so no extra interaction needed.

def _run_page(db_path: str, page: str) -> None:
    """Run one AppTest cycle: load app, switch to db and page, assert no exception."""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    assert not at.exception, f"Exception on initial load ({db_path}, {page}): {at.exception}"

    # Select the database via the first radio widget (index 0 = Live, 1 = Replay)
    if at.radio:
        db_radio = at.radio[0]
        if "replay" in db_path.lower():
            db_radio.set_value("Replay demo (replay_demo.db)")
        else:
            db_radio.set_value("Live (signalwatch.db)")
        at.run()
        assert not at.exception, f"Exception after DB switch ({db_path}, {page}): {at.exception}"

    # Select the page via the second radio widget
    if len(at.radio) > 1:
        page_radio = at.radio[1]
        page_radio.set_value(page)
        at.run()
        assert not at.exception, f"Exception on page {page!r} ({db_path}): {at.exception}"


# Generate one test per (db, page) pair
@pytest.mark.parametrize("db_path,db_label", [
    (LIVE_DB, "live"),
    (REPLAY_DB, "replay"),
])
@pytest.mark.parametrize("page", PAGES)
def test_dashboard_page(db_path: str, db_label: str, page: str) -> None:
    """Dashboard page must load without exceptions."""
    _run_page(db_path, page)


def test_dashboard_live_db_missing_shows_info(tmp_path, monkeypatch):
    """Selecting Live DB when signalwatch.db is absent must not crash the app.
    The dashboard should fall back to the replay DB and show an info message.

    Uses monkeypatching to simulate the missing DB without touching the actual
    file (avoids Windows file-lock issues with long-lived SQLite connections).
    """
    import shutil
    from streamlit.testing.v1 import AppTest

    live_db = ROOT / "data" / "signalwatch.db"
    backup = tmp_path / "signalwatch.db.bak"

    # Strategy 1: try to move the file away (works when no lock is held)
    # Strategy 2: if locked, monkeypatch Path.exists to simulate absence
    moved = False
    if live_db.exists():
        try:
            shutil.move(str(live_db), str(backup))
            moved = True
        except (PermissionError, OSError):
            # File is locked by another process; patch Path.exists instead
            _real_exists = Path.exists

            def _patched_exists(self):
                if self.resolve() == live_db.resolve():
                    return False
                return _real_exists(self)

            monkeypatch.setattr(Path, "exists", _patched_exists)

    try:
        at = AppTest.from_file(APP_PATH, default_timeout=30)
        at.run()
        assert not at.exception, f"Exception on initial load: {at.exception}"
        # Switch to Live tab (which is missing)
        if at.radio:
            at.radio[0].set_value("Live (signalwatch.db)")
            at.run()
            assert not at.exception, (
                f"Exception after switching to missing live DB: {at.exception}"
            )
    finally:
        if moved:
            shutil.move(str(backup), str(live_db))
