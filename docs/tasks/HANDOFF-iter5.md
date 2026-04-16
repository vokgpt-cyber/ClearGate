# HANDOFF — Iteration 5: Quality & Coverage

**Дата:** 2026-04-14
**Последний коммит:** `bd6c5bb` (Phase 1 round-trip)
**Несохранённые изменения:** 15 файлов, +1052/-192 строк (НЕ закоммичены!)
**Предыдущие итерации:** iter3 (DocxPane refactor) → iter4 (strategy session) → Phase 1 round-trip → текущая сессия (quality pass)

---

## КРИТИЧЕСКОЕ ПРАВИЛО: FUSE-коррупция файлов

> **"Можешь себе это правило вытатуировать!?"** — пользователь, 2026-04-13

### Суть проблемы

Edit/Write tools пишут в **Windows FS**. Bash пишет в **FUSE mount** Linux-песочницы. Это ДВА РАЗНЫХ вида одних файлов. FUSE агрессивно кэширует и не видит записи Edit. Результат:

- Edit пишет 446 строк → bash `wc -l` видит 252 (stale cache) → bash перезаписывает → данные потеряны
- Edit после bash → null-байты в конце файла (FUSE/NTFS size mismatch)
- **8+ коррупций файлов** за несколько сессий, включая файлы, закоммиченные в git обрезанными

### ЖЕЛЕЗНОЕ ПРАВИЛО

**Для КАЖДОГО файла в сессии — ОДИН путь записи:**

| Файл | Метод | Почему |
|------|-------|--------|
| <300 строк, мелкая правка | Edit tool | Быстро, безопасно |
| >300 строк ИЛИ реконструкция | **Только bash/Python** | Edit вызовет коррупцию |

**После КАЖДОЙ записи — верификация в том же контексте:**
```bash
wc -l "$FILE"                    # строки совпадают
xxd "$FILE" | tail -3            # нет null-байтов
tail -5 "$FILE"                  # контент кончается правильно
```
Для TS: `npx tsc --noEmit`

**НИКОГДА:**
- Не смешивать Edit и bash на одном файле в одной сессии
- Не верифицировать Edit через bash (и наоборот)
- Не полагаться на Read после bash-записи — кэш может врать

### Текущие размеры файлов (ориентир)

| Файл | Строки | Метод записи |
|------|--------|-------------|
| `frontend/src/components/SplitWorkspace.tsx` | 1060 | bash only |
| `frontend/src/app/globals.css` | 1567 | bash only |
| `backend/app/routers/documents.py` | 461 | bash only |
| `backend/app/services/regex_recognizers.py` | 523 | bash only |
| `frontend/src/lib/api.ts` | 324 | bash only |
| `backend/app/services/docx_deanonymize.py` | 305 | bash only |
| `backend/app/services/entity_registry.py` | 250 | Edit OK |
| `frontend/src/lib/entity-types.ts` | 235 | Edit OK |
| `frontend/src/components/SelectionToolbar.tsx` | 217 | Edit OK |
| `backend/app/services/session_manager.py` | 143 | Edit OK |
| `backend/app/services/stopwords.py` | 122 | Edit OK |
| `frontend/src/components/Sidebar.tsx` | 101 | Edit OK |
| `frontend/src/components/Header.tsx` | 76 | Edit OK |

---

## Что было сделано в этой сессии

### Backend

1. **BIK recognizer** — добавлен `BikRecognizer` в `regex_recognizers.py` (паттерн `04\d{7}`, entity type `RU_BIK`, контекст "бик", "БИК", "банковский идентификационный")
2. **INN/OGRN/SNILS validate_result fix** — `validate_result` теперь возвращает `None` (а не `False`) при невалидной контрольной сумме. `None` = "нет мнения" → базовый score сохраняется, контекстные слова могут поднять. `False` = дропает матч полностью (это ломало тестовые документы с фейковыми номерами)
3. **Stopwords multi-word filter** — "Заявки Заказчика" ложно определялось как PER. Добавлена проверка: если каждое слово многословной фразы есть в `LEGAL_ROLE_STOPWORDS`, вся фраза — стопворд
4. **`/response-raw` endpoint** — новый GET endpoint в `documents.py`, сервит `session.deanonymized_docx_bytes` для превью в правой панели
5. **`deanonymize-docx` с manual_resolutions** — POST body теперь принимает `{ manual_resolutions: [{ placeholder, value }] }` для ручного разрешения плейсхолдеров
6. **`session_manager.py`** — добавлено поле `deanonymized_docx_bytes: bytes | None` в Session, очистка при `close_session`
7. **CORS** — `expose_headers=["Content-Disposition"]` в `main.py`

