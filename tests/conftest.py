"""Pytest bootstrap: make ``src/`` importable.

The project uses a src-layout (`src/data_agent_baseline/...`) but the test
suite runs without `pip install -e .`, so we extend ``sys.path`` here so that
``from data_agent_baseline.run.vote import vote_task`` resolves directly.

Keeping this in conftest.py (not pyproject) means pytest picks it up
automatically without requiring a packaging step before each `pytest` run.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
