"""Local file backends (offline `ADAPTER_MODE=mock`)."""

from .backends import LocalCalendar, LocalDocs, LocalGmail

__all__ = ["LocalCalendar", "LocalDocs", "LocalGmail"]
