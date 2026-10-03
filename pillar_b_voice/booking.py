"""Booking codes `NL-[A-HJ-NP-Z][2-9]{3}` (ported from M3 domain/codes.py)."""

from __future__ import annotations

import re
import secrets
import string
from collections.abc import Callable

LETTERS = "".join(c for c in string.ascii_uppercase if c not in "IO")  # easier to read back
DIGITS = "23456789"  # no 0, 1 (easier to read back)
CODE_RE = re.compile(r"^NL-([A-HJ-NP-Z])(\d{3})$")
MAX_ATTEMPTS = 50


class CodeSpaceExhausted(RuntimeError):
    pass


def generate(exists: Callable[[str], bool]) -> str:
    for _ in range(MAX_ATTEMPTS):
        code = f"NL-{secrets.choice(LETTERS)}{''.join(secrets.choice(DIGITS) for _ in range(3))}"
        if not exists(code):
            return code
    raise CodeSpaceExhausted("could not find a free booking code")


def spoken(code: str) -> str:
    """'NL-A742' → 'N L dash A 7 4 2' (character-by-character TTS read-back)."""
    return " ".join("dash" if c == "-" else c for c in code)


_TYPED_RE = re.compile(r"\bnl\s*-?\s*([a-z])\s*-?\s*(\d)\s*(\d)\s*(\d)\b", re.IGNORECASE)
_NUMBER_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}  # fmt: skip


def _canonical(letter: str, digits: str) -> str | None:
    code = f"NL-{letter.upper()}{digits}"
    return code if CODE_RE.match(code) else None


def parse(text: str) -> str | None:
    """'NL-A742', 'nl a742', 'N L dash A seven four two', 'A as in apple 7 4 2' → 'NL-A742'."""
    if m := _TYPED_RE.search(text):
        return _canonical(m.group(1), "".join(m.group(2, 3, 4)))
    tokens = re.findall(r"[a-z]+|\d", text.lower())
    runs: list[str] = []
    current = ""
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if len(tok) == 1 and tok.isalpha() and tokens[i + 1 : i + 3] == ["as", "in"]:
            current += tok
            i += 4
            continue
        if tok in _NUMBER_WORDS:
            current += _NUMBER_WORDS[tok]
        elif tok == "dash":
            pass
        elif tok.isdigit() or (len(tok) == 1 and tok.isalpha()) or tok == "nl":
            current += tok
        else:
            if current:
                runs.append(current)
            current = ""
        i += 1
    if current:
        runs.append(current)
    for run in runs:
        m = re.search(r"nl([a-z])(\d{3})$", run) or re.fullmatch(r"([a-z])(\d{3})", run)
        if m and (code := _canonical(m.group(1), m.group(2))):
            return code
    return None
