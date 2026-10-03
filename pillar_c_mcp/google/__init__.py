"""Google Workspace backends (`ADAPTER_MODE=google`), ported from M3's MCP server wrappers."""

from .calendar import GoogleCalendar
from .docs import GoogleDocs
from .gmail import GoogleGmail

__all__ = ["GoogleCalendar", "GoogleDocs", "GoogleGmail"]
