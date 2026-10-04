#!/usr/bin/env python3
"""Execute notebooks directly with nbconvert using proper path handling."""

import subprocess
import sys
from pathlib import Path

def execute_notebook(notebook_path):
    """Execute a single notebook."""
    notebook_path = Path(notebook_path)
    print(f"\n{'='*70}")
    print(f"Executing: {notebook_path.name}")
    print(f"{'='*70}")
    
    # Use absolute path to avoid path issues
    cmd = [
        sys.executable,
        "-m", "nbconvert",
        "--to", "notebook",
        "--execute",
        "--ExecutePreprocessor.timeout=300",
        "--inplace",
        str(notebook_path.absolute())
    ]
    
    result = subprocess.run(cmd, cwd=str(notebook_path.parent))
    return result.returncode == 0

def main():
    """Execute all notebooks."""
    base = Path("d:\\market intelligence agent\\signalwatch")
    notebooks = [
        base / "notebooks" / "01_dataset_profiling.ipynb",
        base / "notebooks" / "02_price_analysis.ipynb",
        base / "notebooks" / "03_bocpd_analysis.ipynb",
        base / "notebooks" / "04_competitive_analysis_fixed.ipynb",
        base / "notebooks" / "05_query_generation.ipynb",
    ]
    
    results = {}
    for nb in notebooks:
        if not nb.exists():
            print(f"⚠ {nb.name} not found")
            results[nb.name] = "skipped"
            continue
        
        try:
            success = execute_notebook(nb)
            results[nb.name] = "completed" if success else "failed"
        except Exception as e:
            print(f"Error executing {nb.name}: {e}")
            results[nb.name] = "error"
    
    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    for name, status in results.items():
        icon = "✓" if status == "completed" else ("⚠" if status == "skipped" else "✗")
        print(f"{icon} {name}: {status}")

if __name__ == "__main__":
    main()
