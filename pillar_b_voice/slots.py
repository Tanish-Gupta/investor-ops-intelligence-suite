"""Advisor availability: read the mock calendar, exclude booked slots, offer exactly 2 IST slots."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from config.settings import ROOT_DIR, get_settings
from core import state

from .when import PARTS, Preference

AVAILABILITY_PATH = ROOT_DIR / "data" / "availability.json"
ACTIVE = {state.BookingStatus.TENTATIVE.value, state.BookingStatus.CONFIRMED.value,
          state.BookingStatus.RESCHEDULED.value,
          state.BookingStatus.NEEDS_ATTENTION.value}  # fmt: skip
MIN_LEAD = timedelta(hours=1)


@dataclass(frozen=True, order=True)
class Slot:
    start: datetime
    end: datetime

    def label(self) -> str:
        """'Monday 5 October, 9:30 AM IST'."""
        s = self.start
        return f"{s:%A} {s.day} {s:%B}, {s:%I:%M %p}".replace(", 0", ", ") + " IST"

    def to_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> tuple[Slot, ...]:
    data = json.loads(Path(path).read_text())
    tz = get_settings().tz
    out = []
    for day in data.get("days", []):
        for s in day.get("slots", []):
            if s.get("status") == "free":
                out.append(
                    Slot(
                        datetime.fromisoformat(s["start"]).astimezone(tz),
                        datetime.fromisoformat(s["end"]).astimezone(tz),
                    )
                )
    return tuple(sorted(out))


def all_free_slots(path: Path | None = None) -> tuple[Slot, ...]:
    p = Path(path or AVAILABILITY_PATH)
    if not p.exists():
        return ()
    return _load(str(p), p.stat().st_mtime)


def _booked_starts(exclude_code: str | None = None) -> set[datetime]:
    tz = get_settings().tz
    return {
        b.slot_start_ist.astimezone(tz)
        for b in state.list_bookings()
        if b.status in ACTIVE and b.slot_start_ist and b.booking_code != exclude_code
    }


def free_slots(
    now: datetime, *, exclude_code: str | None = None, path: Path | None = None
) -> list[Slot]:
    booked = _booked_starts(exclude_code)
    return [s for s in all_free_slots(path) if s.start >= now + MIN_LEAD and s.start not in booked]


def _in_part(s: Slot, part: str | None) -> bool:
    if not part:
        return True
    lo, hi = PARTS[part]
    return lo <= s.start.time() < hi


def offer(
    pref: Preference,
    now: datetime,
    *,
    skip: Iterable[Slot] = (),
    exclude_code: str | None = None,
    path: Path | None = None,
) -> tuple[list[Slot], bool]:
    """Return (≤ 2 slots, exact) where `exact` = they match the requested day/part/time."""
    skipped = set(skip)
    pool = [s for s in free_slots(now, exclude_code=exclude_code, path=path) if s not in skipped]
    if not pool:
        return [], False

    def pick(cands: list[Slot]) -> list[Slot]:
        if pref.at:
            target = pref.at.hour * 60 + pref.at.minute
            cands = sorted(
                cands, key=lambda s: (abs(s.start.hour * 60 + s.start.minute - target), s.start)
            )
            return sorted(cands[:2])
        return cands[:2]

    day: date | None = pref.day
    tiers = []
    if day:
        same_day = [s for s in pool if s.start.date() == day]
        tiers.append([s for s in same_day if _in_part(s, pref.part)])
        tiers.append(same_day if not pref.part else [])
        later = [s for s in pool if s.start.date() > day]
        tiers.append([s for s in later if _in_part(s, pref.part)])
        tiers.append(later)
    else:
        tiers.append([s for s in pool if _in_part(s, pref.part)])
    tiers.append(pool)
    for i, cands in enumerate(tiers):
        if cands:
            chosen = pick(cands)
            exact = i == 0 and (not pref.at or any(s.start.time() == pref.at for s in chosen))
            return chosen, exact
    return [], False
