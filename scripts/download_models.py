"""Download the Pillar A models into the project-local cache `.models/hf` (one-time, ~3.5 GB).

Run: `uv run python scripts/download_models.py`
At runtime the app loads these files offline (HF_HUB_OFFLINE=1); nothing else is fetched.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings  # noqa: E402

ALLOW = ["*.json", "*.safetensors", "*.txt", "*.model", "tokenizer*", "1_Pooling/*", "*.py"]
IGNORE = ["onnx/*", "*.onnx", "openvino/*"]


def main() -> None:
    s = get_settings()
    os.environ["HF_HOME"] = str(s.models_dir)
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ.pop("TRANSFORMERS_OFFLINE", None)
    from huggingface_hub import snapshot_download

    for repo in (s.embed_model, s.rerank_model):
        path = snapshot_download(repo, allow_patterns=ALLOW, ignore_patterns=IGNORE)
        print(f"OK {repo} -> {path}")


if __name__ == "__main__":
    main()
