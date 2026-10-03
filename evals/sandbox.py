"""Isolated eval workspace: every write (SQLite, pulses, notes, holds, drafts) goes to a temp dir.

Read-only inputs (corpus, sources.csv, LanceDB index) are symlinked from the real data dir so
Unified Search answers exactly as in the app, while nothing the evals create touches real
artifacts.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from config.settings import get_settings

READ_ONLY_INPUTS = ("corpus", "lancedb", "lancedb_lite", "sources.csv")


def _clear_caches() -> None:
    from core import state
    from pillar_a_kb import retriever
    from pillar_c_mcp.client import reset_bundles

    get_settings.cache_clear()
    state.get_engine.cache_clear()
    retriever._retriever = None
    reset_bundles()


@contextmanager
def sandbox(keep_dir: Path | None = None) -> Iterator[Path]:
    """Point DATA_DIR / DB_PATH at a fresh directory for the duration of the block."""
    real = get_settings().data_dir
    saved = {k: os.environ.get(k) for k in ("DATA_DIR", "DB_PATH")}
    tmp = None
    if keep_dir is None:
        tmp = tempfile.TemporaryDirectory(prefix="investor-ops-eval-")
        root = Path(tmp.name)
    else:
        root = keep_dir
        root.mkdir(parents=True, exist_ok=True)
    for name in READ_ONLY_INPUTS:
        src, dst = real / name, root / name
        if src.exists() and not dst.exists():
            dst.symlink_to(src.resolve(), target_is_directory=src.is_dir())
    os.environ["DATA_DIR"] = str(root)
    os.environ["DB_PATH"] = str(root / "artifacts" / "suite.db")
    _clear_caches()
    try:
        yield root
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _clear_caches()
        if tmp is not None:
            tmp.cleanup()
