"""Configuration package.

Importing it applies privacy defaults for third-party libraries *before* they are
imported elsewhere, because they read these settings once, at import time:

- Hugging Face models load only from the project-local cache `.models/hf`, offline and
  without telemetry. `scripts/download_models.py` is the one place that goes online.
- litellm uses its bundled model-cost map instead of fetching one from GitHub on import.

`setdefault` is used, so an explicit environment variable still wins.
"""

from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

PRIVACY_ENV = {
    "HF_HOME": str(_ROOT / ".models" / "hf"),
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "TOKENIZERS_PARALLELISM": "false",
    "LITELLM_LOCAL_MODEL_COST_MAP": "True",
    "DO_NOT_TRACK": "1",
}

for _k, _v in PRIVACY_ENV.items():
    os.environ.setdefault(_k, _v)
