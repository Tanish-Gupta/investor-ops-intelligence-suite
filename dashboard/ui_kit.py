"""The suite's UI kit: small HTML/Streamlit helpers over the Linen & Caramel world (CSS, icons
and the direction contract live in `dashboard.theme`; see DESIGN.md). All dynamic text goes
through `esc` before it is placed in HTML."""

from __future__ import annotations

import html
from collections.abc import Sequence
from typing import Literal

import streamlit as st

from dashboard.theme import ICONS

Tone = Literal["brand", "sage", "iris", "ink", "muted", "red", "amber"]


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value))


def today() -> str:
    from core.state import now  # IST clock (frozen in tests)

    return f"{now():%d %b %Y}"


def inject_css() -> None:
    from dashboard.theme import CSS, DIRECTION

    st.html(f"{DIRECTION}<style>{CSS}</style>")


def html_block(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def icon(name: str, tone: Tone = "brand", *, small: bool = False) -> str:
    """A tinted icon tile (inline stroke SVG drawn for this suite)."""
    size = " sm" if small else ""
    return (
        f'<span class="io-tile {tone}{size}" aria-hidden="true"><svg viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
        f'stroke-linejoin="round">{ICONS[name]}</svg></span>'
    )


def card(name: str, *, tone: Literal["", "brand", "sage", "iris", "link"] = "", **kw):
    """A raised sheet of card stock: a keyed st.container styled by the `io-card-*` CSS rule."""
    return st.container(key=f"io-card-{tone}-{name}" if tone else f"io-card-{name}", **kw)


def card_head(
    title: str, sub: str = "", *, icon_name: str | None = None, tone: Tone = "brand", end: str = ""
) -> None:
    tile = icon(icon_name, tone, small=True) if icon_name else ""
    p = f"<p>{esc(sub)}</p>" if sub else ""
    tail = f'<span class="end">{end}</span>' if end else ""
    html_block(f'<div class="io-cardhead">{tile}<div><h3>{esc(title)}</h3>{p}</div>{tail}</div>')


def masthead(title: str, subtitle: str, portal: str = "") -> None:
    """Page title in the serif display face, one line of purpose, and which portal you are in."""
    meta = [tag(portal, "brand")] if portal else []
    meta += [tag(today(), "muted"), tag("Facts only. No investment advice.", "muted")]
    html_block(
        f'<header class="io-mast"><h1 class="io-title">{esc(title)}</h1>'
        f'<p class="io-sub">{esc(subtitle)}</p><div class="io-meta">{"".join(meta)}</div></header>'
    )


def heading(text: str) -> None:
    html_block(f'<h2 class="io-h">{esc(text)}</h2>')


def tag(text: str, tone: Tone = "muted") -> str:
    return f'<span class="io-tag {tone}">{esc(text)}</span>'


def note(body: str, tone: Tone | None = None, *, title: str | None = None) -> None:
    head = f"<b>{esc(title)}</b> " if title else ""
    html_block(f'<div class="io-note {tone or ""}">{head}{esc(body)}</div>')


def stamp(text: str, kind: Literal["approved", "pending", "red", "ink"], sub: str = "") -> str:
    small = f"<small>{esc(sub)}</small>" if sub else ""
    return f'<span class="io-stamp {kind}">{esc(text)}{small}</span>'


def empty_state(
    title: str, body: str, *, cta: str | None = None, page: str | None = None, key: str = ""
) -> None:
    html_block(f'<div class="io-empty"><h3>{esc(title)}</h3><p>{esc(body)}</p></div>')
    if cta and page:
        go_button(cta, page, key=key or f"empty_{page}", primary=True)


def go_button(label: str, page: str, *, key: str, primary: bool = False, icon: str | None = None):
    """Navigate to another page in the suite (a `views/*.py` path)."""
    if st.button(label, key=key, type="primary" if primary else "secondary", icon=icon):
        st.switch_page(page)


def steps(labels: Sequence[str], current: int) -> None:
    """Numbered progress line; `current` = index of the active step (len = all done)."""
    parts = []
    for i, label in enumerate(labels):
        cls = "done" if i < current else "now" if i == current else ""
        cur = ' aria-current="step"' if i == current else ""
        bar = '<span class="bar"></span>' if i < len(labels) - 1 else ""
        parts.append(f'<li class="{cls}"{cur}><span class="n">{i + 1}</span>{esc(label)}{bar}</li>')
    html_block(f'<ol class="io-steps" aria-label="Booking progress">{"".join(parts)}</ol>')


def kv(rows: Sequence[tuple[str, object]]) -> str:
    body = "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in rows)
    return f'<dl class="io-kv">{body}</dl>'


def bars(rows: Sequence[tuple[str, float, str]], *, top: str | None = None, tone: str = "") -> str:
    """Horizontal share bars: (label, fraction 0-1, value text); `top` is highlighted."""
    items = []
    for label, frac, val in rows:
        hi = " top" if label == top else ""
        width = max(2.0, min(100.0, frac * 100))
        items.append(
            f'<li><span class="lbl{hi}">{esc(label)}</span><span class="val">{esc(val)}</span>'
            f'<span class="track"><span class="fill{hi}" style="width:{width:.1f}%"></span>'
            "</span></li>"
        )
    return f'<ul class="io-bars {tone}">{"".join(items)}</ul>'


def footer(text: str) -> None:
    html_block(f'<div class="io-foot">{esc(text)}</div>')


# --- Legacy helpers: kept only so the retired ops modules (dashboard.overview, evals.ui; no longer
# in navigation) still import cleanly. New UI uses the helpers above.
_LEGACY_TONE: dict[str, Tone] = {
    "ok": "sage", "brand": "brand", "info": "iris", "warn": "amber", "bad": "red",
    "neutral": "muted",
}  # fmt: skip


def pill(text: str, tone: str = "neutral") -> str:
    return tag(text, _LEGACY_TONE.get(tone, "muted"))


def callout(title: str, body: str, tone: str = "ok") -> None:
    note(body, _LEGACY_TONE.get(tone, "muted"), title=title)


def page_header(_eyebrow: str, title: str, subtitle: str | None = None) -> None:
    masthead(title, subtitle or "")


def section(title: str) -> None:
    heading(title)
