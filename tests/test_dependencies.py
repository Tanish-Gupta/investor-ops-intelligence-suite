import importlib

import pytest

STACK = [
    "streamlit",
    "litellm",
    "pydantic_settings",
    "sqlmodel",
    "lancedb",
    "presidio_analyzer",
    "presidio_anonymizer",
    "fastmcp",
    "googleapiclient.discovery",
    "dateparser",
    "groq",
    "edge_tts",
]


@pytest.mark.parametrize("module", STACK)
def test_stack_module_importable(module):
    importlib.import_module(module)


def test_fastmcp_matches_m3_major_version():
    import importlib.metadata as md

    assert md.version("fastmcp").split(".")[0] == "4"


def test_cloud_requirements_are_slim_and_match_lock():
    """cloud/requirements.txt (Streamlit Cloud) pins the same versions as uv.lock, minus torch."""
    import importlib.metadata as md
    from pathlib import Path

    req = Path(__file__).resolve().parents[1] / "cloud" / "requirements.txt"
    pins = dict(
        line.split("==", 1)
        for line in req.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    )
    heavy = {"torch", "sentence-transformers", "docling", "transformers", "arize-phoenix"}
    assert not heavy & set(pins)
    for name, version in pins.items():
        assert md.version(name) == version, f"{name}: cloud pin {version} != installed"
