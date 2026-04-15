# Handoff — Phase 1 complete → Phase 2 kickoff

**Date:** 2026-04-15
**Tag:** `phase1-complete` on `dev` branch (commit `4708bf3`)
**Accepted by:** user acceptance testing on `ЛЛМ_Тренировочный_Договор_Альфа_Логистика (v12).docx`, 2026-04-14
**Status:** ✅ Phase 1 closed. Phase 2 ready to start.

---

## What Phase 1 shipped

### Core round-trip (PHASES.md §1.2 + §1.3 + §1.4)
Lawyer uploads DOCX → anonymizes → exports → works with external LLM → loads LLM response DOCX → deanonymizes → exports final DOCX. Entire cycle tested end-to-end.

- `backend/app/routers/documents.py` — `POST /api/sessions/{id}/import-response`, `POST /api/sessions/{id}/deanonymize-docx`, `POST /api/sessions/{id}/export-deanonymized`
- `backend/app/services/docx_deanonymize.py` — `PlaceholderMatcher` with exact / cross-language / fuzzy-with-length-proportional-threshold resolution; `scan_placeholders`, `deanonymize_docx`
- `backend/app/services/docx_export.py` — metadata scrub on export (core props, app props, thumbnail, tracked-change authors, ZipInfo timestamps)
- `frontend/src/components/SplitWorkspace.tsx` — import response button, unresolved placeholder editor, compare-with-original toggle
- `frontend/src/lib/word-diff.ts` — LCS-based word-level Unicode-aware diff utility

### Session persistence (PHASES.md §1.5)
Sessions and mapping tables survive app restart. SQLite (WAL mode), AES-256-GCM encrypted mapping blob, 7-day default TTL, list/load/delete endpoints.

- `backend/app/services/session_store.py`, `session_manager.py`
- `backend/tests/services/test_session_store.py` (15 tests), `test_session_persistence.py` (8 tests)

### UI polish (ADR-0008)
Design-token refactor — `--radius-*`, `--shadow-*`, `--focus-ring`, `--accent-soft`, 4/8 px spacing grid. Sidebar active item → soft pill. Focus-visible rings on all interactive elements (WCAG 2.4.7). Palette preserved (burgundy `#8B1A2B`, warm neutrals).

- `frontend/src/app/globals.css` — 258 lines changed across 200+ selectors
- `docs/adr/0008-ui-design-tokens-polish.md`

### Critical fixes along the way
| Bug | Commit | Summary |
|---|---|---|
| BUG-1 | `a2dc42e` | Dynamic placeholder regex includes custom types (`РАССТОЯНИЕ`, `АФТА`, …) |
| BUG-2 | `a2dc42e` | Numeric boundary respected — `[ЛИЦО_1]` doesn't eat trailing digits |
| BUG-3/4/5/6 | `83411e3` | Unified zoom, single sans font, removed noisy subtitle, fixed badge |
| BUG-7 | `a2dc42e` | Deanonymize returns `original_forms[0]` (surface form) not lowercase lemma |
| BUG-8 | `f1b4604` | Frontend passes `manual_resolutions` on final export |
| BIK | `c399412` | Bank-identifier-code Presidio recognizer |
| BUG-P2-1 | `7f2aed9` | Length-proportional fuzzy threshold so `АФТА` no longer collapses to `ДАТА` |

### Test health
- **106/106** collectable backend service tests green (`test_docx_deanonymize`, `test_entity_registry`, `test_session_store`, `test_session_persistence`, `test_crypto`, `test_checksum_validators`).
- Collection-only failures on `tests/routers/*` and some service tests require `httpx`/Presidio/spaCy models in the sandbox — **not a code regression**, an environment gap.
- Frontend: TSC clean; `word-diff` smoke-tested (31 assertions: Russian swaps, empty↔empty, all-ins, all-del, newlines, HTML-safe, 500 words in ~13 ms).
- Manual acceptance: round-trip on the Alfa-Logistics training contract passed.

