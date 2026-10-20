"""tests/test_loader.py — Tests for src/data/loader.py"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.data.loader import _resolve_raw_path, load_raw


def test_load_raw_returns_dataframe(tmp_path):
    """load_raw() should return a non-empty DataFrame."""
    # Write a minimal CSV
    csv = tmp_path / "test.csv"
    csv.write_text(
        "id,prices.amountMax,prices.amountMin,prices.dateSeen,prices.merchant,"
        "prices.isSale,brand,name,primaryCategories,\n"
        "P001,99.99,99.99,2017-01-01T00:00:00Z,Amazon.com,FALSE,BrandA,Prod A,Electronics,\n",
        encoding="utf-8",
    )
    df = load_raw(str(csv))
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 1


def test_load_raw_drops_empty_columns(tmp_path):
    """Trailing empty columns should be dropped."""
    csv = tmp_path / "test.csv"
    csv.write_text(
        "id,prices.dateSeen,,\n"
        "P001,2017-01-01T00:00:00Z,,\n",
        encoding="utf-8",
    )
    df = load_raw(str(csv))
    assert "" not in df.columns
    assert not any(c.startswith("Unnamed:") for c in df.columns)


def test_load_raw_all_string_dtype(tmp_path):
    """All columns should be string dtype (object in pandas 2, StringDtype in pandas 3+)."""
    csv = tmp_path / "test.csv"
    csv.write_text(
        "id,prices.amountMin,prices.dateSeen\n"
        "P001,99.99,2017-01-01T00:00:00Z\n",
        encoding="utf-8",
    )
    df = load_raw(str(csv))
    for col in df.columns:
        is_string_like = df[col].dtype == object or pd.api.types.is_string_dtype(df[col])
        assert is_string_like, f"Column {col} should be string dtype, got {df[col].dtype}"


def test_resolve_raw_path_explicit(tmp_path):
    """Explicit path argument takes priority."""
    csv = tmp_path / "data.csv"
    csv.write_text("a,b\n1,2\n", encoding="utf-8")
    resolved = _resolve_raw_path(str(csv))
    assert resolved == csv


def test_resolve_raw_path_missing_raises():
    """Non-existent explicit path should raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        _resolve_raw_path("/nonexistent/path/file.csv")


def test_load_raw_missing_path_raises():
    """load_raw with a non-existent path raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_raw("/this/does/not/exist.csv")
