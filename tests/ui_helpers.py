"""Helpers for driving the multipage Streamlit app with AppTest."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")
PAGES = ["home", "ask", "book", "pulse", "approvals"]  # Home + customer and admin portals


def open_app(timeout: int = 90) -> AppTest:
    return AppTest.from_file(APP, default_timeout=timeout).run()


def goto(at: AppTest, page: str) -> AppTest:
    at.switch_page(f"views/{page}.py")
    return at.run()


def md(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown)


def say(at: AppTest, text: str) -> AppTest:
    at.text_input(key="voice_text").input(text)
    at.button(key="FormSubmitter:voice_form-Send").click()
    return at.run()


def click_label(at: AppTest, label: str) -> AppTest:
    next(b for b in at.button if b.label == label).click()
    return at.run()
