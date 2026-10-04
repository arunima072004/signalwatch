#!/usr/bin/env python3
"""Execute all notebooks sequentially using nbconvert in-place."""

import os
import sys
from pathlib import Path

# Change to project directory
os.chdir(Path(__file__).parent)

# List of notebooks to execute
notebooks = [
    "notebooks/01_dataset_profiling.ipynb",
    "notebooks/02_price_analysis.ipynb", 
    "notebooks/03_bocpd_analysis.ipynb",
    "notebooks/04_competitive_analysis_fixed.ipynb",
    "notebooks/05_query_generation.ipynb",
]

print("="*70)
print("SIGNALWATCH NOTEBOOK EXECUTION")
print("="*70)

success_count = 0
failed_count = 0

for nb in notebooks:
    if not Path(nb).exists():
        print(f"\n⚠ {nb} not found, skipping")
        continue
    
    print(f"\n{'='*70}")
    print(f"Running: {nb}")
    print(f"{'='*70}")
    
    cmd = f'python -m nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=300 "{nb}"'
    result = os.system(cmd)
    
    if result == 0:
        print(f"[OK] {nb} completed")
        success_count += 1
    else:
        print(f"[FAIL] {nb} failed")
        failed_count += 1

print(f"\n{'='*70}")
print("FINAL SUMMARY")
print(f"{'='*70}")
print(f"Completed: {success_count}")
print(f"Failed: {failed_count}")
print(f"{'='*70}")
