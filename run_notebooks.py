#!/usr/bin/env python3
"""Execute all analysis notebooks end-to-end."""

import os
import sys
import subprocess
import json
from pathlib import Path

def run_notebook(notebook_path):
    """Execute a single notebook using nbconvert."""
    notebook_path = Path(notebook_path)
    output_path = notebook_path.parent / f"{notebook_path.stem}_output{notebook_path.suffix}"
    
    print(f"\n{'='*70}")
    print(f"Executing: {notebook_path.name}")
    print(f"{'='*70}")
    
    cmd = [
        sys.executable,
        "-m", "nbconvert",
        "--to", "notebook",
        "--execute",
        "--ExecutePreprocessor.timeout=600",
        f"--output={output_path}",
        str(notebook_path)
    ]
    
    result = subprocess.run(cmd, capture_output=False, text=True)
    
    if result.returncode == 0:
        print(f"✓ {notebook_path.name} completed successfully")
        # Copy output back to original
        import shutil
        shutil.copy(output_path, notebook_path)
        output_path.unlink()
        return True
    else:
        print(f"✗ {notebook_path.name} failed with exit code {result.returncode}")
        return False

def main():
    """Execute all notebooks in order."""
    notebooks_dir = Path("notebooks")
    notebooks = [
        "01_dataset_profiling.ipynb",
        "02_price_analysis.ipynb",
        "03_bocpd_analysis.ipynb",
        "04_competitive_analysis.ipynb",
        "05_query_generation.ipynb",
    ]
    
    os.chdir(Path(__file__).parent)
    
    results = {}
    for nb in notebooks:
        nb_path = notebooks_dir / nb
        if not nb_path.exists():
            print(f"⚠ {nb} not found, skipping")
            results[nb] = "skipped"
            continue
        
        success = run_notebook(nb_path)
        results[nb] = "completed" if success else "failed"
    
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    for nb, status in results.items():
        icon = "✓" if status == "completed" else ("⚠" if status == "skipped" else "✗")
        print(f"{icon} {nb}: {status}")
    
    failed = sum(1 for s in results.values() if s == "failed")
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
