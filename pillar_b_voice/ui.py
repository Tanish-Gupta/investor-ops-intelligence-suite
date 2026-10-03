"""Book-a-call page (Pillar B): the theme-aware voice agent. The Weekly Pulse (M2) briefs the agent,
whose greeting names this week's top review theme; the call ends with a booking code and the
follow-ups (calendar hold + advisor email) go to Approvals."""

from __future__ import annotations

import hashlib

import streamlit as st

from dashboard.shell import APPROVALS
from dashboard.ui_kit import (
    card,
    card_head,
    esc,
    go_button,
    html_block,
    masthead,
    note,
    stamp,
    steps,
    tag,
)

from . import speech
from .agent import AgentTurn, S, VoiceSession

KEY = "voice_session"
MAX_UPLOAD_MB = 10


def _session() -> VoiceSession:
    s = st.session_state.get(KEY)
    if s is None:
        s = VoiceSession(pulse="latest")
        st.session_state[KEY] = s
        st.session_state["voice_turns"] = [("agent", s.start())]
    return s


def _new_call() -> None:
    old = st.session_state.get(KEY)
    if old is not None and not old.ended:
        old.end()
    st.session_state.pop(KEY, None)
    st.session_state.pop("voice_audio_digest", None)
    st.session_state.pop("voice_handoff", None)


def _say(text: str) -> None:
    s = _session()
    if s.ended:
        return
    turns = st.session_state["voice_turns"]
    turns.append(("caller", text))
    turn = s.handle(text)
    turns.append(("agent", turn))
    if turn.ended:
        _finish(s)


def _finish(s: VoiceSession) -> None:
    s.end()
    codes = [r.booking_code for r in s.results]
    if codes:
        st.session_state["focus_code"] = codes[-1]
        st.session_state["voice_handoff"] = codes


STAGES = ["Topic", "Time", "Slot", "Confirm", "Booked"]
_STAGE = {
    S.GREETING: 0, S.INTENT: 0, S.TOPIC: 0, S.LOOKUP: 0, S.TIME_PREF: 1, S.SLOT: 2,
    S.CONFIRM: 3, S.CANCEL_CONFIRM: 3, S.BOOKED: 5, S.PREPARE: 5, S.CANCELLED: 5,
    S.WAITLIST: 5, S.CLOSING: 0,
}  # fmt: skip


def _send_form() -> None:
    text = (st.session_state.get("voice_text") or "").strip()
    if text:
        _say(text)


def _reply_for(s: VoiceSession, option: str) -> str:
    """Slot chips carry the slot label; the agent expects the option number."""
    if s.state == S.SLOT:
        labels = [slot.label() for slot in s.offered]
        if option in labels:
            return str(labels.index(option) + 1)
    return option


def rebrief(upload) -> object:  # noqa: ANN001 - file-like CSV
    """Rebuild the Weekly Pulse from uploaded reviews. Raises ReviewInputError on bad input."""
    from pillar_m2_pulse.pulse import run_pulse
    from pillar_m2_pulse.reviews import ReviewInputError

    if getattr(upload, "size", 0) > MAX_UPLOAD_MB * 1024 * 1024:
        raise ReviewInputError(f"That file is over {MAX_UPLOAD_MB} MB. Upload a smaller export.")
    return run_pulse(upload)


def _upload() -> None:
    from pillar_m2_pulse.reviews import ReviewInputError

    with st.popover("Update from new reviews", icon=":material/upload_file:"):
        up = st.file_uploader(
            "App-store reviews export (CSV with date, rating and text columns)",
            type="csv",
            key="brief_upload",
        )
        if st.button("Update briefing", key="brief_apply", type="primary", disabled=up is None):
            try:
                with st.spinner("Reading the reviews…"):
                    p = rebrief(up)
            except ReviewInputError as exc:
                st.error(str(exc))
                return
            st.session_state["brief_msg"] = f"Briefing updated. Top theme: {p.top_theme}."
            _new_call()
            st.rerun()


def _brief() -> None:
    from pillar_m2_pulse.pulse import get_latest_pulse

    from .greeting import build_greeting

    p = get_latest_pulse()
    g = build_greeting(p)
    with card("brief", tone="sage"):
        card_head("This week's briefing", "From the review pulse", icon_name="pulse", tone="sage")
        if p is None or g.kind == "generic":
            why = "there is no recent review pulse" if g.reason != "no_top_theme" else (
                "no single theme stood out")  # fmt: skip
            note(f"The agent is using its standard greeting because {why}.")
        else:
            follow = (
                "and offers to book a call about it."
                if g.kind == "bookable"
                else "and points callers to in-app help, since it isn't an advisor topic."
            )
            html_block(
                '<div class="io-live"><b>' + esc(g.theme) + "</b><span>top theme in this week's "
                "reviews</span></div>"
                f'<p class="io-foot-cap">The top theme in this week\'s app reviews is '
                f"<b>{esc(g.theme)}</b>. The agent mentions it when the call opens {follow} "
                f"From review pulse {esc(g.pulse_id)}.</p>"
            )
        if msg := st.session_state.pop("brief_msg", None):
            st.success(msg)
        _upload()