### Frontend

1. **Header/version badge** — убрана плашка "Connected ALPHA", добавлен floating badge в правый нижний угол: зелёная/красная точка + `v0.7.3`
2. **Entity overlap fix** — `addFromSelection` теперь удаляет существующие сущности, полностью покрытые новым выделением (предотвращает mark-inside-mark в DOM)
3. **URL fix** — `deanonymizeDocx()` в `api.ts`: `/deanonymize` → `/deanonymize-docx`
4. **"Применить" UX** — кнопка теперь вызывает `deanonymizeDocx(sessionId, resolutions)` и обновляет превью в правой панели вместо скачивания файла
5. **`deanonymizeDocx()` в api.ts** — теперь принимает optional `manualResolutions` и отправляет как POST body
6. **RU_BIK** — добавлен в `entity-types.ts` и `LEGEND_ORDER`
7. **globals.css** — добавлены стили для scale indicator, version badge, LLM panel, custom type, import/export buttons

---

## БАГИ ДЛЯ ИСПРАВЛЕНИЯ (приоритет)

### BUG-1: Вручную анонимизированные данные не деанонимизируются [CRITICAL]

**Симптом:** Пользователь выбирает текст → "Свой тип…" → вводит "РАССТОЯНИЕ" или "ЧАСЫ" → значение анонимизируется как `[РАССТОЯНИЕ_1]`, `[ЧАСЫ_1]`. При деанонимизации эти плейсхолдеры НЕ резолвятся обратно.

**Корневая причина:** `docx_deanonymize.py` строит `_PLACEHOLDER_RE` regex **только из `_ALL_LABELS`** — это фиксированный набор из `_RU_LABELS` и `_EN_LABELS` (19 типов). Кастомные типы (РАССТОЯНИЕ, ЧАСЫ, КЛИЕНТ и т.д.) **не попадают в regex**, поэтому сканер их просто не видит в тексте DOCX.

**Файлы:**
- `backend/app/services/docx_deanonymize.py` строки 54-75 — `_ALL_LABELS` и `_PLACEHOLDER_RE`
- `backend/app/services/entity_registry.py` строка 233 — fallback label: `self._labels.get(entity.entity_type, entity.entity_type)`

**Решение:** Сделать `_PLACEHOLDER_RE` динамическим. Вместо compile-time regex из фиксированных labels, PlaceholderMatcher должен при инициализации брать ВСЕ уникальные labels из `registry._reverse.keys()` и строить regex на лету. Или использовать более щедрый regex, который матчит `[ЛЮБОЕ_СЛОВО_N]`.

### BUG-2: Совпадение подстрок при ручной анонимизации ("500" в "500 000") [CRITICAL]

**Симптом:** Пользователь анонимизирует "500 км" → значение "500" становится плейсхолдером `[РАССТОЯНИЕ_1]`. Но "500" также встречается в "500 000 рублей" → `[РАССТОЯНИЕ_1] 000 рублей`. Анонимизация распространяется по всему документу на все вхождения подстроки.

**Корневая причина:** `entity_registry.py → anonymize_text()` (строка 146-156) заменяет по offset'ам (`result[:entity.start] + placeholder + result[entity.end:]`), но фронтенд, вероятно, при первичной анонимизации вызывает что-то, что делает глобальную замену текста "500" на placeholder. Или: `deanonymize_text()` (строка 158-165) делает `result.replace(placeholder, entry.canonical_value)` — это **глобальная** строковая замена, без привязки к позициям.

**Файлы:**
- `backend/app/services/entity_registry.py` строка 146 — `anonymize_text`
- `backend/app/services/docx_export.py` (или аналог) — экспорт анонимизированного DOCX
- Нужно проверить: как именно вручную добавленные сущности попадают в экспорт? Используется ли позиционная замена или глобальная?

**Решение:** При экспорте анонимизированного DOCX замена должна быть СТРОГО позиционной (по start/end), а не глобальной по тексту. Для `deanonymize_text()` глобальная замена OK (плейсхолдеры уникальны), но для анонимизации — нет.

