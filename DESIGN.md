---
name: Investor Ops & Intelligence Suite
description: Linen & Caramel. Warm paper, raised card-stock, one caramel leather accent.
colors:
  canvas: "#F6F1EA"
  canvas-light: "#FFFBF5"
  canvas-shade: "#EFE4D6"
  surface: "#FFFDFA"
  sunk: "#F8F3EC"
  white: "#FFFFFF"
  ink: "#2B2722"
  ink-paper: "#FBF7F1"
  muted: "#6B6158"
  bar: "#CDBBA6"
  caramel: "#9A5B2C"
  caramel-hi: "#A8693A"
  caramel-lo: "#8A4F24"
  caramel-wash: "#F4E4D3"
  caramel-tint: "#FBF1E6"
  caramel-tint-deep: "#F6E7D6"
  sage: "#4A7354"
  sage-hi: "#6A9375"
  sage-deep: "#3A5E44"
  sage-wash: "#E2ECE1"
  sage-tint: "#F1F6F0"
  iris: "#535FA0"
  iris-deep: "#444F8C"
  iris-wash: "#E5E7F4"
  iris-tint: "#F1F2FA"
  red: "#A3341F"
  red-wash: "#F9E7E2"
  amber: "#85570A"
  amber-wash: "#FAF0DC"
  shadow-06: "rgba(60, 40, 20, .06)"
  shadow-08: "rgba(60, 40, 20, .08)"
  shadow-10: "rgba(60, 40, 20, .1)"
  shadow-12: "rgba(60, 40, 20, .12)"
typography:
  hero:
    fontFamily: "Iowan Old Style, Palatino Linotype, Charter, Bitstream Charter, Georgia, serif"
    fontSize: "clamp(2.6rem, 5.6vw, 4.5rem)"
    fontWeight: 700
    lineHeight: 1.02
    letterSpacing: "-0.03em"
  display:
    fontFamily: "Iowan Old Style, Palatino Linotype, Charter, Bitstream Charter, Georgia, serif"
    fontSize: "clamp(2rem, 3.2vw, 2.7rem)"
    fontWeight: 700
    lineHeight: 1.08
    letterSpacing: "-0.02em"
  display-sm:
    fontFamily: "Iowan Old Style, Palatino Linotype, Charter, Bitstream Charter, Georgia, serif"
    fontSize: "1.75rem"
    fontWeight: 700
  h2:
    fontFamily: "Iowan Old Style, Palatino Linotype, Charter, Bitstream Charter, Georgia, serif"
    fontSize: "1.55rem"
    fontWeight: 700
  h3:
    fontFamily: "Iowan Old Style, Palatino Linotype, Charter, Bitstream Charter, Georgia, serif"
    fontSize: "1.3rem"
    fontWeight: 700
    letterSpacing: "-0.01em"
  h4:
    fontSize: "1.15rem"
    fontWeight: 700
  lead:
    fontSize: "1.04rem"
    lineHeight: 1.6
  body:
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.6
  body-sm:
    fontSize: "0.95rem"
  caption:
    fontSize: "0.9rem"
  small:
    fontSize: "0.85rem"
  label:
    fontSize: "0.8rem"
    fontWeight: 650
  micro:
    fontSize: "0.72rem"
    fontWeight: 700
  code:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "0.85rem"
rounded:
  xs: "4px"
  sm: "8px"
  md: "14px"
  lg: "16px"
  xl: "22px"
  full: "999px"
spacing:
  para: "0.65rem"
  block: "1.1rem"
  section: "1.4rem"
  card: "1.25rem 1.35rem 1.2rem"
components:
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.xl}"
    padding: "{spacing.card}"
  card-nested:
    backgroundColor: "{colors.sunk}"
    rounded: "{rounded.lg}"
  button-primary:
    backgroundColor: "{colors.caramel}"
    textColor: "{colors.white}"
    rounded: "{rounded.full}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.full}"
  tag:
    textColor: "{colors.muted}"
    rounded: "{rounded.full}"
    typography: "{typography.label}"
  icon-tile:
    backgroundColor: "{colors.caramel-wash}"
    textColor: "{colors.caramel-lo}"
    rounded: "{rounded.md}"
  input:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.md}"
  refblock:
    backgroundColor: "{colors.caramel-tint}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
  stamp-approved:
    textColor: "{colors.sage}"
    rounded: "{rounded.sm}"
  stamp-rejected:
    textColor: "{colors.red}"
    rounded: "{rounded.sm}"
---
# Design System: Investor Ops & Intelligence Suite

## Overview

**Creative North Star: "Linen & Caramel"**

A calm, physical desk. The canvas is warm linen with soft light falling from the top. Every tool
sits on a raised sheet of card-stock with a layered shadow, and the one thing you should press is a
caramel leather pill. Headlines are set in a book serif; working text stays in the system sans. The
product should feel like a well-made private-bank folio, not a fintech dashboard.

The product has a front door and two portals:
- **Home**: a hero headline, the Customer and Admin portal CTAs, three pillar cards with live data,
  and a four-step flow strip.
- **Customer portal**: *Ask* (Smart-Sync FAQ) and *Book a call* (the theme-aware voice agent).
- **Admin portal**: *Review pulse* (CSV → Weekly Pulse) and *Approvals* (HITL holds, email drafts
  and the notes register).

There are no eval, health or metric panels in the product. Evals live in the CLI and in
`docs/evalsReport.md`.

**Key Characteristics:**
- Depth comes from three layers: the linen canvas, raised cards (`--io-shadow`), and nested cards
  that sink back to `sunk`.
- There is one accent (caramel). Sage means done or approved and also marks the voice brief.
  Iris marks Market Context and email. Red and amber are used only for state.
