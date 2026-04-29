# Cleargate anonymization quality test — 2026-04-21

Autonomous end-to-end test of the Cleargate anonymization pipeline against
seven realistic Russian legal documents. All inputs, outputs, scripts and
per-doc entity dumps are reproducible from this folder.

## TL;DR

| Metric | Value |
|---|---|
| Documents tested | 7 (6 .docx + 1 .txt) |
| Total characters processed | 18 595 |
| Total entities detected | 332 |
| Pipeline wall-time (all 7 docs) | ~0.9 s |
| Structured PII leaks (INN/OGRN/SNILS/passport/phone/email/account/BIK) | **0** |
| Proper-name leaks (PER/ORG) | **12** |
| False positives on legal/role terms | **28** (~8% of detections) |
| Round-trips that reconstruct the original byte-for-byte | **0 / 7** |

**Headline:** structured PII detection is excellent (0 leaks); proper-name
recall in signature blocks is the dominant failure mode; round-trip
reconstruction has three reproducible bug classes that need fixing before
Phase 2 can be called done.

## Test setup

Pipeline configuration in this test:

- Layer 1 (regex): full Presidio + 11 Cleargate `RU_*` recognisers from
  `app.services.regex_recognizers` — INN-10, INN-12, OGRN-13, OGRNIP-15,
  SNILS, passport, bank account, BIK, phone, date, case number, contract
  number.
- Layer 2 (NER): spaCy `ru_core_news_sm`. The production model
  `ru_core_news_lg` could not be downloaded inside the sandbox (timeout on
  the 470 MB archive); `_sm` is roughly the same recall on common entities
  but noticeably weaker on long surnames and signature-line short forms.
  This is called out per finding below where it matters.
- Layer 3 (LLM): **disabled** — Ollama is not available in the sandbox.
  All findings here are baseline regex+NER quality; the production system
  with Qwen 2.5 verification will catch a portion of the false negatives
  reported below.
- GLiNER: disabled (model archive too large for the sandbox).

Reproduce with:

```powershell
cd backend
.venv\Scripts\activate
python ..\test\generate_test_docs.py     # creates the 7 docs
python ..\test\run_anonymization_test.py # writes ..\test\results\
```

## Test corpus

Hand-rolled to cover the surface area of typical EPAM workflows:

| # | File | Type | Format | Why it's interesting |
|---|---|---|---|---|
| 01 | NDA.docx | Соглашение о неразглашении | prose only | minimum-viable NDA, two LLCs |
| 02 | Dogovor_uslug.docx | Договор оказания юр. услуг | parties block + table | LLC + ИП; full passport, address, OGRNIP |
| 03 | Trudovoy_dogovor.docx | Трудовой договор | prose | employee paspоrt + СНИЛС + ИНН + spouse |
| 04 | Agentskiy_dogovor.docx | Агентский договор | parties + 5-row commission table | category-by-category commission % |
| 05 | Politika_PDn.docx | Политика обработки ПДн | sectioned policy | numbered sections, no parties block |
| 06 | Dop_soglashenie.docx | Доп. соглашение к договору | prose + 6-row pricing table | tariff change document |
| 07 | Protokol_sobraniya.txt | Протокол собрания | plain text, 5 attendees | one entity, 5 different `Фамилия И.О.` references |

Every document carries valid PII that survives Cleargate's checksum
validators (INN-10/INN-12/OGRN-13 mod-11, SNILS Луна-style, БИК prefix
checks). PII generated programmatically — no real client data was used.

## What worked well

### 1. Structured PII — 100 % regex recall

A regex sweep across all seven anonymised outputs found **zero** unmasked
INNs, OGRNs, SNILSes, passports, phones, emails, bank accounts, БИКs,
OGRNIPs or ISO dates. Every pattern that the recogniser library knows
about, it caught — including:

- 22 INNs across both 10- and 12-digit lengths
- 15 OGRNs (13-digit) and the OGRNIP 15-digit variant inside parties
  blocks
- 5 SNILSes in the canonical `XXX-XXX-XXX YY` form
- 8 passports including the variant with internal space (`6515 345678`)
- 18 emails and 20 phone numbers including the `+7 (812) 555-22-33`
  formatting
- 27 dates in `DD.MM.YYYY` form

The high-confidence (`score = 1.0`) regex layer is the system's most
reliable component and matches the design intent.

### 2. Throughput