### BUG-3: Zoom сломан и inconsistent между панелями [HIGH]

**Симптом:** При zoom документов структура документа не сохраняется. В деанонимизированном документе масштаб один, в оригинале и анонимизированном — другой. "Ужасное состояние".

**Файлы:**
- `frontend/src/components/DocxViewer.tsx` — zoom logic
- `frontend/src/app/globals.css` — zoom-related styles
- Уже записано в deferred UX fixes: zoom badge должен появляться только при изменении и затухать, позиционировать как overlay в правом нижнем углу панели

**Решение:** Все три панели (оригинал, анонимизированный, деанонимизированный) должны использовать ОДИН и тот же zoom state и одинаковую логику масштабирования. Zoom должен масштабировать контейнер через CSS `transform: scale()` с `transform-origin: top left`, а контейнер должен сохранять свои пропорции (не ломать вёрстку).

### BUG-4: Version badge (v0.7.3) не виден, сливается с фоном [MEDIUM]

**Симптом:** Плашка с версией сливается со всем остальным, "будто её и нет".

**Файлы:**
- `frontend/src/components/Header.tsx` строка 66-73
- `frontend/src/app/globals.css` — `.cleargate-version-badge` стили (opacity: 0.55)

**Решение:** Увеличить контрастность: opacity 0.75+, добавить тонкий backdrop-blur и/или border, сделать фон полупрозрачным. Или переместить badge в sidebar footer.

### BUG-5: Разнобой шрифтов — "это не стиль Apple" [MEDIUM]

**Симптом:** На главном экране "дохрена разных шрифтов". Используется микс `--font-serif` и `--font-sans` в разных местах без системы.

**Файлы:**
- `frontend/src/app/globals.css` — 20+ мест с `font-family` (serif в brand, sans в кнопках, serif в сессиях, sans в легенде...)

**Решение:** Apple/Harvey стиль = ОДИН основной шрифт (sans-serif: Inter или SF Pro) для всего UI, serif ТОЛЬКО для brand name "CLEARGATE". Убрать все `font-family: var(--font-serif)` кроме `.cleargate-sidebar__brand-name`. Всё остальное — `var(--font-sans)`.

### BUG-6: Подзаголовок "Анонимизация юридических документов" лишний [LOW]

**Симптом:** "Не нужны такие уточнения... это и так всем понятно. Ориентируйся на стиль Apple и Harvey. Без колхоза."

**Файлы:**
- `frontend/src/components/Sidebar.tsx` строка 47 — `{t('app.subtitle')}`
- `frontend/src/lib/locales/ru.json` — `"subtitle": "Анонимизация юридических документов"`
- `frontend/src/lib/locales/en.json` — `"subtitle": "Legal document anonymization"`

**Решение:** Убрать подзаголовок полностью. Оставить только "CLEARGATE" в brand area. Или заменить на минималистичный tagline в 2-3 слова (по аналогии с Harvey — там просто "Harvey" и всё).

### BUG-7: Деанонимизация возвращает canonical (нижний регистр) вместо оригинальных форм [MEDIUM]

**Симптом:** В деанонимизированном документе "петров алексей николаевич" вместо "Петрова Алексея Николаевича", "козлов марина игоревич" вместо "Козловой Марины Игоревны", "альфа логистика" вместо "ООО «Альфа Логистика»".

**Корневая причина:** `MappingEntry.canonical_value` — это нормализованная (лемматизированная) форма через pymorphy3. `deanonymize_docx` берёт `entry.canonical_value`, а нужно `entry.original_forms[0]` (первая встреченная форма, обычно из оригинального документа).

**Файлы:**
- `backend/app/services/docx_deanonymize.py` строка 124 — `self._reverse[normalized].canonical_value`
- `backend/app/services/entity_registry.py` — `MappingEntry` хранит `original_forms: list[str]`

**Решение:** В PlaceholderMatcher.match() возвращать `entry.original_forms[0]` если список не пуст, иначе fallback на `canonical_value`.

---

## ПЛАН РАСШИРЕНИЯ ПОКРЫТИЯ АНОНИМИЗАЦИИ

### Проблема

Пользователь не должен вручную добавлять каждый тип данных. Сейчас pipeline покрывает 19 типов, но в российских юрдокументах стандартно встречаются:

