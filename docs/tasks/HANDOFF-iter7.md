# HANDOFF — Iteration 7

**Date:** 2026-04-14  
**Author:** Claude (iter6→iter7 transition)  
**Branches:** `master` = demo, `dev` = development (both at `567ece5`)  
**Demo tag:** `demo-v0.7.3`  
**Tests:** 39/39 green (entity_registry + docx_deanonymize)

---

## Current State

CLEARGATE v0.7.3 is a working demo. The full Phase 1 round-trip works end-to-end:

```
Upload .docx → Anonymize (regex + NER + LLM) → Export anonymized .docx
→ (lawyer uses external LLM) →
Import LLM response .docx → Deanonymize (fuzzy matching) → Resolve unknowns → Export final .docx
```

All 8 bugs from iteration 6 are fixed. UI is clean (single sans font, dark/light theme, RU/EN locale).

### Launcher Scripts

| Script | Branch | Purpose |
|--------|--------|---------|
| `START-DEMO.bat` | `master` | Stable demo for presentations |
| `START-DEV.bat` | `dev` | Development with latest changes |
| `START-CLEARGATE-Alpha.bat` | (current) | Original launcher, no branch switch |

### Branch Strategy

- **`master`** — frozen demo. Only touch to merge verified dev work or update launchers.
- **`dev`** — all new development goes here. Created from master at `567ece5`.
- When a feature is complete and tested on `dev`, merge to `master` and update the demo tag.

---

## CLEARGATE Phases — Full Overview

### Phase 1 — Perfect Round-Trip (CURRENT)

**Goal:** Flawless single-document anonymize → LLM → deanonymize cycle. Must be perfect before any expansion.

**What's DONE:**
- Three-layer anonymization pipeline (Regex/Presidio → NER/spaCy+GLiNER → LLM/Ollama+Qwen)
- EntityRegistry with AES-256-GCM encryption, consistent placeholder mapping, pymorphy3 normalization
- PlaceholderMatcher with 4-step fuzzy resolution (exact → cross-language → Levenshtein → manual)
- Dynamic regex for custom entity types (РАССТОЯНИЕ, ЧАСЫ, etc.)
- Boundary-aware numeric replacement (_safe_replace)
- Import response .docx → deanonymize → export with formatting preservation
- Unresolved placeholder detection + manual resolution UI
- Russian PII regex recognizers (ИНН, ОГРН, СНИЛС, паспорт, банк. счёт, телефон, email, БИК)
- Split-pane DOCX viewer with synchronized zoom
- Light/dark theme, RU/EN i18n
- 39 backend tests

**What REMAINS (in priority order):**

1. **Session persistence to disk** — Size: L, Priority: CRITICAL
   - Currently sessions live in RAM only, lost on backend restart
   - Need SessionStore that serializes EntityRegistry + session metadata to disk
   - Encrypted at rest (AES-256-GCM key derived from session)
   - Without this, CLEARGATE is demo-only — can't survive a restart

2. **NER coverage expansion** — Size: M, Priority: HIGH
   - Add GLiNER labels for: monetary amounts, time periods, distances
   - Add regex recognizers for: КПП, ОКПО, ОКВЭД, кадастровый номер
   - Current coverage misses these in real legal documents

3. **spaCy model upgrade** — Size: S, Priority: MEDIUM
   - Switch ru_core_news_sm → ru_core_news_lg
   - Better NER quality, especially for organization names and addresses
   - Need to update download-models.ps1 and docker config

4. **E2E tests with real legal documents** — Size: L, Priority: HIGH
   - Test with actual contract/agreement patterns
   - Verify round-trip fidelity on complex formatting (tables, headers, footnotes)
   - Stress-test PlaceholderMatcher with LLM-distorted placeholders

5. **UI polish (Phase 1 acceptance)** — Size: M, Priority: MEDIUM
   - Test full flow manually on multiple document types
   - Error handling edge cases (large files, corrupt DOCX, network failures)
   - Loading states and progress indicators

### Phase 2 — Carousel, Diff, Multi-Doc

**Goal:** Deepen the document workflow — multiple versions, visual comparison, iterative refinement.

- Document carousel (4 docs rotating through split-screen panes)
- Diff view: original vs. deanonymized with accept/reject per change
- Multi-document sessions sharing a single EntityRegistry
- Iterative rounds (re-anonymize → send again → deanonymize round 2)

### Phase 3 — Built-in LLM Chat

**Goal:** Eliminate the "copy to external LLM" step — talk to LLMs directly inside CLEARGATE.

- API key settings UI (Claude/GPT/Gemini)
- Native adapters per provider (NOT unified shims — need extended thinking access per ADR-0006)
- Chat mode in UI with auto-anonymize outgoing / auto-deanonymize incoming
- Prompt library for common legal tasks
- WebSocket streaming for real-time responses

### Phase 4 — Extra Formats & Advanced

**Goal:** Support more input types and advanced features based on lawyer feedback.

- .pdf, .eml, .txt input support
- Advanced features TBD based on Phase 1-3 usage data

---

## Next Session Instructions

### Pre-flight Checks

```powershell
cd C:\Users\V\Documents\Claude\Projects\Cleargate

# Verify branches
git log --oneline master -1   # should be 567ece5
git log --oneline dev -1      # should be 567ece5 (or ahead if work was done)

# Switch to dev
git checkout dev

# Run tests
cd backend && .venv\Scripts\activate && pytest tests/services/test_entity_registry.py tests/services/test_docx_deanonymize.py -v
```

### FUSE Rules (CRITICAL — read before any file operation)

1. **Files >300 lines:** NEVER use Edit tool. Always write via bash/Python (`cat > file << 'EOF'` or Python script).
2. **Git operations:** FUSE creates phantom `.git/index.lock`. Use git plumbing (`git hash-object -w`, `git update-index`, `git write-tree`, `git commit-tree`) with `GIT_INDEX_FILE=/tmp/...` env var. Write commit SHA directly to `.git/refs/heads/dev`.
3. **HEAD points to `refs/heads/dev`** (not `main`). The `main` branch is stale — ignore it.
4. **After bash writes:** verify with `wc -l` and `python3 -c "import ast; ast.parse(open('file').read())"` for Python files.

### Recommended Work Order

1. **Session persistence** — this is the #1 blocker for real use
2. **NER expansion** — add the missing regex recognizers
3. **spaCy upgrade** — quick win for NER quality
4. **E2E testing** — validate everything with real documents
5. **Phase 1 acceptance** — final polish, then freeze `master` as v1.0

### Commit Conventions

- Branch: `dev` (never commit directly to `master`)
- Format: `feat(backend): add session persistence` / `fix(frontend): handle large file upload`
- Snapshot before risky operations: `.\scripts\snapshot.ps1 -Tag "pre-persistence"`
- Merge to master only after testing: `git checkout master && git merge dev && git tag demo-vX.Y.Z`
