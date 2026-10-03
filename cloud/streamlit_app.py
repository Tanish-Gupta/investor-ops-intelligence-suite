"""Streamlit Community Cloud entry point (set "Main file path" to `cloud/streamlit_app.py`).

It lives in its own folder so Community Cloud installs `cloud/requirements.txt` (no torch, no
local models) instead of the root `uv.lock`. It switches on the lite runtime, then runs the
same `app.py` used locally.
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Lite runtime defaults; Streamlit secrets / env vars still override them.
os.environ.setdefault("KB_LITE", "true")
os.environ.setdefault("PHOENIX_TRACING", "false")

runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