End-to-end pipeline (regex + spaCy `_sm` + post-processing + AES-GCM
mapping table builds) processed **18 595 characters in ~0.9 s on a
single CPU core** in the sandbox (no GPU, no LLM). Per-doc latencies all
landed between 0.11 s and 0.17 s. With `_lg` and the LLM layer enabled
that will grow, but the regex/NER baseline is comfortably sub-second per
contract — well inside interactive UX budget.

### 3. Stopword list catches the obvious legal cliches

The stopword filter (`is_stopword`) successfully suppressed common
phrases like *«Сторона»*, *«Стороны»*, *«Договор»*, *«Соглашение»* in
their bare forms. The false positives surveyed below are inflected or
compound forms the stopword list doesn't cover yet.

## Findings — what needs fixing

### Finding 1 — proper-name leakage in signature blocks (P0)

12 proper-name occurrences leaked through across 5 of the 7 documents.
All leaks share one structural cause: **the surname appears alone or as
`Initial.Initial. Surname`, not as a full ФИО triple.**

Examples (from the anonymised outputs):

| Doc | Leaked text | Surrounding context |
|---|---|---|
| 01_NDA | `Ромашка-Групп` | `«Ромашка-Групп» (ИНН [ИНН_2], ОГРН ...)` |
| 02_Dogovor_uslug | `Михайловский` (×3) | `А.В. Михайловский Заказчик: ИП Михайловская Е.В.` |
| 03_Trudovoy_dogovor | `Технопром` | `Акционерное общество «Технопром»` |
| 03_Trudovoy_dogovor | `Смирнов` | `Работник: Смирнов [ЛИЦО_2] [ПАСПОРТ_1]` |
| 03_Trudovoy_dogovor | `Козлова` | `И.М. Козлова Работник:` |
| 04_Agentskiy_dogovor | `Волкова` | `Н.С. Волкова Агент: ИП ...` |
| 04_Agentskiy_dogovor | `Кузнецова` (×2) | `ИП Кузнецовой А.С. № [СЧЁТ_1]` |
| 06_Dop_soglashenie | `Павлов` | `И.В. Павлов Заказчик:` |

Two sub-patterns:

1. **Bare surname after a full ФИО elsewhere.** spaCy detects
   `Смирнов Алексей Петрович` correctly in the parties block, but the
   later bare `Смирнов:` in the signature line is missed by the model
   and the registry. Because it isn't reported as an entity, it cannot
   be replaced — even though `Смирнов` is canonically already in the
   registry as the lemma of `[ЛИЦО_2]`.
   - **Fix direction:** after Layer 2 finishes, do a registry-aware
     post-pass that scans for substring matches against
     `entry.canonical_value` for PER entries (within reasonable token
     boundaries). This is cheap and surgical; the registry already has
     the right entry, we just need to find more occurrences of it.

2. **Initial.Initial. Surname signature line.** Lines like
   `И.М. Козлова`, `Н.С. Волкова`, `И.В. Павлов`, `А.В. Михайловский`
   are missed wholesale by `ru_core_news_sm`. A simple regex
   recogniser for `[А-ЯЁ]\.\s?[А-ЯЁ]\.\s?[А-ЯЁ][а-яё]+` would catch
   all of them with negligible false-positive risk inside Russian
   legal documents.
   - **Fix direction:** add a `RU_FIO_INITIALS` PatternRecognizer to
     `regex_recognizers.py` with score 0.85 (high enough to win
     overlap against bare-NER PERs but low enough that real ФИО from
     spaCy still wins).

3. **First-reference ORG names with `«»` quotes.** `«Ромашка-Групп»`,
   `«Технопром»`, `«Квант Лигал»` are the *first* mention of each org
   inside a parties block — they typically slip past
   `_sm` because the surrounding tokens (`общество с ограниченной
   ответственностью «...»`) is exactly the sequence that gets eaten by
   the stopword filter, and the quoted name itself doesn't look like
   a Russian word the small model recognises. `_lg` is much better
   here. **Recommendation:** continue treating `_lg` as a hard
   requirement for production, and add a recogniser for
   `«[A-ZА-ЯЁ][^»]{2,}»` after `(ООО|ОАО|АО|ЗАО|ПАО|НКО|АНО)` to act
   as a backstop.

### Finding 2 — false positives on legal role terms (P1)

28 / 332 entities (~8 %) are inflected role/policy terms that the
stopword filter doesn't currently cover. They get detected as PER, ORG
or LOC with score 0.85 — all from spaCy. Examples:

