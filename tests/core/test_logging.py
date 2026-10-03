import json
import logging

from core.logging import JsonFormatter, PIIRedactionFilter, configure_logging
from core.pii import REDACTED


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []
        self.addFilter(PIIRedactionFilter())
        self.setFormatter(JsonFormatter())

    def emit(self, record):
        self.lines.append(self.format(record))


def _logger(name):
    h = _Capture()
    log = logging.getLogger(name)
    log.addHandler(h)
    log.setLevel(logging.INFO)
    log.propagate = False
    return log, h


def test_message_args_and_extras_redacted():
    log, h = _logger("t1")
    try:
        log.info(
            "user %s said %s",
            "jane@example.com",
            "PAN ABCPD1234E",
            extra={"phone": "9876543210", "nested": {"email": "a@b.com"}, "code": "NL-A742"},
        )
    finally:
        log.removeHandler(h)
    line = h.lines[0]
    for raw in ("jane@example.com", "ABCPD1234E", "9876543210", "a@b.com"):
        assert raw not in line
    data = json.loads(line)
    assert REDACTED in data["msg"] and data["code"] == "NL-A742"
    assert data["ts"].endswith("+05:30")


def test_exception_text_redacted():
    log, h = _logger("t2")
    try:
        raise ValueError("bad email jane@example.com")
    except ValueError:
        log.exception("failed")
    finally:
        log.removeHandler(h)
    assert "jane@example.com" not in h.lines[0]
    assert "exc" in json.loads(h.lines[0])


def test_configure_logging_file_has_no_raw_pii(tmp_path):
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        log_file = tmp_path / "app.log"
        configure_logging("INFO", log_file=log_file, force=True)
        logging.getLogger("suite").info("my name is Rahul Sharma, call 9876543210")
        for h in root.handlers:
            h.flush()
        content = log_file.read_text()
        assert "9876543210" not in content and "Sharma" not in content
        assert REDACTED in content
    finally:
        for h in root.handlers:
            h.close()
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
