"""Local embedding and reranking models (loaded lazily, once per process).

Models live in the project-local cache `.models/hf` (fetched once with
`scripts/download_models.py`). At runtime the Hub is put in offline mode so nothing is
downloaded or phoned home.
"""

from __future__ import annotations

import logging
import os
import threading
from functools import lru_cache
from typing import TYPE_CHECKING

from config.settings import get_settings

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder, SentenceTransformer

_log = logging.getLogger(__name__)
_lock = threading.Lock()


class ModelUnavailable(RuntimeError):
    """The model is not in the local cache (run scripts/download_models.py)."""


def configure_hf_env() -> None:
    s = get_settings()
    os.environ["HF_HOME"] = str(s.models_dir)
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    if s.hf_offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"


def local_model_path(repo_id: str) -> str:
    """Return the cached snapshot directory for `repo_id` without touching the network."""
    configure_hf_env()
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        return snapshot_download(
            repo_id, cache_dir=str(get_settings().models_dir / "hub"), local_files_only=True
        )
    except (LocalEntryNotFoundError, FileNotFoundError, OSError) as exc:
        raise ModelUnavailable(
            f"{repo_id} not in local cache; run `uv run python scripts/download_models.py`"
        ) from exc


def _device() -> str:
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    return "cuda" if torch.cuda.is_available() else "cpu"


@lru_cache(maxsize=1)
def embedder() -> SentenceTransformer:
    configure_hf_env()
    from sentence_transformers import SentenceTransformer

    name = get_settings().embed_model
    with _lock:
        try:
            model = SentenceTransformer(
                local_model_path(name), device=_device(), local_files_only=True
            )
        except OSError as exc:
            raise ModelUnavailable(f"{name} not in local cache: {exc}") from exc
    _log.info("embedder_loaded", extra={"model": name})
    return model


@lru_cache(maxsize=1)
def reranker() -> CrossEncoder:
    configure_hf_env()
    from sentence_transformers import CrossEncoder

    name = get_settings().rerank_model
    with _lock:
        try:
            model = CrossEncoder(
                local_model_path(name), device=_device(), max_length=512, local_files_only=True
            )
        except OSError as exc:
            raise ModelUnavailable(f"{name} not in local cache: {exc}") from exc
    _log.info("reranker_loaded", extra={"model": name})
    return model


def embed_documents(texts: list[str]) -> list[list[float]]:
    vecs = embedder().encode(texts, batch_size=8, normalize_embeddings=True)
    return [v.tolist() for v in vecs]


def embed_query(text: str) -> list[float]:
    # Qwen3-Embedding uses an instruction prompt for queries only.
    model = embedder()
    kwargs = {"prompt_name": "query"} if "query" in (model.prompts or {}) else {}
    return model.encode([text], normalize_embeddings=True, **kwargs)[0].tolist()


def rerank(query: str, texts: list[str]) -> list[float]:
    """Relevance in [0, 1] (sigmoid of the cross-encoder logit) for each text."""
    if not texts:
        return []
    scores = reranker().predict([(query, t) for t in texts], batch_size=8)
    return [float(s) for s in scores]