def _ticket(s: VoiceSession) -> None:
    r = s.results[-1]
    action = {"BOOK": "Booked", "RESCHEDULE": "Rescheduled", "CANCEL": "Cancelled"}[r.action]
    html_block(
        '<div class="io-refblock"><div class="lbl">Booking code</div>'
        f'<div class="code">{esc(r.booking_code)}</div>'
        f'<div class="row">{esc(r.topic)}, {esc(r.slot_label)}</div>'
        f"{stamp(f'{action}, awaiting approval', 'pending')}</div>"
    )


def _handoff(s: VoiceSession) -> None:
    handoff = st.session_state.get("voice_handoff")
    if s.ended and handoff:
        note(
            f"The calendar hold and advisor email for {', '.join(handoff)} are waiting for "
            "sign-off in Approvals.",
            "sage",
            title="Sent for approval.",
        )
        go_button("Review in Approvals", APPROVALS, key="voice_to_approvals", primary=True,
                  icon=":material/approval:")  # fmt: skip
    elif s.results:
        html_block('<p class="io-foot-cap">End the call, or say "no, that\'s all", to send the '
                   "follow-ups for approval.</p>")  # fmt: skip
    elif s.ended:
        html_block('<p class="io-foot-cap">Call ended without a booking. Start a new call to '
                   "try again.</p>")  # fmt: skip


def _speak(turn: AgentTurn) -> None:
    if not speech.tts_ready():
        return
    try:
        st.audio(speech.synthesize(turn.speech or turn.text), format="audio/mp3", autoplay=True)
    except speech.SpeechUnavailable as e:
        st.caption(f"Spoken replies are unavailable: {e}")


def _mic() -> None:
    if not speech.stt_ready():
        return
    audio = st.audio_input("Speak to the agent", key="voice_mic")
    if audio is None:
        return
    data = audio.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    if st.session_state.get("voice_audio_digest") == digest:
        return  # already handled on a previous rerun
    st.session_state["voice_audio_digest"] = digest
    try:
        text = speech.transcribe(data, getattr(audio, "name", "call.wav") or "call.wav")
    except speech.SpeechUnavailable as e:
        st.warning(f"{e} Please type your reply instead.")
        return
    if text:
        _say(text)


def _transcript(s: VoiceSession) -> AgentTurn | None:
    turns = st.session_state.get("voice_turns", [])
    for who, item in turns:
        avatar = ":material/support_agent:" if who == "agent" else ":material/person:"
        with st.chat_message("assistant" if who == "agent" else "user", avatar=avatar):
            if who == "agent":
                st.markdown(item.text)
                if item.refused:
                    st.caption("Refused: facts only, never advice or personal data.")
            else:
                st.markdown(item)
    if s.ended:
        st.caption("Call ended.")
    return next((t for who, t in reversed(turns) if who == "agent"), None)


def render() -> None:
    masthead(
        "Book an advisor call",
        "Talk to the scheduling agent. It books a tentative slot and gives you a booking code. "
        "Don't share your phone, PAN or email here; an advisor collects contact details later "
        "through a secure link.",
        "Customer portal",
    )
    s = _session()
    left, right = st.columns([1.65, 1], gap="large")
    with left, card("call"):
        status = tag("Call ended", "muted") if s.ended else tag("On the line", "sage")
        card_head("Scheduling agent", "Speak or type. Facts only, no advice.",
                  icon_name="voice", tone="sage", end=status)  # fmt: skip
        with st.container(height=440, border=False):
            last = _transcript(s)
        if last is not None and last.options and not s.ended:
            with st.container(horizontal=True):
                for i, opt in enumerate(last.options):
                    st.button(opt, key=f"voice_opt_{len(st.session_state['voice_turns'])}_{i}",
                              on_click=_say, args=(_reply_for(s, opt),))  # fmt: skip
        with st.form("voice_form", clear_on_submit=True, border=False):
            a, b = st.columns([5, 1], vertical_alignment="bottom")
            a.text_input(
                "Your reply",
                key="voice_text",
                placeholder="e.g. Book a nominee call for Monday morning",
                disabled=s.ended,
                label_visibility="collapsed",
            )
            b.form_submit_button("Send", disabled=s.ended, on_click=_send_form, type="primary",
                                 width="stretch")  # fmt: skip
        _mic()
        if last is not None:
            _speak(last)

    with right:
        _brief()
        with card("booking"):
            card_head("Your booking", "Tentative until an advisor approves",
                      icon_name="calendar")  # fmt: skip
            steps(STAGES, len(STAGES) if s.results else _STAGE.get(s.state, 0))
            if s.results:
                _ticket(s)
            _handoff(s)
            with st.container(horizontal=True):
                if st.button("New call", key="voice_new", icon=":material/call:"):
                    _new_call()
                    st.rerun()
                if st.button("End call", key="voice_end", disabled=s.ended,
                             icon=":material/call_end:"):  # fmt: skip
                    _finish(s)
                    st.rerun()