| Term | Detected as | Frequency |
|---|---|---|
| `Получающей`, `Раскрывающей`, `Получающая` | LOC / PER / ORG | NDA |
| `Принципала`, `Принципалом`, `Агента`, `Агентом` | PER / LOC / ORG | agency agreement |
| `Оператора`, `Оператором` | PER / LOC | privacy policy |
| `Работника`, `Работодатель` | PER | employment contract |
| `Трудовой` (in `«Трудовой договор»`) | PER | employment contract |
| `Политика`, `ПОЛИТИКА` | PER / ORG | privacy policy |
| `Договором` | PER | services agreement |

Why it matters: each false positive consumes a placeholder slot
(`[ЛИЦО_7]`, `[ОРГАНИЗАЦИЯ_4]` …) and pollutes the human-review UI
with noise. It also degrades round-trip quality — see Finding 3.

**Fix direction:** the stopword module already exists. Extend
`is_stopword` so it normalises the candidate through `pymorphy3` (or
just lowercases and strip-suffixes) before lookup, so that
`Принципала / Принципалом / Принципал` all match the single stem
`принципал`. The same trick will catch the `Оператор/Получающ/
Раскрывающ/Работник/Работодатель` family in one pass.

### Finding 3 — round-trip reconstruction fails on every document (P0)

0 / 7 documents reconstruct byte-for-byte after the
`anonymize_text → deanonymize_text` round trip. Three distinct bug
classes account for all failures.

#### 3a. Levenshtein fuzzy-match collides distinct dates and bank accounts

`EntityRegistry._fuzzy_lookup` allows up to `len(canonical) // 4` edits
(capped at 4). For a 10-character date `15.01.2025` the cap is 2 edits,
and **any two dates that differ by ≤2 character positions get merged
into one entry.**

Concrete collisions observed in the test corpus:

| Doc | Originals merged | Round-trip result |
|---|---|---|
| 02_Dogovor_uslug | `10.02.2025` ⇄ `15.03.2025` | both come back as `15.03.2025` |
| 07_Protokol_sobraniya | `15.01.2025`, `20.02.2025`, `25.05.2025` | all three come back as `25.05.2025` |
| 01_NDA | `30101810400000000225` ⇄ `30101810700000000187` (two different correspondent accounts) | both come back as one number |
| 02_Dogovor_uslug | similar K/с collision |

This is silent data corruption. A user who reviews the registry and
sees two distinct dates in the source doc will see one placeholder
covering both, and on deanonymisation the *wrong* date will appear in
the LLM-returned text.

**Fix direction:** disable Levenshtein fuzzy matching for entity types
where the canonical value is purely numeric or follows a strict format
(`RU_DATE`, `RU_INN`, `RU_OGRN`, `RU_SNILS`, `RU_BANK_ACCOUNT`,
`RU_BIK`, `RU_PASSPORT`, `RU_PHONE`, `RU_CASE_NUMBER`,
`RU_CONTRACT_NUMBER`). Keep fuzzy matching only for `PER`, `ORG`,
`LOC`, `ADDR` where it actually helps with morphological/typographic
variants.

#### 3b. ORG fuzzy-merge prepends `ООО «` to every reference

`«Индустрия Консалт»` (short) and `ООО «Индустрия Консалт»` (long)
both end up under one registry entry. Because `original_forms[0]` is
the long form, every short reference comes back as the long form on
deanonymisation:

```
original:    ...ответственностью «Индустрия Консалт»...
deanon:      ...ответственностью «ООО «Индустрия Консалт»...   ← double ООО + double «
```

Same pattern observed in 4 of the 7 docs (`Авто-Лайн`, `МедиаПро`,
`СтартАп Технолоджис`, `Индустрия Консалт`).

**Fix direction:** when fuzzy-matching ORGs, strip the legal prefix
(`ООО `, `АО `, `ПАО `, `«`, `»`) from both sides of the comparison
before computing distance, but keep the *full* surface form in
`original_forms`. Even better: at deanonymise time, prefer the
`original_forms` entry whose length matches the placeholder's actual
character context (i.e., look at neighbouring text to choose the
right surface form). This dovetails with the
`record_surface_forms` mechanism that already exists for export.

#### 3c. Morphological inflection lost on round-trip (PER and LOC)

`deanonymize_text` uses `original_forms[0]` — the *first* observed
surface form — for every occurrence. So inflected references collapse
to whichever case spaCy detected first:

```
original:    ...г. Екатеринбург ... Свердловской области в Октябрьском районе г. Екатеринбурга 23.08.2015...
deanon:      ...г. Екатеринбург ... Свердловской области в Октябрьском районе г. Екатеринбург 23.08.2015...
```