---

## What's open going into Phase 2

### Bugs deferred (tracked in `docs/tasks/PHASE2-BACKLOG.md`)

**BUG-P2-2 (P1) — Case-form preservation**
`Москве` (prepositional) round-trips as `Москва` (nominative) because pymorphy3 normalization stores only the lemma. Fix direction: persist `surface_form` per occurrence in `MappingEntry`; optionally re-inflect via `pymorphy3.inflect` when the LLM uses the placeholder in a new grammatical position. MVP: just emit the lemma and mark the restoration "low-confidence" (yellow badge in UI).

### UX polish backlog (PHASES.md §2.5)

1. **Sidebar sessions → date + time only** — filename moves to tooltip/hover card. The kliekable line shows just `2026-04-15 · 14:32`.
2. **Save & resume across stages** — SQLite persistence covers stage 1; extend to import / deanonymize / unresolved stages, with full preservation of manual entity adds, accept/reject, manual resolutions. UI: "Continue from where you left off".
3. **Ephemeral zoom HUD** — zoom % in bottom-right of right pane, Apple-style fade-out ~1 s after last wheel event. Remove permanent indicator from sub-header.
4. **EPAM brand deeper refresh** — token polish already landed in ADR-0008; a further brand pass (if requested) would revisit type scale, empty-state illustration, sidebar brand bar styling.

### Phase 2 core features (PHASES.md §2.1–§2.4)

- **§2.1 Carousel** — split-screen rotates through 4 documents (original, anonymized, LLM anonymized response, deanonymized response). Breadcrumb/dots indicator + slide animation.
- **§2.2 Diff with original** — compare-view LCS diff already works for any two documents on the right pane; §2.2 extends it with accept/reject per edit and final export with accepted edits.
- **§2.3 Multi-document sessions** — one EntityRegistry shared across several DOCXs in one session; group export as archive; group deanonymize multiple LLM responses against the shared registry.
- **§2.4 Iterative work** — loading a 2nd/3rd LLM response extends the same registry; round history.

**Blocker-before-Phase-2-features:** BUG-P2-1 (done). Recommended next: close BUG-P2-2 in parallel with §2.5 UX polish; start §2.1 carousel after that.

---

## Architectural state (for anyone picking this up)

- **Stack:** Tauri 2 + Next.js 15 + React 19 + Tailwind 4, FastAPI + Presidio + spaCy `ru_core_news_lg` + GLiNER + Ollama/Qwen (local LLM verifier).
- **3-layer anonymization pipeline:** regex recognizers (Presidio) → NER (spaCy + GLiNER) → local-LLM verifier. Results consolidated in `EntityRegistry` with AES-256-GCM mapping.
- **Frontend document rendering:** `docx-preview` wrapped in a `DocxPane` class (`frontend/src/lib/docx-pane.ts`) that owns the rendered-HTML snapshot; `rerender` restores from that snapshot instead of re-parsing the DOCX.
- **Branches:** `master` is the frozen demo (tagged `demo-v0.7.3`). `dev` is active development; everything since `567ece5` lives there. `phase1-complete` tag pins the Phase 1 close.

See `CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY_MODEL.md`, and the ADR directory for deeper context.

---

## Recommended Phase 2 sequencing

1. **BUG-P2-2** — surface-form preservation (≈1 session). Unblocks legally-correct output.
2. **UX §2.5 polish** — sidebar date-only + ephemeral zoom HUD + save-resume extension (1–2 sessions). Low risk, visible wins.
3. **§2.1 Carousel** — biggest visual change; needs settled UX first.
4. **§2.3 Multi-document** — built on top of carousel once UX stable.
5. **§2.2 Diff accept/reject + §2.4 Iterative** — refinement once multi-doc works.

---

*Start the next session with the prompt in `outputs/PHASE2-KICKOFF-PROMPT.md` (or paste it directly into a fresh chat).*
