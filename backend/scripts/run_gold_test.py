"""
Run gold document test suite — PASS/FAIL for the whole system.

Usage:
  python -m scripts.run_gold_test
  python -m scripts.run_gold_test --bootstrap tests/gold/shoprite_2025 --extraction path/to/statements.xlsx --notes path/to/notes.json
"""
import sys
import os
from pathlib import Path

backend = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend))
os.chdir(backend.parent)

from tests.gold_runner import main

if __name__ == "__main__":
    sys.exit(main())