Other examples: `Республике Татарстан → Республика Татарстан`,
`Алексеев → Алексеева`, `Михаил Владимирович → Михаила Владимировича`,
`Москвы → Москве`.

This is not a new bug — it's the exact case the
`MappingEntry.surface_forms` field plus `record_surface_forms()` was
designed to fix at export time. The path that *does* fix it is
`POST /anonymize → DOCX export`, which the production code calls.
The plain `anonymize_text/deanonymize_text` API used by this test
harness (and by quick-experiment code paths) does not yet use the
occurrence-aware list.

**Fix direction:** make `deanonymize_text` aware of position when
called after `anonymize_text` — record the substitution sequence in
`anonymize_text` and consume it in reverse for deanonymisation. That
is functionally what the export path does; lift it to the registry's
public API so any caller gets correct round-trip behaviour without
having to opt in via the export-only hook.

### Finding 4 — secondary observations

- **Source-layer label is computed from score, not from origin.**
  `_convert_presidio_results` sets `source_layer = "regex" if
  score >= 0.7 else "ner"`. spaCy detections with confidence 0.85
  (the default it returns for high-confidence PERs/ORGs/LOCs) are
  therefore mislabelled as `regex`. Telemetry and UI debugging both
  rely on this field — fix is to track the actual recogniser name
  from `RecognizerResult.recognition_metadata` instead. Cosmetic, but
  it makes triage harder than it needs to be.
- **"Дата начала работы: 10 марта 2025 г."** — natural-language Russian
  dates ("10 марта 2025 г.") were *not* detected. The Russian date
  recogniser only matches `DD.MM.YYYY`. For Phase 2 / pilot, consider
  adding a recogniser for `\d{1,2}\s+(января|февраля|...|декабря)\s+\d{4}\s*г?\.?`.
- **`«Дополнительное соглашение № 2»`** got tagged as `ORG` by spaCy.
  Same root cause as Finding 2 — adding the document-type words
  («Соглашение», «Договор», «Политика», «Протокол») to the stopword
  stems list will fix it.

## Recommended next steps (ordered)

1. **Fix Finding 3a** — gate fuzzy matching by entity type. ~30 line
   change in `entity_registry._fuzzy_lookup`. Highest value: removes
   silent data corruption on numeric IDs.
2. **Fix Finding 1.2** — add `RU_FIO_INITIALS` recogniser. ~50 lines in
   `regex_recognizers.py` + tests. Removes the most embarrassing leak
   class (signature lines).
3. **Fix Finding 3c** — make `deanonymize_text` occurrence-aware.
   Probably the largest change of the four, but it's the one that
   makes round-trip stop being a per-call gamble.
4. **Fix Finding 2** — extend stopwords with morphological
   normalisation. ~40 lines in `stopwords.py`. Gets ~28 false positives
   off the human-review surface.
5. **Fix Finding 3b** — ORG-aware fuzzy comparison. ~20 lines in
   `_fuzzy_lookup` once 3a is in place.
6. Re-run this test suite and aim for `roundtrip_ok = 7 / 7` and
   `proper-name leaks = 0` before declaring Phase 2 done.

## Caveats on this test

- spaCy `_sm` is the model used here, not the production `_lg`.
  A subset of Finding 1's leaks (especially first-reference quoted
  ORG names) will not reproduce on `_lg`. Re-run on a developer
  machine with the full model before treating the leak count as
  ground truth — but Finding 3 is model-independent and will
  reproduce regardless.
- The LLM verification layer (Qwen 2.5) is off in this run. It is
  expected to recover some of the leaked ORG / surname references at
  the cost of adding latency. Re-run with `enable_llm_layer=True` to
  measure the lift.
- Documents are synthetic. Real EPAM contracts will have OCR noise,
  unusual abbreviations, footnotes and table layouts the synthetic
  set doesn't cover. This test should be considered a *floor* on
  baseline quality, not a representative sample.

## File index

| Path | Description |
|---|---|
| `test/01_NDA.docx … 07_Protokol_sobraniya.txt` | Synthetic input documents |
| `test/generate_test_docs.py` | Script that produced the inputs |
| `test/run_anonymization_test.py` | Test harness |
| `test/results/<name>_original.txt` | Plain-text extract of each input |
| `test/results/<name>_anonymized.txt` | Pipeline output, placeholders applied |
| `test/results/<name>_deanonymized.txt` | Round-trip output via the registry |
| `test/results/<name>_entities.json` | All detected entities for the doc |
| `test/results/_summary.json` | Aggregate counts across all 7 docs |
