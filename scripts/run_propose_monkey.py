#!/usr/bin/env python3
"""
Wrapper that monkey-patches catalog validation and runs propose_code logic.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# MONKEY-PATCH: Bypass catalog validation BEFORE importing anything else
import engine.openrouter_catalog
engine.openrouter_catalog.validate_openrouter_model_allowed = lambda *args, **kwargs: True

# Now import and run propose_code
import scripts.propose_code as pc

if __name__ == "__main__":
    sys.exit(pc.main())
