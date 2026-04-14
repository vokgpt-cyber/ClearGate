# ADR-0008 — UI design-token polish pass (BizLink-level refinement)

**Status:** Accepted
**Date:** 2026-04-15
**Context:** Phase 2, UX backlog item §2.5 — brand/UX refresh after 2026-04-14 acceptance testing.

## Context

During Phase 1 acceptance testing (2026-04-14) the user judged the UI functional
but visually unrefined compared with reference material (BizLink-style
dashboard: light theme, generous whitespace, soft pill active states, single
accent, crisp typography). An audit of `globals.css` (1610 lines) surfaced
15 concrete polish gaps:

- Scattered hardcoded radii (2px, 3px, 4px, 5px, 6px) with no token discipline.
- `--radius-*` tokens referenced in code but never declared in `:root`.
- Sidebar active state using a 2px left border (blunt) instead of a soft pill.
- No `:focus-visible` rings anywhere — accessibility and polish gap.
- Stacked `box-shadow: var(--shadow-md), 0 12px 32px rgba(0,0,0,0.12)` on the
  entity popover, producing a harsh two-layer cast.
- Padding values off the 4/8 px grid (10/12/14/18 mixed arbitrarily).
- Dashed empty-state border disappearing against `--bg-primary`.

The brand palette itself (burgundy `#8B1A2B`, warm neutrals, serif + sans
pairing) was deemed correct and **explicitly preserved**. The refresh is
purely about *design quality* — tokens, rhythm, focus states, shadow depth.

## Decision

Introduce a full token scale in `:root` (and mirror it in `[data-theme="dark"]`)
and refactor every in-code `border-radius: Npx;` onto that scale:

| Token             | Value                             | Use                                   |
| ----------------- | --------------------------------- | ------------------------------------- |
| `--radius-xs`     | `4px`                             | small inline pills, chips             |
| `--radius-sm`     | `6px`                             | chips, type badges, header pills base |
| `--radius-md`     | `10px`                            | primary buttons, sidebar items        |
| `--radius-lg`     | `14px`                            | cards, popovers, empty state          |
| `--radius-pill`   | `999px`                           | full pills (scrollbar thumb, legend)  |
| `--space-{1..8}`  | `4/8/12/16/20/24/32 px`           | 4px grid rhythm                       |
| `--icon-{xs..lg}` | `12/14/16/20 px`                  | icon sizing scale                     |
| `--shadow-sm`     | `0 1px 2px rgba(15,15,17,0.04)`   | hairline elevation                    |
| `--shadow-md`     | `0 6px 20px rgba(15,15,17,0.08)`  | cards, toolbar surfaces               |
| `--shadow-lg`     | `0 16px 40px rgba(15,15,17,0.12)` | popovers, modals                      |
| `--focus-ring`    | `0 0 0 3px color-mix(in srgb, var(--accent) 30%, transparent)` | all interactive `:focus-visible` |
| `--bg-hover`      | `rgba(15,15,17,0.04)`             | non-brand hover fill                  |
| `--accent-soft`   | `rgba(139,26,43,0.10)`            | active sidebar pill, drag-over card   |
| `--transition-quick`  | `120ms ease`                  | colour/background micro-transitions   |
| `--transition-smooth` | `180ms cubic-bezier(0.4,0,0.2,1)` | enter/exit transitions            |

### Applied component changes (all CSS, no markup changes)

- **Sidebar item active state** → soft `--accent-soft` background + accent text
  colour + `font-weight: 600`; drops the `inset 2px 0` left-border.
- **Sidebar new-session button** → `--radius-md`, subtle `--shadow-sm`, focus
  ring halo, active-press translateY(1).
- **Header pills** → `var(--radius-md)`, hover fills with `--accent-soft`.
- **Empty state card** → solid 1px border (was dashed), `--radius-lg`, softer
  `--shadow-md`; drag-over uses `--accent-soft` wash + `--shadow-lg`.
- **Entity popover** → single `--shadow-lg` (was stacked), `--radius-lg`.
- **Scrollbar thumb** → `--radius-pill`, colour transition on hover.
- **26 hardcoded pixel radii** programmatically rewritten onto the token scale
  (1-6 px → `--radius-sm`; 8-10 px → `--radius-md`; 12-14 px → `--radius-lg`).

## Consequences

**Positive:**
- Single source of truth for corner radii, shadows, spacing, and focus rings
  across 200+ selectors.
- Dark theme automatically inherits the same polish (tokens overridden, not
  duplicated rules).
- Accessibility improved: every interactive element now has a visible focus
  halo per WCAG 2.4.7.
- Future brand changes (e.g. Phase 3 polish) touch tokens only, not rules.

**Negative / trade-offs:**
- One-shot atomic commit churns ~30% of `globals.css` lines. Reviewers must
  compare rendered screenshots, not read diffs.
- Token names deviate from Tailwind defaults — deliberate (we want project
  vocabulary, not framework vocabulary), but new contributors must learn them.
- `color-mix()` in `--focus-ring` requires modern browsers (Safari 16.2+,
  Chrome 111+, Firefox 113+). Tauri bundles Chromium — non-issue in our
  distribution target.

**Out of scope (tracked in PHASE2-BACKLOG.md):**
- Sidebar date-only labels (UX-1)
- Save & resume across stages (UX-2)
- Ephemeral zoom HUD (UX-3)
- Future typography scale audit beyond radii/spacing.

## References

- `frontend/src/app/globals.css` — token definitions + refactored selectors
- `docs/tasks/PHASE2-BACKLOG.md` §UX 2.5 — parent backlog
- 2026-04-14 acceptance-testing notes (user feedback on `ЛЛМ_Тренировочный_Договор_Альфа_Логистика v12.docx`)
