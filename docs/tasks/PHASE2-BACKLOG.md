# Phase 2 — Backlog (bugs + UX)

> Seeded 2026-04-14 after Phase 1 acceptance testing on
> `ЛЛМ_Тренировочный_Договор_Альфа_Логистика (v12).docx`.

## Open bugs (must-fix before new Phase 2 features land)

### BUG-P2-1 — Custom placeholder misread as built-in type

**Repro:** user manually adds a custom entity type `АФТА`, получая плейсхолдер `[АФТА_2]` в ответе LLM. При деанонимизации сервер воспринимает его как `[ДАТА_2]` и подставляет значение даты.

**Hypothesis:** `PlaceholderMatcher.normalize()` или fuzzy-lookup в `EntityRegistry._fuzzy_lookup` слишком агрессивно сворачивает Cyrillic-метки: `АФТА` → `ДАТА` по Levenshtein ≤ 2 (3 буквы из 4 совпадают по позиции). Аналогичная ошибка уже ловилась для численных ИНН — мы уже сузили порог до `min(len//4, 4)`, но для коротких (4-символьных) меток порог всё ещё = 1, чего достаточно для `АФТА↔ДАТА` при case-insensitive сравнении.

**Fix direction:**
- Labels (алфавитная часть плейсхолдера) матчить **строго по equality**, fuzzy применять только к canonical-value части.
- Добавить регрессионный тест: custom type с меткой, лексически близкой к built-in (`АФТА`/`ДАТА`, `ЛИЦ`/`ЛИСТ`).

**Severity:** P0 — ломает корректность round-trip.

---

### BUG-P2-2 — Case form of place-name lost during deanonymization

**Repro:** В оригинале слово «Москве» (предложный падеж). После round-trip в деанонимизированном файле остаётся «Москва» (именительный) — грамматика предложения разваливается.

**Hypothesis:** pymorphy3-нормализация в `EntityRegistry.register()` сохраняет только **lemma** (`Москва`). При деанонимизации мы подставляем lemma обратно, игнорируя исходную словоформу, хранящуюся в detection stage как `entity.text`.

**Fix direction:**
- Хранить в `MappingEntry` **обе** версии: `canonical_value` (lemma для fuzzy-lookup) и словоформу, встреченную в **конкретной** позиции (`surface_form`).
- При deanonymize заменять placeholder на `surface_form` того вхождения, которое породило конкретный номер плейсхолдера, а не на lemma.
- Для случаев, где LLM использует плейсхолдер в новой грамматической позиции (не совпадающей с исходной), — на втором шаге применять pymorphy3.inflect к lemma по морфологическим признакам соседних слов (difficult). MVP: возвращать lemma как есть и пометить restoration как «низкоуверенная» (yellow warning в UI).

**Severity:** P1 — документ формально корректен, но читается косо; юристу придётся чинить вручную.

---

## UX upgrades (tracked in PHASES.md §2.5)

1. **Session list minimalism** — только дата+время в левом tray.
2. **Save & resume across stages** — анонимизация / import / деанонимизация / unresolved сохраняются полностью, пользователь может закрыть и вернуться.
3. **Ephemeral zoom HUD** — процент масштаба в нижнем правом углу правой панели, появляется только при изменении, fade-out через ~1 с.
4. **EPAM brand refresh** — все токены UI перевести на EPAM brandbook (нейтральные + один акцент), оформить ADR.

---

## Readiness assessment for Phase 2

**Green** (done, стабильно):
- Round-trip (1.2 + 1.3 + 1.4): import → deanonymize → export, 22+ тестов.
- Session persistence (SQLite WAL, 50 tests).
- Interactive entity overlay (both panes), manual add via selection.
- Compare-with-original (word-level LCS diff, toggle).
- DOCX page-geometry + styles transplant для визуального паритета деаноним-preview.
- Metadata scrub при экспорте (core props, app props, thumbnail, author).

**Yellow** (работает, но есть долги):
- Качество NER — всё ещё `ru_core_news_sm`; большая модель + GLiNER не разворачивалась.
- Морфология: inflection-aware deanonymization отсутствует (см. BUG-P2-2).

**Red** (блокер для Phase 2):
- BUG-P2-1: placeholder label collision ломает round-trip при custom-типах, лексически близких к built-in. Это обязательно исправить до старта 2.1 (карусель), потому что multi-doc сценарий увеличит частоту таких коллизий.

**Вердикт:** ядро Phase 1 принять можно (round-trip работает, persistence работает, UX round-trip закончен). Но до начала работ над 2.1/2.3 закрыть минимум BUG-P2-1. BUG-P2-2 можно параллелить с 2.5 (UX polish). NER-модель (1.1 в исходном PHASES.md) — всё ещё открыт, но не блокирует карусель/diff.
