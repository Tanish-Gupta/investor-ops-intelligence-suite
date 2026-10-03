"""Fee calculators driven by `config/fee_rules.yaml` (bullet 4 is computed here, never by the LLM).

All arithmetic uses Decimal. Each result carries the doc_ids whose rules it applied, so the
validator can treat its numbers as grounded and the composer can cite the right sources.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pillar_a_kb.corpus import fee_rules
from pillar_a_kb.textutil import numbers

EXAMPLE_AMOUNT = Decimal("100000")  # ₹1,00,000: the explainer's example amount
EXAMPLE_NAV = Decimal("100")


@dataclass(frozen=True)
class Calc:
    text: str  # one sentence, ready for bullet 4
    doc_ids: tuple[str, ...]

    @property
    def numbers(self) -> set[Decimal]:
        return numbers(self.text)


def pct(rate: str | Decimal) -> Decimal:
    return Decimal(str(rate)) / Decimal(100)


def fmt_pct(rate: str | Decimal) -> str:
    return f"{rate}%"


def inr(amount: Decimal) -> str:
    """Indian digit grouping: 100000 -> ₹1,00,000; 0.5 -> ₹0.50."""
    q = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    whole, frac = divmod(q, 1)
    s = str(int(whole))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join([head, *groups, tail]) if head else ",".join([*groups, tail])
    return f"₹{s}" if frac == 0 else f"₹{s}.{str(frac)[2:].ljust(2, '0')}"


def _calc(text: str, *doc_ids: str) -> Calc:
    return Calc(text, tuple(dict.fromkeys(doc_ids)))


# --- Rules --------------------------------------------------------------------------------
def stamp_duty(amount: Decimal = EXAMPLE_AMOUNT) -> Calc:
    r = fee_rules()["stamp_duty"]
    duty = amount * pct(r["rate_pct"])
    return _calc(
        f"Example: {inr(amount)} × {fmt_pct(r['rate_pct'])} = {inr(duty)} stamp duty, so units "
        f"are allotted for {inr(amount - duty)}.",
        r["doc_id"],
    )


def stt_applies(category: str) -> bool:
    return category in fee_rules()["stt"]["applies_to_categories"]


def stt(amount: Decimal = EXAMPLE_AMOUNT) -> Calc:
    r = fee_rules()["stt"]
    return _calc(
        f"Example: redeeming {inr(amount)} of equity-oriented fund units attracts STT of "
        f"{fmt_pct(r['rate_pct'])} = {inr(amount * pct(r['rate_pct']))}.",
        r["doc_id"],
    )


def expense_ratio(ter_pct: str, holding: Decimal = EXAMPLE_AMOUNT) -> Calc:
    r = fee_rules()["expense_ratio"]
    cost = holding * pct(ter_pct)
    return _calc(
        f"Example: on an average holding of {inr(holding)}, a {ter_pct}% TER is about "
        f"{inr(cost)} over a year, seen only as a lower NAV.",
        r["doc_id"],
    )


def elss_lock_in() -> Calc:
    r = fee_rules()["lock_in"]["ELSS"]
    return _calc(
        f"Example: SIP instalments from January to December 2024 unlock month by month from "
        f"January to December 2027, each {r['years']} years after its own allotment.",
        r["doc_id"],
    )


ExitStatus = Literal["no_load", "inside", "outside", "graded", "graded_nil", "unknown_period"]


@dataclass(frozen=True)
class ExitLoad:
    status: ExitStatus
    rate_pct: str | None  # applicable rate for the holding period (None = nil)
    window_days: int | None  # end of the load window for flat slabs
    doc_id: str
    calc: Calc
    window_text: str | None = None  # window as the scheme page words it ("90 days", "6 months")
    free_units_pct: int | None = None  # share of units redeemable inside the window without load

    @property
    def window_label(self) -> str:
        return self.window_text or f"{self.window_days} days"


def exit_load(
    scheme_id: str,
    holding_days: int | None = None,
    amount: Decimal | None = None,
) -> ExitLoad:
    """Exit load for a scheme and holding period (days counted from allotment)."""
    rules = fee_rules()["exit_load"]
    s = rules["schemes"][scheme_id]
    doc = s["doc_id"]
    explainer = s.get("explainer_doc_id", rules["explainer_doc_id"])

    if s.get("graded"):
        amt = amount or EXAMPLE_AMOUNT
        nil_from = s["nil_from_day"]
        if holding_days is not None and holding_days >= nil_from:
            return ExitLoad(
                "graded_nil",
                None,
                None,
                doc,
                _calc(
                    f"Example: redeeming on day {holding_days} has no exit load (nil from day "
                    f"{nil_from}), so {inr(amt)} is paid out in full.",
                    doc,
                    explainer,
                ),
            )
        day = holding_days if holding_days else 1
        rate = next(sl["rate_pct"] for sl in s["slabs"] if sl["day"] == day)
        load = amt * pct(rate)
        status: ExitStatus = "graded" if holding_days else "unknown_period"
        return ExitLoad(
            status,
            rate,
            None,
            doc,
            _calc(
                f"Example: redeeming {inr(amt)} on day {day} costs {rate}% = {inr(load)}, so you "
                f"receive {inr(amt - load)}.",
                doc,
                explainer,
            ),
        )

    slabs = s["slabs"]
    if not slabs:
        return ExitLoad("no_load", None, None, doc, stamp_duty(Decimal("10000")))
    slab = slabs[0]
    window = slab["max_days"]
    rate = slab["rate_pct"]
    wtext = s.get("window_text")
    label = wtext or f"{window} days"
    free = s.get("free_units_pct")
    nav_after = EXAMPLE_NAV * (1 - pct(rate))
    if holding_days is not None and holding_days > window:
        text = (
            f"Example: inside {label}, {fmt_pct(rate.rstrip('0').rstrip('.'))} at NAV "
            f"{inr(EXAMPLE_NAV)} gives {inr(nav_after)} per unit; at {holding_days} days you "
            f"get the full {inr(EXAMPLE_NAV)}."
        )
        return ExitLoad("outside", None, window, doc, _calc(text, doc, explainer), wtext, free)
    rate_s = rate.rstrip("0").rstrip(".")
    if amount is not None:
        what = f"{inr(amount)} of units beyond the free {free}%" if free else inr(amount)
        text = (
            f"Example: redeeming {what} within {label} costs {rate_s}% = "
            f"{inr(amount * pct(rate))}, so you receive {inr(amount * (1 - pct(rate)))}."
        )
    else:
        units = f"on units beyond the free {free}% redeemed" if free else "if you redeem"
        text = (
            f"Example: a {rate_s}% exit load at NAV {inr(EXAMPLE_NAV)} means you get "
            f"{inr(nav_after)} per unit {units} within {label}."
        )
    status = "inside" if holding_days is not None else "unknown_period"
    return ExitLoad(status, rate_s, window, doc, _calc(text, doc, explainer), wtext, free)
