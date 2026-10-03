"""Append-only local Notes doc (`data/artifacts/notes.md`) shared by the pulse and MCP backends.

The doc has two sections: a `## Weekly Pulse` log (one summary per pulse id) and a
`## Bookings` log (one pipe-separated line per booking event). History is never edited.
"""

from __future__ import annotations

import threading
from pathlib import Path

from config.settings import get_settings
from core import pii

PULSE_HEADER = "## Weekly Pulse"
BOOKINGS_HEADER = "## Bookings"
_lock = threading.Lock()


def notes_path() -> Path:
    return get_settings().artifacts_dir / "notes.md"


def _ensure(path: Path) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# Advisor Pre-Booking Notes\n\n"
            "_Append-only log. Booking codes link calls, holds, drafts and pulses._\n\n"
            f"{PULSE_HEADER}\n\n{BOOKINGS_HEADER}\n\n",
            encoding="utf-8",
        )


def read_notes() -> str:
    path = notes_path()
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _insert_under(text: str, header: str, block: str) -> str:
    """Insert `block` at the end of the `header` section (before the next `## `)."""
    start = text.find(header)
    if start == -1:
        return text.rstrip("\n") + f"\n\n{header}\n\n{block}\n"
    nxt = text.find("\n## ", start + len(header))
    if nxt == -1:
        return text.rstrip("\n") + f"\n{block}\n"
    head, tail = text[:nxt].rstrip("\n"), text[nxt:]
    return f"{head}\n{block}\n{tail}"


def append_pulse_summary(pulse_id: str, summary: str) -> bool:
    """Add a pulse summary once per pulse id. Returns False when it was already present."""
    path = notes_path()
    marker = f"[{pulse_id}]"
    with _lock:
        _ensure(path)
        text = path.read_text(encoding="utf-8")
        if marker in text:
            return False
        block = f"- {marker} {pii.redact(' '.join(summary.split()))}"
        path.write_text(_insert_under(text, PULSE_HEADER, block), encoding="utf-8")
    return True


def append_booking_line(line: str) -> str:
    """Append one booking line (already formatted) and return the stored, scrubbed text."""
    path = notes_path()
    clean = pii.redact(" ".join(line.split()))
    with _lock:
        _ensure(path)
        text = path.read_text(encoding="utf-8")
        path.write_text(_insert_under(text, BOOKINGS_HEADER, f"- {clean}"), encoding="utf-8")
    return clean


def booking_lines() -> list[str]:
    text = read_notes()
    start = text.find(BOOKINGS_HEADER)
    if start == -1:
        return []
    section = text[start + len(BOOKINGS_HEADER) :]
    nxt = section.find("\n## ")
    section = section if nxt == -1 else section[:nxt]
    return [ln[2:] for ln in section.splitlines() if ln.startswith("- ")]
