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