- **Количественные данные:** суммы (1 500 000 руб.), периоды (48 часов, 30 дней), расстояния (500 км), проценты (0,1%), количества (80 перевозок)
- **Идентификаторы:** КПП, ОКПО, ОКТМО, ОКВЭД, номера доверенностей, кадастровые номера
- **Юридические ссылки:** статьи законов (ст. 200.1 УК РФ), ФЗ (№ 152-ФЗ), постановления

### Рекомендуемый подход

1. **Расширить GLiNER labels** — zero-shot NER умеет находить произвольные типы по описанию. Добавить: "денежная сумма", "временной период", "расстояние", "процентная ставка", "номер доверенности", "ссылка на закон" и т.д. Это самый быстрый путь без кода.

2. **Включить LLM-слой** — третий слой pipeline (Qwen через Ollama), сейчас отключен (`enable_llm_layer: false`). Создан для контекстного анализа — найдёт то, что regex и NER пропустят.

3. **Добавить regex для структурированных ID:** КПП (9 цифр, формат XXXXYYZZZ), ОКПО (8 или 10 цифр), ОКВЭД (XX.XX.XX).

### Новые entity types для frontend

При расширении покрытия нужно синхронно обновить:
- `backend/app/services/entity_registry.py` — `_RU_LABELS` / `_EN_LABELS`
- `backend/app/models/entities.py` — `EntityType` literal
- `frontend/src/lib/entity-types.ts` — `EntityTypeCode`, `ENTITY_TYPES`, `LEGEND_ORDER`
- `frontend/src/lib/locales/ru.json` и `en.json` — `entity.types`

---

## ОБЩИЕ UX ПРИНЦИПЫ (из feedback пользователя)

1. **Стиль Apple/Harvey** — минимализм, один шрифт (sans), много whitespace, никакого "колхоза"
2. **Функциональность > подсказки** — не прикрывать баги тултипами, чинить root cause
3. **ANY selection MUST trigger popover** — любое непустое выделение в любой панели должно показывать popover анонимизации, без порогов, P0 блокер
4. **Conventional Commits** — `feat(backend): ...`, `fix(frontend): ...`
5. **Snapshot before risky ops** — `scripts/snapshot.ps1` перед опасными изменениями
6. **Никогда unified LLM shims** — нативные адаптеры с доступом к extended thinking
7. **Никогда не логировать** оригинальные тексты, mapping table, ключи шифрования

---

## НЕЗАКОММИЧЕННЫЕ ИЗМЕНЕНИЯ

15 файлов изменены относительно `bd6c5bb`. **Первое действие в новом чате:**

```bash
cd /path/to/cleargate
git add -A
git commit -m "feat(backend+frontend): BIK recognizer, deanonymize UX, version badge, entity overlap fix, stopwords multi-word filter

- Add BIK (Bank Identification Code) regex recognizer
- Fix INN/OGRN/SNILS validate_result: None instead of False for invalid checksums
- Add /response-raw endpoint for deanonymized DOCX preview
- Accept manual_resolutions in deanonymize-docx POST body
- Fix 'Применить' button: preview in right pane, not download
- Move version badge to floating bottom-right indicator
- Fix entity overlap: remove covered entities on new selection
- Fix deanonymize URL mismatch (/deanonymize → /deanonymize-docx)
- Add multi-word stopword filtering ('Заявки Заказчика')
- Add RU_BIK to frontend entity types and legend"
```

Затем snapshot:
```powershell
.\scripts\snapshot.ps1 -Message "iter5-pre-bugfix"
```

---

## ПОРЯДОК РАБОТЫ В НОВОМ ЧАТЕ

1. **Закоммитить** незакоммиченные изменения (см. выше)
2. **BUG-1** [CRITICAL] — dynamic placeholder regex для кастомных типов
3. **BUG-2** [CRITICAL] — позиционная замена при экспорте, не глобальная
4. **BUG-7** [MEDIUM] — original_forms[0] вместо canonical_value при деанонимизации
5. **BUG-3** [HIGH] — unified zoom across all panes
6. **BUG-5 + BUG-6** [MEDIUM] — один шрифт sans, убрать subtitle, Apple/Harvey style
7. **BUG-4** [MEDIUM] — version badge visibility
8. **Расширение покрытия** — GLiNER labels + regex для КПП/ОКПО/ОКВЭД
9. **Snapshot + тесты**
