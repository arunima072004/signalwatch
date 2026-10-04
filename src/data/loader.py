"""
src/data/loader.py
==================
Responsible for reading the raw Datafiniti Electronics Products Pricing CSV
into a pandas DataFrame without any mutation of the raw file.

Key design decisions
--------------------
* prices.dateSeen is a comma-separated list of ISO-8601 timestamps stored in
  a single cell.  The loader returns the raw string; explosion into individual
  observations is the responsibility of preprocessing.py.
* The trailing empty column that appears in the CSV header is silently dropped
  here so that downstream modules never see it.
* Encoding errors are replaced with the Unicode replacement character rather
  than raising so that the pipeline is robust to occasional binary artefacts.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# All column names that are actually present in the Datafiniti CSV.
# The trailing empty column produced by the extra commas is excluded.
EXPECTED_COLUMNS: list[str] = [
    "id",
    "prices.amountMax",
    "prices.amountMin",
    "prices.availability",
    "prices.condition",
    "prices.currency",
    "prices.dateSeen",
    "prices.isSale",
    "prices.merchant",
    "prices.shipping",
    "prices.sourceURLs",
    "asins",
    "brand",
    "categories",
    "dateAdded",
    "dateUpdated",
    "ean",
    "imageURLs",
    "keys",
    "manufacturer",
    "manufacturerNumber",
    "name",
    "primaryCategories",
    "sourceURLs",
    "upc",
    "weight",
]

# Path pointer file written by project setup
_POINTER_FILE = Path(__file__).resolve().parents[2] / "data" / "raw" / "DATA_PATH.txt"


def _resolve_raw_path(raw_path: str | Path | None) -> Path:
    """
    Return the path to the raw CSV.

    Priority order:
    1. Explicit ``raw_path`` argument.
    2. ``DATA_PATH.txt`` pointer file next to the raw data directory.
    3. Environment variable ``SIGNALWATCH_RAW_DATA``.

    Raises
    ------
    FileNotFoundError
        When no valid path can be resolved or the file does not exist.
    """
    if raw_path is not None:
        p = Path(raw_path)
        if p.exists():
            return p
        raise FileNotFoundError(f"Explicit raw_path does not exist: {p}")

    env_path = os.environ.get("SIGNALWATCH_RAW_DATA")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
        raise FileNotFoundError(f"SIGNALWATCH_RAW_DATA points to non-existent file: {p}")

    if _POINTER_FILE.exists():
        pointer_content = _POINTER_FILE.read_text(encoding="utf-8").strip()
        p = Path(pointer_content)
        if p.exists():
            return p
        raise FileNotFoundError(
            f"DATA_PATH.txt points to '{p}' which does not exist."
        )

    raise FileNotFoundError(
        "Cannot locate raw data file. "
        "Pass raw_path explicitly, set SIGNALWATCH_RAW_DATA env var, "
        "or ensure data/raw/DATA_PATH.txt contains a valid path."
    )


def load_raw(raw_path: str | Path | None = None) -> pd.DataFrame:
    """
    Load the raw Datafiniti CSV into a DataFrame.

    Parameters
    ----------
    raw_path:
        Optional explicit path to the CSV file.  When omitted the path is
        resolved automatically (see ``_resolve_raw_path``).

    Returns
    -------
    pd.DataFrame
        Raw DataFrame — no column renaming, no type coercion, no filtering.
        The trailing empty column is dropped.  All values remain as strings
        so that the profiler and preprocessing steps can make informed
        decisions about parsing.
    """
    path = _resolve_raw_path(raw_path)
    logger.info("Loading raw data from: %s", path)

    df = pd.read_csv(
        path,
        dtype=str,           # keep everything as str; let preprocessing parse
        encoding="utf-8",
        encoding_errors="replace",
        low_memory=False,
    )

    # Drop the trailing empty column(s) introduced by the extra commas in the
    # Datafiniti export format.
    unnamed_cols = [c for c in df.columns if str(c).strip() == "" or str(c).startswith("Unnamed:")]
    if unnamed_cols:
        df.drop(columns=unnamed_cols, inplace=True)
        logger.debug("Dropped %d unnamed/empty column(s): %s", len(unnamed_cols), unnamed_cols)

    logger.info(
        "Raw data loaded: %d rows × %d columns", len(df), len(df.columns)
    )
    return df


def get_raw_path(raw_path: str | Path | None = None) -> Path:
    """Return the resolved path to the raw CSV (for scripts that need the path)."""
    return _resolve_raw_path(raw_path)
