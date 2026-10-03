"""The 6 fixed booking topics: synonyms (ported from M3's TopicMapper) and prep checklists."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Topic:
    name: str
    short: str  # spoken list form ("KYC", "SIPs", …)
    synonyms: tuple[str, ...]
    checklist: tuple[str, ...]


TOPICS: tuple[Topic, ...] = (
    Topic(
        "KYC/Onboarding",
        "KYC",
        (
            "kyc", "ekyc", "e-kyc", "know your customer", "onboarding", "onboard",
            "open an account", "open account", "account opening", "new account", "sign up",
            "signup", "register", "registration", "verification", "verify my", "ckyc",
            "video kyc", "ipv", "in-person verification", "pan card", "aadhaar", "aadhar",
        ),
        (
            "Keep your PAN card and address proof handy (don't share numbers on this call)",
            "Have the app open on your registered device",
            "Note any error message you saw during KYC",
        ),
    ),
    Topic(
        "SIP/Mandates",
        "SIPs",
        (
            "sip", "sips", "systematic investment plan", "mandate", "mandates", "e-mandate",
            "emandate", "nach", "autopay", "auto pay", "auto-debit", "auto debit", "autodebit",
            "standing instruction", "monthly investment", "step up", "step-up", "pause sip",
            "debit date", "instalment", "installment",
        ),
        (
            "Note the scheme name and SIP date",
            "Check your bank app for the mandate status",
            "List the SIPs you want to pause, change or stop",
        ),
    ),
    Topic(
        "Statements/Tax Docs",
        "statements",
        (
            "statement", "statements", "account statement", "cas",
            "consolidated account statement", "capital gains", "capital gain", "tax", "taxes",
            "tax docs", "tax documents", "tax document", "tax certificate", "tax statement",
            "elss", "form 16", "26as", "itr", "tax return", "contract note", "p&l",
            "holding statement", "transaction history", "fee", "fees", "charges", "charged",
            "exit load", "stamp duty", "expense ratio",
        ),
        (
            "Know the financial year you need documents for",
            "Download your latest CAS from the app if you can",
            "List the transactions or charges you want explained",
        ),
    ),
    Topic(
        "Withdrawals & Timelines",
        "withdrawals",
        (
            "withdraw", "withdrawal", "withdrawals", "withdrawing", "redeem", "redemption",
            "redemptions", "redeeming", "payout", "payouts", "take out my money",
            "get my money", "money back", "credited", "credit to my bank", "timeline",
            "timelines", "how long does it take", "when will i get", "settlement", "lock-in",
            "lock in",
        ),
        (
            "Note the redemption date and amount shown in the app",
            "Keep the order status screen ready",
            "Check whether your bank account is verified in the app",
        ),
    ),
    Topic(
        "Nominee Updates",
        "nominee updates",
        (
            "nominee", "nominees", "nomination", "add a nominee", "change nominee",
            "update nominee", "opt out of nomination", "nominee update", "nominee updates",
        ),
        (
            "Decide who you want to nominate and the share for each nominee",
            "Keep the nominee's details ready to enter in the app yourself",
            "Note any error you saw on the nomination screen",
        ),
    ),
    Topic(
        "Account & App Access",
        "account access",
        (
            "login", "log in", "logging in", "sign in", "signin", "otp", "password", "pin",
            "mpin", "locked out", "account locked", "blocked", "can't access", "cannot access",
            "access my account", "app access", "2fa", "two factor", "change mobile",
            "mobile number change", "update email", "change email", "email change",
            "bank account change", "change bank", "change my bank", "update bank",
            "bank details", "change address", "address change", "update my details",
            "account change", "account changes",
        ),
        (
            "Update the app to the latest version",
            "Note the exact error message and when it started",
            "Have access to your registered email for verification links",
        ),
    ),
)  # fmt: skip

TOPIC_NAMES: tuple[str, ...] = tuple(t.name for t in TOPICS)
_BY_NAME = {t.name.lower(): t for t in TOPICS}

_PATTERNS = {
    t.name: [
        re.compile(r"(?<![a-z0-9])" + re.escape(s).replace(r"\ ", r"\s+") + r"(?![a-z0-9])")
        for s in sorted(t.synonyms, key=len, reverse=True)
    ]
    for t in TOPICS
}
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
             "last": 6, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}  # fmt: skip
_PICK_RE = re.compile(
    r"^(?:(?:option|number|no|topic|choice)\s*)?([1-6]|one|two|three|four|five|six)$"
    r"|^(?:the\s+)?(first|second|third|fourth|fifth|sixth|last)(?:\s+(?:one|option|topic))?$"
)


def get(name: str | None) -> Topic | None:
    return _BY_NAME.get((name or "").lower())


def spoken_list() -> str:
    shorts = [t.short for t in TOPICS]
    return ", ".join(shorts[:-1]) + " or " + shorts[-1]


def numbered_list() -> str:
    return "; ".join(f"{i}. {t.name}" for i, t in enumerate(TOPICS, 1))


def _hits(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, patterns in _PATTERNS.items():
        taken: list[tuple[int, int]] = []
        for p in patterns:
            for m in p.finditer(text):
                if not any(a < m.end() and m.start() < b for a, b in taken):
                    taken.append((m.start(), m.end()))
        if taken:
            counts[name] = len(taken)
    return counts


def match_topic(text: str) -> tuple[str | None, list[str]]:
    """(topic, candidates): a clear winner, a tie (None, tied) or nothing (None, [])."""
    t = text.lower().strip()
    if t in _BY_NAME:
        return _BY_NAME[t].name, [_BY_NAME[t].name]
    counts = _hits(t)
    if not counts:
        return None, []
    best = max(counts.values())
    winners = [n for n in TOPIC_NAMES if counts.get(n) == best]
    return (winners[0], winners) if len(winners) == 1 else (None, winners)


def pick_from_list(text: str, options: list[str] | None = None) -> str | None:
    """'2', 'option 3', 'the first one' → topic by position in `options` (default: all 6)."""
    opts = options or list(TOPIC_NAMES)
    m = _PICK_RE.match(text.strip().lower())
    if m is None:
        return None
    token = m.group(1) or m.group(2)
    n = len(opts) if token == "last" else int(token) if token.isdigit() else _ORDINALS[token]
    return opts[n - 1] if 1 <= n <= len(opts) else None
