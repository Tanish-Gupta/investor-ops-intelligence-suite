"""Deterministic day/time preference parsing in IST (subset of M3's RelativeDateResolver)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "friday": 4, "fri": 4, "saturday": 5,
    "sat": 5, "sunday": 6, "sun": 6,
}  # fmt: skip
MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4,
    "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9, "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}  # fmt: skip
PARTS = {"morning": (time(9), time(12)), "afternoon": (time(12), time(16)),
         "evening": (time(16), time(18))}  # fmt: skip

_WD = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
_MON = "|".join(sorted(MONTHS, key=len, reverse=True))
_ANY = re.compile(
    r"\b(?:any ?time|any ?day|any slot|whenever|earliest|asap|as soon as possible|soonest"
    r"|first available|next available|no preference|doesn'?t matter|don'?t mind|flexible"
    r"|anything works|either is fine)\b"
)
_REL = re.compile(r"\b(day after tomorrow|today|tonight|tomorrow|tmrw|tomorow)\b")
_NEXT_WEEK = re.compile(r"\bnext week\b")
_WEEKDAY = re.compile(rf"\b(?:(next|this|coming) )?({_WD})\b")
_DAY_MONTH = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?(?: of)? ({_MON})\b")
_MONTH_DAY = re.compile(rf"\b({_MON}) (\d{{1,2}})(?:st|nd|rd|th)?\b")
_NUMERIC = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")  # d/m (India)
_ORD_DAY = re.compile(r"\bthe (\d{1,2})(?:st|nd|rd|th)\b")
_PART = re.compile(r"\b(morning|afternoon|evening|noon|tonight|lunch ?time)\b")
_CLOCK = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b|\b(\d{1,2}):(\d{2})\b")
_AT_HOUR = re.compile(r"\b(?:at|around|by|after) (\d{1,2})\b(?!:|\s*(?:am|pm|st|nd|rd|th))")


@dataclass
class Preference:
    day: date | None = None
    part: str | None = None
    at: time | None = None
    any: bool = False

    @property
    def empty(self) -> bool:
        return not (self.day or self.part or self.at or self.any)

    def describe(self) -> str:
        bits = []
        if self.day:
            bits.append(f"{self.day:%A} {self.day.day} {self.day:%B}")
        if self.at:
            bits.append(f"around {fmt_time(self.at)}")
        elif self.part:
            bits.append(self.part)
        return " ".join(bits) or "the earliest time"


def fmt_time(t: time) -> str:
    return t.strftime("%I:%M %p").lstrip("0")


def _hour24(h: int, m: int, ampm: str | None) -> time | None:
    if ampm == "pm" and h < 12:
        h += 12
    elif ampm == "am" and h == 12:
        h = 0
    elif ampm is None and 1 <= h <= 6:
        h += 12  # "at 3" during business hours means 3 PM
    return time(h, m) if 0 <= h < 24 and 0 <= m < 60 else None


def _future(d: date, today: date) -> date:
    return d if d >= today else d.replace(year=d.year + 1)


def _safe_date(y: int, mth: int, d: int) -> date | None:
    try:
        return date(y, mth, d)
    except ValueError:
        return None


def parse_preference(text: str, now: datetime) -> Preference:
    t = re.sub(r"[^a-z0-9:/' ]", " ", text.lower())
    t = re.sub(r"\b([ap])\s?m\b", r"\1m", re.sub(r"\b([ap])\.m\.?", r"\1m", t))
    t = re.sub(r"\s+", " ", t)
    today = now.date()
    pref = Preference(any=bool(_ANY.search(t)))

    if m := _REL.search(t):
        word = m.group(1)
        offset = 2 if word == "day after tomorrow" else 0 if word in ("today", "tonight") else 1
        pref.day = today + timedelta(days=offset)
        if word == "tonight":
            pref.part = "evening"
    elif m := _WEEKDAY.search(t):
        target = WEEKDAYS[m.group(2)]
        delta = (target - today.weekday()) % 7
        if m.group(1) == "next" and delta == 0:
            delta = 7
        pref.day = today + timedelta(days=delta)
    elif m := _DAY_MONTH.search(t):
        pref.day = _safe_date(today.year, MONTHS[m.group(2)], int(m.group(1)))
    elif m := _MONTH_DAY.search(t):
        pref.day = _safe_date(today.year, MONTHS[m.group(1)], int(m.group(2)))
    elif m := _NUMERIC.search(t):
        y = int(m.group(3)) if m.group(3) else today.year
        pref.day = _safe_date(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(1)))
    elif m := _ORD_DAY.search(t):
        d = _safe_date(today.year, today.month, int(m.group(1)))
        if d and d < today:
            nm = today.month % 12 + 1
            d = _safe_date(today.year + (nm == 1), nm, int(m.group(1)))
        pref.day = d
    elif _NEXT_WEEK.search(t):
        pref.day = today + timedelta(days=(7 - today.weekday()) or 7)
    if pref.day and not _REL.search(t) and not _WEEKDAY.search(t):
        pref.day = _future(pref.day, today)

    if m := _PART.search(t):
        word = m.group(1)
        pref.part = {"noon": "afternoon", "tonight": "evening"}.get(word, word)
        if word.startswith("lunch"):
            pref.part = "afternoon"
    if m := _CLOCK.search(t):
        if m.group(1):
            pref.at = _hour24(int(m.group(1)), int(m.group(2) or 0), m.group(3))
        else:
            pref.at = _hour24(int(m.group(4)), int(m.group(5)), None)
    elif m := _AT_HOUR.search(t):
        pref.at = _hour24(int(m.group(1)), 0, None)
    return pref