- Every card heading has an icon tile; there are no emoji.
- One animation: the approval stamp lands (280 ms, expo-out). Hover lifts on link cards and buttons
  are transitions, not choreography, and both are disabled under reduced motion.

## Colors

### Primary
- **Caramel** (#9A5B2C; gradient #A8693A → #8A4F24): primary pills, link cards' page links, focus
  rings, footnote numerals. Its washes (#F4E4D3, #FBF1E6, #F6E7D6) are used for icon tiles, the
  selected queue card and the booking reference block.

### Neutral
- **Canvas** (#F6F1EA), lit with radial light #FFFBF5 at the top and shaded #EFE4D6 at the
  bottom-right.
- **Surface** (#FFFDFA): cards, inputs, secondary pills. **Sunk** (#F8F3EC): nested cards and
  chat bubbles.
- **Ink** (#2B2722): text; the ink tag sets #FBF7F1 on ink. **Muted** (#6B6158): captions, labels
  and meta text.
- **Bar** (#CDBBA6): neutral bars in theme and funnel charts.
- Lines are rgba(74, 52, 30, .12), and faint lines are .07.

### Semantic
- **Sage** (#4A7354; hi #6A9375, deep #3A5E44, washes #E2ECE1/#F1F6F0): approved, done, the
  voice agent's brief, and the top theme bar.
- **Iris** (#535FA0; deep #444F8C, washes #E5E7F4/#F1F2FA): Market Context and the email annexure.
- **Red** (#A3341F / #F9E7E2): rejected, refused. **Amber** (#85570A / #FAF0DC): pending.

## Typography

Headings are set in a book serif (Iowan Old Style → Palatino → Charter → Georgia) with no webfont
fetch. Body text uses the system sans, and booking codes use the system mono.

| Step | Size | Use |
| --- | --- | --- |
| hero | clamp(2.6rem, 5.6vw, 4.5rem) | Home headline only |
| display | clamp(2rem, 3.2vw, 2.7rem) | Page titles |
| display-sm | 1.75rem | Booking code |
| h2 | 1.55rem | Live data figures |
| h3 | 1.3rem | Card titles, answer subject, empty states |
| h4 | 1.15rem | Annexure heads, pulse doc headings |
| lead | 1.04rem | Page subtitles |
| body | 1rem | Running text |
| body-sm | 0.95rem | Answer paragraphs, library rows |
| caption | 0.9rem | Register, quiet notes |
| small | 0.85rem | Footers, bar values, mono |
| label | 0.8rem | Tags, stamps, table headers |
| micro | 0.72rem | Footnote superscripts, stamp sub-lines |

Reading measure is capped at 66–70ch. Numerals are tabular in bars, registers and stamps.

## Layout

The app is a single centred column with top navigation, grouped into Home, Customer portal and
Admin portal. Approvals shows its pending count in the nav. Streamlit folds the nav into a menu on
narrow screens, and every column stacks.

| Page | Layout |
| --- | --- |
| Home | Hero, then 3 pillar cards, then the flow strip |
| Ask | Ask card plus answer (1.85) beside the library card (1) |
| Book | Call card (transcript, input) beside the brief and booking cards |
| Review pulse | Intake card beside the funnel card, then the pulse doc beside the themes and briefs cards |
| Approvals | Queue beside the open booking and its annexures, with the register full width below |

## Elevation & Depth

| Level | Treatment | Used for |
| --- | --- | --- |
| 0 | Linen canvas with radial light | The page |
| 1 | `--io-shadow`, a three-layer warm shadow | Cards |
| 2 | `--io-shadow-hi` | Hovered link cards (lift 2px) |
| Inset | Inset shadow | Inputs and nested cards (`sunk`) |
| Buttons | `--io-shadow-btn` (warm drop plus inner highlight) | Primary pills |

## Shapes

Radii: 4px (chat tail), 8px (stamps), 14px (icon tiles, inputs), 16px (nested cards, expanders,
uploader, reference block), 22px (cards), and full (buttons, tags, bars). Stamps use a 3px double
border (dashed while pending) and sit rotated −3° once filed.

## Components

`dashboard/ui_kit.py` provides the helpers below. CSS lives in `dashboard/theme.py`.

- **`card(name, tone)`**: a keyed `st.container` that renders as a raised card. Tones are
  `brand`/`sage`/`iris` (tinted top) and `link` (hover lift plus a stretched page link).
  Names must be unique per page.
- **`card_head` + `icon`**: an icon tile, a serif title and an optional meta tag.
- **`masthead(title, sub, portal)`**: the portal tag, display title and lead.
- **`tag`, `note`, `stamp`, `steps`, `kv`, `bars`, `empty_state`, `go_button`, `footer`**.
- **Answer** (`.io-circ`): the subject, six numbered paragraphs with superscript citations, and
  footnoted sources.
- **Reference block** (`.io-refblock`): the booking code in mono on a caramel tint, with a stamp.
- **Annexure** (`.io-annex`): an icon tile, title and stamp, a preview, then Approve / Edit /
  Reject.
- **Mail** (`.io-mail`): the To/Subject header and body, with Market Context in an iris mark.
- **Register** (`.io-register`): the notes doc, with the booking code in mono bold.

## Do's and Don'ts

- Do keep one primary (caramel) action per view; everything else is a white pill.
- Do give every answer its sources and keep six bullets.
- Do escape all dynamic text with `esc` before it goes into HTML.
- Do show caller names only as [REDACTED].
- Don't add evals, health or metric tiles to the product UI.
- Don't use emoji, gradient text, thick coloured side-stripes or eyebrow kickers.
- Don't add a second animation. The stamp is the only one.
