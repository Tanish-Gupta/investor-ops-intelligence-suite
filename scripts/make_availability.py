"""Generate the mock advisor calendar `data/availability.json`.

The file lists the next N working days (Mon-Fri) in IST with 30-minute slots inside business
hours, matching M3 (`slot_duration_min=30`, `business_hours=(9, 18)`). About a third of the slots
are marked busy with a fixed seed, so runs are reproducible and the "no free slot" path has data.

    uv run python scripts/make_availability.py                 # from the next working day
    uv run python scripts/make_availability.py --start 2026-10-05 --days 10
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "data" / "availability.json"
IST = ZoneInfo("Asia/Kolkata")
SLOT_MIN = 30
HOURS = (9, 18)  # [start, end)
BUSY_SHARE = 0.35
SEED = 20261003


def working_days(start: date, n: int) -> list[date]:
    days, d = [], start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def build(start: date, n_days: int, seed: int = SEED) -> dict:
    rng = random.Random(seed)
    out_days = []
    for d in working_days(start, n_days):
        slots = []
        t = datetime.combine(d, time(HOURS[0]), IST)
        end_of_day = datetime.combine(d, time(HOURS[1]), IST)
        while t + timedelta(minutes=SLOT_MIN) <= end_of_day:
            end = t + timedelta(minutes=SLOT_MIN)
            status = "busy" if rng.random() < BUSY_SHARE else "free"
            slots.append({"start": t.isoformat(), "end": end.isoformat(), "status": status})
            t = end
        out_days.append({"date": d.isoformat(), "weekday": d.strftime("%A"), "slots": slots})
    return {
        "timezone": "Asia/Kolkata",
        "slot_minutes": SLOT_MIN,
        "business_hours": {"start": f"{HOURS[0]:02d}:00", "end": f"{HOURS[1]:02d}:00"},
        "generated_on": datetime.now(IST).date().isoformat(),
        "mock": True,
        "days": out_days,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--start", type=date.fromisoformat, help="first day (default: next working day)"
    )
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--dest", type=Path, default=DEST)
    args = ap.parse_args()

    start = args.start or working_days(datetime.now(IST).date() + timedelta(days=1), 1)[0]
    data = build(start, args.days)
    args.dest.parent.mkdir(parents=True, exist_ok=True)
    args.dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    free = sum(s["status"] == "free" for day in data["days"] for s in day["slots"])
    total = sum(len(day["slots"]) for day in data["days"])
    print(
        f"wrote {args.dest.relative_to(ROOT)}: {len(data['days'])} days, {free}/{total} slots free"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
