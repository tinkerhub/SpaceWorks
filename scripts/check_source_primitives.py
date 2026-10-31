#!/usr/bin/env python3
"""Check the exact release checkout, or export UNREVIEWED observations only."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_audit.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
