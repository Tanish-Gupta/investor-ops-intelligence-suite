"""Linen & Caramel: the suite's visual world. A warm cream desk where every working surface is a
raised card: soft layered shadows, generous radii, a bold serif voice for headings and caramel pill
buttons for the one action that matters. `ui_kit` injects this CSS and builds on these icons."""

from __future__ import annotations

DIRECTION = """<!--
THESIS: Investor Ops is a warm, tactile desk: three working surfaces (answers, calls, approvals)
lifted off a cream linen canvas, each carrying live numbers rather than marketing copy.
OWN-WORLD: private-banking stationery: linen paper, letterpress serif, caramel leather, layered
card stock that casts real shadows; booking codes set like engraved reference numbers.
STORY: home (choose a portal) -> customer: ask (six cited points) -> book a call (the agent opens
with this week's top review theme) -> admin: review pulse (CSV to pulse) -> approvals (stamp the
hold and the advisor email with Market Context; the code lands in the notes register).
FIRST VIEWPORT: one serif headline, two pill CTAs (Customer portal, Admin portal), three raised
pillar cards with live data, the demo flow strip beneath.
FORM: operate mode with a persuade landing; system sans body, Iowan/Charter serif display;
canvas #F6F1EA, ink #2B2722, caramel #9A5B2C, sage #4A7354, iris #535FA0; radius 22px cards,
pill buttons; one authored motion moment: the approval stamp.
-->"""

SERIF = '"Iowan Old Style", "Palatino Linotype", Charter, "Bitstream Charter", Georgia, serif'

CSS = (
    """
:root {
  --io-canvas: #F6F1EA; --io-surface: #FFFDFA; --io-sunk: #F8F3EC;
  --io-ink: #2B2722; --io-muted: #6B6158; --io-line: rgba(74, 52, 30, .12);
  --io-faint: rgba(74, 52, 30, .07);
  --io-brand: #9A5B2C; --io-brand-hi: #A8693A; --io-brand-lo: #8A4F24; --io-brand-wash: #F4E4D3;
  --io-sage: #4A7354; --io-sage-wash: #E2ECE1; --io-iris: #535FA0; --io-iris-wash: #E5E7F4;
  --io-red: #A3341F; --io-red-wash: #F9E7E2; --io-amber: #85570A; --io-amber-wash: #FAF0DC;
  --io-shadow: 0 1px 2px rgba(60, 40, 20, .06), 0 8px 24px -8px rgba(60, 40, 20, .14),
    0 24px 48px -16px rgba(60, 40, 20, .12);
  --io-shadow-hi: 0 2px 4px rgba(60, 40, 20, .07), 0 14px 32px -8px rgba(60, 40, 20, .18),
    0 36px 64px -18px rgba(60, 40, 20, .16);
  --io-shadow-btn: 0 1px 1px rgba(60, 30, 10, .18), 0 6px 14px -4px rgba(120, 70, 30, .38),
    inset 0 1px 0 rgba(255, 255, 255, .22);
  --io-serif: SERIF_STACK;
  --io-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --io-ease: cubic-bezier(.16, 1, .3, 1);
}

/* Canvas: linen with a soft light falling from the top. */
[data-testid="stAppViewContainer"] {
  background: radial-gradient(1100px 520px at 50% -8%, #FFFBF5 0%, rgba(255, 251, 245, 0) 70%),
    radial-gradient(900px 600px at 100% 110%, #EFE4D6 0%, rgba(239, 228, 214, 0) 70%),
    var(--io-canvas);
}
[data-testid="stHeader"] { background: rgba(246, 241, 234, .82);
  backdrop-filter: saturate(1.2) blur(10px); -webkit-backdrop-filter: saturate(1.2) blur(10px);
  box-shadow: 0 1px 0 var(--io-faint); }
[data-testid="stMainBlockContainer"] { padding-top: 5.2rem; padding-bottom: 3rem;
  max-width: 1180px; }
[data-testid="stTopNavLink"] { border-radius: 999px; }
[data-testid="stHeaderActionElements"] { display: none; }

/* Type */
h1, h2, h3, .io-title, .io-hero h1 { font-family: var(--io-serif); }
.io-title { font-size: clamp(2rem, 3.2vw, 2.7rem); line-height: 1.08; font-weight: 700;
  letter-spacing: -.02em; color: var(--io-ink); margin: 0; padding: 0; text-wrap: balance; }
.io-sub { color: var(--io-muted); font-size: 1.04rem; line-height: 1.6; max-width: 66ch;
  margin: .6rem 0 .8rem; }
.io-mast { margin: 0 0 1.6rem; }
.io-meta { display: flex; flex-wrap: wrap; gap: .4rem; }
.io-h { font-family: var(--io-serif); font-size: 1.3rem; font-weight: 700; letter-spacing: -.01em;
  color: var(--io-ink); margin: .2rem 0 .55rem; padding: 0; line-height: 1.25; }
.io-body { line-height: 1.6; max-width: 70ch; color: var(--io-ink); }
.io-foot-cap { color: var(--io-muted); font-size: .85rem; line-height: 1.5; margin: .3rem 0 .6rem; }
.io-mono { font-family: var(--io-mono); font-size: .85rem; }

/* Raised cards: every st.container(key="io-card-*") is a sheet of card stock. */
[class*="st-key-io-card-"] { background: var(--io-surface); border: 1px solid var(--io-line);
  border-radius: 22px; padding: 1.25rem 1.35rem 1.2rem; box-shadow: var(--io-shadow);
  position: relative; }
[class*="st-key-io-card-"] [class*="st-key-io-card-"] { background: var(--io-sunk);
  border-radius: 16px; box-shadow: 0 1px 2px rgba(60, 40, 20, .05); }
[class*="st-key-io-card-sage"] { background: linear-gradient(180deg, #F1F6F0, var(--io-surface)); }
[class*="st-key-io-card-iris"] { background: linear-gradient(180deg, #F1F2FA, var(--io-surface)); }
[class*="st-key-io-card-brand"] { background: linear-gradient(180deg, #FBF1E6, var(--io-surface)); }
[class*="st-key-io-card-link"] { transition: transform 260ms var(--io-ease),
  box-shadow 260ms var(--io-ease); }
[class*="st-key-io-card-link"]:hover { transform: translateY(-3px);
  box-shadow: var(--io-shadow-hi); }
[class*="st-key-io-card-link"] [data-testid="stElementContainer"],
[class*="st-key-io-card-link"] [data-testid="stPageLink"] { position: static; }
[class*="st-key-io-card-link"] [data-testid="stPageLink-NavLink"]::after { content: "";
  position: absolute; inset: 0; border-radius: 22px; }
[class*="st-key-io-card-link"] [data-testid="stPageLink-NavLink"] { padding-left: 0; }
[class*="st-key-io-card-link"] [data-testid="stPageLink-NavLink"] p { color: var(--io-brand-lo);
  font-weight: 650; }
@media (prefers-reduced-motion: reduce) {
  [class*="st-key-io-card-link"], [class*="st-key-io-card-link"]:hover { transition: none;
    transform: none; } }

/* Buttons: caramel leather pills for the primary action, white card-stock pills otherwise. */
button[data-testid^="stBaseButton-primary"] { border-radius: 999px; border: 0;
  background: linear-gradient(180deg, var(--io-brand-hi), var(--io-brand-lo));
  box-shadow: var(--io-shadow-btn); color: #FFF; font-weight: 650; padding-inline: 1.15rem;
  transition: transform 160ms var(--io-ease), filter 160ms var(--io-ease); }
button[data-testid^="stBaseButton-primary"]:hover { filter: brightness(1.06); color: #FFF;
  transform: translateY(-1px); }
button[data-testid^="stBaseButton-primary"]:active { transform: none; filter: none; }
button[data-testid^="stBaseButton-secondary"], [data-testid="stPopoverButton"] {
  border-radius: 999px; background: var(--io-surface); border: 1px solid var(--io-line);
  box-shadow: 0 1px 2px rgba(60, 40, 20, .06), 0 4px 10px -4px rgba(60, 40, 20, .12);
  color: var(--io-ink); font-weight: 600; }
button[data-testid^="stBaseButton-secondary"]:hover, [data-testid="stPopoverButton"]:hover {
  border-color: rgba(154, 91, 44, .45); color: var(--io-brand-lo); }
button[data-testid="stBaseButton-tertiary"] { border-radius: 999px; }
button:focus-visible, a:focus-visible { outline: 2px solid var(--io-brand); outline-offset: 2px; }
[class*="st-key-io-cta"] button { min-height: 3.1rem; padding-inline: 1.7rem; }
[class*="st-key-io-cta"] button p { font-size: 1rem; }

/* Inputs sit sunk into the card. */
[data-testid="stTextInputRootElement"], [data-baseweb="textarea"] { border-radius: 14px;
  background: var(--io-surface); box-shadow: inset 0 1px 2px rgba(60, 40, 20, .06); }
[data-testid="stFileUploaderDropzone"] { border-radius: 16px; background: var(--io-sunk);
  border: 1.5px dashed rgba(154, 91, 44, .35); }
[data-testid="stExpander"] details { border-radius: 16px; background: var(--io-surface);
  border-color: var(--io-line); }
[data-testid="stChatMessage"] { background: transparent; padding: .3rem 0; }
[data-testid="stChatMessageContent"] { background: var(--io-sunk);
  border: 1px solid var(--io-faint); border-radius: 4px 16px 16px 16px; padding: .6rem .95rem; }
[data-testid="stChatMessageAvatarUser"] + [data-testid="stChatMessageContent"] {
  background: var(--io-brand-wash); border-color: transparent; }

/* Tags and notes */
.io-tag { display: inline-flex; align-items: center; gap: .3rem; padding: .16rem .62rem;
  border-radius: 999px; font-size: .8rem; font-weight: 650; line-height: 1.5;
  white-space: nowrap; vertical-align: middle; background: var(--io-sunk); color: var(--io-muted);
  border: 1px solid var(--io-faint); }
.io-tag.brand { background: var(--io-brand-wash); color: var(--io-brand-lo);
  border-color: transparent; }
.io-tag.sage { background: var(--io-sage-wash); color: #3A5E44; border-color: transparent; }
.io-tag.iris { background: var(--io-iris-wash); color: #444F8C; border-color: transparent; }
.io-tag.ink { background: var(--io-ink); color: #FBF7F1; border-color: transparent; }
.io-tag.red { background: var(--io-red-wash); color: var(--io-red); border-color: transparent; }
.io-tag.amber { background: var(--io-amber-wash); color: var(--io-amber);
  border-color: transparent; }
.io-note { border-radius: 16px; padding: .8rem 1rem; margin: .4rem 0 .9rem; line-height: 1.55;
  color: var(--io-ink); background: var(--io-sunk); border: 1px solid var(--io-faint); }
.io-note b { font-weight: 700; }
.io-note.brand { background: var(--io-brand-wash); border-color: transparent; }
.io-note.sage { background: var(--io-sage-wash); border-color: transparent; }
.io-note.iris { background: var(--io-iris-wash); border-color: transparent; }
.io-note.red { background: var(--io-red-wash); border-color: transparent; }
.io-note.amber { background: var(--io-amber-wash); border-color: transparent; }
.io-empty { border-radius: 22px; padding: 1.5rem 1.6rem; margin-bottom: .9rem;
  background: var(--io-surface); border: 1px solid var(--io-line); box-shadow: var(--io-shadow); }
.io-empty h3 { margin: 0 0 .35rem; font-size: 1.3rem; font-weight: 700; padding: 0; }
.io-empty p { margin: 0; color: var(--io-muted); max-width: 62ch; line-height: 1.55; }

/* Icon tiles */
.io-tile { width: 3rem; height: 3rem; border-radius: 14px; display: inline-flex;
  align-items: center; justify-content: center; flex: none;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .7), 0 1px 2px rgba(60, 40, 20, .08); }
.io-tile svg { width: 1.45rem; height: 1.45rem; }
.io-tile.brand { background: var(--io-brand-wash); color: var(--io-brand); }
.io-tile.sage { background: var(--io-sage-wash); color: var(--io-sage); }
.io-tile.iris { background: var(--io-iris-wash); color: var(--io-iris); }
.io-tile.sm { width: 2.3rem; height: 2.3rem; border-radius: 14px; }
.io-tile.sm svg { width: 1.15rem; height: 1.15rem; }
.io-cardhead { display: flex; align-items: center; gap: .8rem; margin-bottom: .75rem; }
.io-cardhead h3 { font-size: 1.15rem; font-weight: 700; margin: 0; padding: 0; line-height: 1.2;
  letter-spacing: -.01em; color: var(--io-ink); }
.io-cardhead p { margin: .15rem 0 0; font-size: .85rem; color: var(--io-muted); }
.io-cardhead .end { margin-left: auto; }

/* Landing */
.io-hero { text-align: center; padding: 1.6rem 0 1.2rem; }
.io-hero h1 { font-size: clamp(2.6rem, 5.6vw, 4.5rem); line-height: 1.02; font-weight: 700;
  letter-spacing: -.03em; color: var(--io-ink); margin: 0 auto; padding: 0; max-width: 16ch;
  text-wrap: balance; }
.io-hero p { font-size: 1.15rem; line-height: 1.6; color: var(--io-muted); max-width: 58ch;
  margin: 1.1rem auto 0; }
.io-pillar h3 { font-size: 1.3rem; font-weight: 700; letter-spacing: -.015em;
  margin: 1rem 0 .35rem; padding: 0; color: var(--io-ink); }
.io-pillar p { color: var(--io-muted); line-height: 1.55; margin: 0 0 .9rem; font-size: .95rem; }
.io-live { display: flex; align-items: baseline; flex-wrap: wrap; gap: .2rem .5rem;
  padding: .7rem .85rem; border-radius: 14px; background: var(--io-sunk);
  border: 1px solid var(--io-faint); margin-bottom: .3rem; }
.io-live b { font-family: var(--io-serif); font-size: 1.3rem; font-weight: 700;
  color: var(--io-ink); font-variant-numeric: tabular-nums; line-height: 1.15; }
.io-live span { font-size: .85rem; color: var(--io-muted); line-height: 1.35; }
.io-flow { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0;
  background: var(--io-surface); border: 1px solid var(--io-line); border-radius: 22px;
  box-shadow: var(--io-shadow); margin: 1.6rem 0 .4rem; list-style: none; padding: 0;
  overflow: hidden; }
.io-flow li { padding: 1.05rem 1.2rem; display: flex; gap: .75rem; align-items: flex-start;
  border-left: 1px solid var(--io-faint); margin: 0; }
.io-flow li:first-child { border-left: 0; }
.io-flow .n { flex: none; width: 1.75rem; height: 1.75rem; border-radius: 50%;
  background: var(--io-brand-wash); color: var(--io-brand-lo); font-weight: 700; font-size: .8rem;
  display: inline-flex; align-items: center; justify-content: center; }
.io-flow b { display: block; font-size: .95rem; color: var(--io-ink); line-height: 1.3; }
.io-flow span.d { font-size: .85rem; color: var(--io-muted); line-height: 1.45; }
@media (max-width: 860px) { .io-flow { grid-template-columns: 1fr 1fr; }
  .io-flow li:nth-child(3) { border-left: 0; }
  .io-flow li:nth-child(n+3) { border-top: 1px solid var(--io-faint); } }
@media (max-width: 520px) { .io-flow { grid-template-columns: 1fr; }
  .io-flow li { border-left: 0; } .io-flow li + li { border-top: 1px solid var(--io-faint); } }

/* Answer sheet: six numbered points, each footnoted to its source. */
.io-circ-head { display: flex; flex-wrap: wrap; align-items: center; gap: .4rem; }
.io-circ-head .ref { font-size: .8rem; color: var(--io-muted); font-variant-numeric: tabular-nums;
  margin-right: .2rem; }
.io-subject { font-family: var(--io-serif); font-size: 1.3rem; font-weight: 700;
  color: var(--io-ink); line-height: 1.3; letter-spacing: -.01em; margin: .75rem 0 1rem;
  max-width: 60ch; }
.io-paras { list-style: none; counter-reset: para; margin: 0; padding: 0; max-width: 72ch; }
.io-paras li { counter-increment: para; position: relative; padding-left: 2.5rem;
  margin: 0 0 .8rem; line-height: 1.62; color: var(--io-ink); }
.io-paras li::before { content: counter(para); position: absolute; left: 0; top: .05rem;
  width: 1.65rem; height: 1.65rem; border-radius: 50%; background: var(--io-brand-wash);
  color: var(--io-brand-lo); font-size: .8rem; font-weight: 700; display: flex;
  align-items: center; justify-content: center; font-variant-numeric: tabular-nums; }
.io-fn { font-size: .72rem; font-weight: 700; line-height: 0; margin-left: .15rem; }
.io-fn a { color: var(--io-brand-lo) !important; text-decoration: none;
  background: var(--io-brand-wash); border-radius: 999px; padding: .05rem .32rem;
  margin-right: .12rem; }
.io-fn a:hover, .io-fn a:focus-visible { text-decoration: underline; }
.io-notes { margin-top: 1.1rem; padding-top: .9rem; border-top: 1px solid var(--io-faint);
  max-width: 72ch; }
.io-notes ol { margin: 0; padding: 0; list-style: none; font-size: .85rem; }
.io-notes li { display: grid; grid-template-columns: 1.6rem 1fr; gap: .1rem .3rem;
  margin-bottom: .35rem; color: var(--io-muted); line-height: 1.45; }
.io-notes li sup { font-weight: 700; color: var(--io-brand-lo); font-size: .72rem; }
.io-notes a { color: var(--io-ink) !important; }

/* Library: what Unified Search can answer. */
.io-lib { list-style: none; margin: 0 0 .4rem; padding: 0; }
.io-lib li { display: flex; justify-content: space-between; align-items: baseline; gap: .8rem;
  padding: .5rem 0; margin: 0; border-bottom: 1px solid var(--io-faint); font-size: .95rem;
  color: var(--io-ink); }
.io-lib li:last-child { border-bottom: 0; }
.io-lib-scroll { max-height: 19rem; overflow-y: auto; margin: 0 0 .5rem; padding-right: .3rem;
  overscroll-behavior: contain; scrollbar-width: thin; }
.io-lib-scroll:focus-visible { outline: 2px solid var(--io-brand); outline-offset: 2px; }
.io-lib-amc { position: sticky; top: 0; z-index: 1; margin: 0; padding: .45rem 0 .3rem;
  background: var(--io-surface); font-size: .72rem; font-weight: 700; letter-spacing: .08em;
  text-transform: uppercase; color: var(--io-muted); border-bottom: 1px solid var(--io-faint); }
.io-lib-amc span { font-variant-numeric: tabular-nums; color: var(--io-brand); }
.io-lib li span { color: var(--io-muted); font-size: .8rem; white-space: nowrap; }
.io-chips { display: flex; flex-wrap: wrap; gap: .35rem; margin: .3rem 0 .5rem; }

/* Stamps: approval is the one authored motion moment. */
.io-stamp { display: inline-flex; flex-direction: column; align-items: center;
  border: 3px double currentColor; border-radius: 8px; padding: .2rem .7rem .25rem;
  font-weight: 750; letter-spacing: .12em; text-transform: uppercase; font-size: .8rem;
  line-height: 1.25; color: var(--io-muted); white-space: nowrap; background: var(--io-surface); }
.io-stamp small { font-size: .72rem; font-weight: 600; letter-spacing: .04em;
  text-transform: none; }
.io-stamp.pending { border-style: dashed; border-width: 1.5px; color: var(--io-amber); }
.io-stamp.approved { color: var(--io-sage); transform: rotate(-3deg);
  animation: io-stamp-in 280ms var(--io-ease) both; }
.io-stamp.red { color: var(--io-red); transform: rotate(-3deg); }
.io-stamp.ink { color: var(--io-ink); }
@keyframes io-stamp-in { from { opacity: 0; transform: rotate(-3deg) scale(1.35); }
  to { opacity: 1; transform: rotate(-3deg) scale(1); } }
@media (prefers-reduced-motion: reduce) { .io-stamp.approved { animation: none; } }

/* Annexures: the follow-ups attached to a booking. */
.io-annex-head { display: flex; align-items: center; justify-content: space-between; gap: 1rem;
  margin-bottom: .7rem; }
.io-annex-head h3 { font-size: 1.15rem; font-weight: 700; margin: 0; padding: 0;
  color: var(--io-ink); }
.io-annex-head h3 span { display: block; font-family: system-ui, sans-serif; font-size: .8rem;
  color: var(--io-muted); font-weight: 500; margin-top: .1rem; }
.io-kv { display: grid; grid-template-columns: max-content 1fr; gap: .35rem 1.1rem;
  font-size: .9rem; margin: 0 0 .5rem; }
.io-kv dt { color: var(--io-muted); }
.io-kv dd { margin: 0; color: var(--io-ink); font-variant-numeric: tabular-nums; }
.io-mail { border-radius: 16px; padding: 1rem 1.1rem; font-size: .9rem; line-height: 1.6;
  color: var(--io-ink); background: var(--io-surface); border: 1px solid var(--io-line);
  box-shadow: 0 1px 2px rgba(60, 40, 20, .05); margin-bottom: .5rem; }
.io-mail .io-kv { font-size: .85rem; padding-bottom: .7rem; margin-bottom: .75rem;
  border-bottom: 1px solid var(--io-faint); }
.io-mail .text { white-space: pre-wrap; }
.io-mail mark { background: var(--io-iris-wash); color: inherit; padding: .1rem .15rem;
  border-radius: 4px; box-shadow: inset 0 -2px 0 rgba(83, 95, 160, .45); }

/* Reference block: the booking code, set like an engraved reference number. */
.io-refblock { border-radius: 16px; padding: .95rem 1.1rem 1rem; margin: .3rem 0 .9rem;
  background: linear-gradient(180deg, #FBF1E6, #F6E7D6); border: 1px solid rgba(154, 91, 44, .18);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .7); }
.io-refblock .lbl { font-size: .8rem; color: var(--io-brand-lo); font-weight: 600; }
.io-refblock .code { font-family: var(--io-mono); font-size: 1.75rem; font-weight: 700;
  letter-spacing: .06em; color: var(--io-ink); margin: .1rem 0; }
.io-refblock .row { color: var(--io-ink); margin-bottom: .6rem; }

/* Register: the pre-booking notes doc, one line per approved booking. */
.io-register { width: 100%; border-collapse: collapse; font-size: .9rem;
  font-variant-numeric: tabular-nums; }
.io-register th { text-align: left; font-weight: 600; color: var(--io-muted); font-size: .8rem;
  border-bottom: 1px solid var(--io-line); padding: .45rem .6rem .45rem 0; }
.io-register td { border-bottom: 1px solid var(--io-faint); padding: .55rem .6rem .55rem 0;
  color: var(--io-ink); vertical-align: top; }
.io-register td.code { font-family: var(--io-mono); font-weight: 700; color: var(--io-brand-lo); }
.io-register tr:last-child td { border-bottom: 0; }

.io-steps { display: flex; flex-wrap: wrap; gap: .4rem .45rem; margin: .2rem 0 1rem;
  padding: 0; list-style: none; font-size: .85rem; color: var(--io-muted); }
.io-steps li { display: flex; align-items: center; gap: .35rem; margin: 0; }
.io-steps .n { width: 1.45rem; height: 1.45rem; border-radius: 50%; background: var(--io-sunk);
  border: 1px solid var(--io-line); display: inline-flex; align-items: center;
  justify-content: center; font-size: .72rem; font-weight: 700;
  font-variant-numeric: tabular-nums; }
.io-steps li.done .n { background: var(--io-sage); border-color: var(--io-sage); color: #fff; }
.io-steps li.now { color: var(--io-ink); font-weight: 650; }
.io-steps li.now .n { background: var(--io-brand-wash); border: 2px solid var(--io-brand);
  color: var(--io-brand-lo); }
.io-steps .bar { width: .9rem; border-top: 1.5px solid var(--io-line); }

/* Pulse page: the review funnel and theme bars. */
.io-bars { list-style: none; margin: 0; padding: 0; }
.io-bars li { display: grid; grid-template-columns: 1fr auto; gap: .3rem .8rem;
  margin: 0 0 .75rem; }
.io-bars .lbl { font-size: .9rem; color: var(--io-ink); }
.io-bars .lbl.top { font-weight: 700; }
.io-bars .val { font-size: .85rem; color: var(--io-muted); font-variant-numeric: tabular-nums; }
.io-bars .track { grid-column: 1 / -1; height: .5rem; border-radius: 999px;
  background: var(--io-sunk); box-shadow: inset 0 1px 2px rgba(60, 40, 20, .1);
  overflow: hidden; }
.io-bars .fill { display: block; height: 100%; border-radius: 999px; background: #CDBBA6; }
.io-bars .fill.top { background: linear-gradient(90deg, var(--io-brand-hi), var(--io-brand-lo)); }
.io-bars.sage .fill.top { background: linear-gradient(90deg, #6A9375, var(--io-sage)); }
.io-doc h2 { font-size: 1.55rem; margin: 0 0 .2rem; padding: 0; letter-spacing: -.015em; }
.io-doc h3 { font-size: 1.15rem; margin: 1.1rem 0 .4rem; padding: 0; }
.io-doc p, .io-doc li { line-height: 1.6; color: var(--io-ink); }
.io-doc em { color: var(--io-muted); font-style: normal; font-size: .9rem; }
.io-quote { border-radius: 16px; padding: .85rem 1rem; font-size: .95rem; line-height: 1.6;
  color: var(--io-ink); background: var(--io-surface); border: 1px solid var(--io-faint);
  box-shadow: 0 1px 2px rgba(60, 40, 20, .05); margin-bottom: .7rem; }
.io-quote.serif { font-family: var(--io-serif); font-size: 1.15rem; line-height: 1.5; }

.io-foot { color: var(--io-muted); font-size: .8rem; margin-top: 2.6rem; padding-top: .8rem;
  border-top: 1px solid var(--io-faint); text-align: center; }
"""
).replace("SERIF_STACK", SERIF)

ICONS = {
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>'
    '<path d="M8.5 11h5M11 8.5v5"/>',
    "voice": '<path d="M12 3.5a3 3 0 0 0-3 3v5a3 3 0 0 0 6 0v-5a3 3 0 0 0-3-3Z"/>'
    '<path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5v3"/>',
    "approve": '<path d="M12 3 4.5 6v5.5c0 4.4 3.1 8.1 7.5 9.5 4.4-1.4 7.5-5.1 7.5-9.5V6Z"/>'
    '<path d="m8.5 12 2.4 2.4 4.6-4.8"/>',
    "pulse": '<path d="M3 12h3.5l2.5-6 4 12 2.5-6H21"/>',
    "mail": '<rect x="3.5" y="5.5" width="17" height="13" rx="2.5"/><path d="m4.5 7 7.5 6 7.5-6"/>',
    "book": '<path d="M5 4.5h10.5A3.5 3.5 0 0 1 19 8v11.5H8.5A3.5 3.5 0 0 1 5 16Z"/>'
    '<path d="M5 16a3.5 3.5 0 0 1 3.5-3.5H19M9 8h6"/>',
    "upload": '<path d="M12 15V4.5M7.5 9 12 4.5 16.5 9"/>'
    '<path d="M4.5 15v3a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-3"/>',
    "calendar": '<rect x="4" y="5.5" width="16" height="14.5" rx="2.5"/>'
    '<path d="M4 10h16M8.5 3.5v4M15.5 3.5v4"/>',
    "notes": '<rect x="5" y="3.5" width="14" height="17" rx="2.5"/>'
    '<path d="M8.5 8h7M8.5 12h7M8.5 16h4"/>',
}
