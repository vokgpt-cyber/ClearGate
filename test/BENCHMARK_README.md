# Cleargate model-comparison benchmark

Этот набор фикстур + скрипт для измерения качества и скорости разных LLM в pipeline Cleargate. Используется на ПК #2 в связке с локальным профилем (`docker-compose.local.yml` + Ollama на хосте).

## Что лежит в этой папке

| Файл | Что это |
|------|---------|
| `01_NDA.docx` … `06_Dop_soglashenie.docx` | DOCX-фикстуры (договоры, политика ПДн) — оригинальный пилотный набор |
| `07_Protokol_sobraniya.txt` | Protokol собрания участников ООО (TXT) |
| `08_pretenziya.pdf` | **Новое:** короткая претензия (~2 стр), PDF |
| `09_protocol_sd.pdf` | **Новое:** длинный протокол совета директоров (~5 стр), PDF |
| `10_tricky_dogovor.docx` | **Новое:** документ с omonyms/coreference/declensions — стресс-тест |
| `results/<doc>_ground_truth.json` | **Новое:** золотой стандарт, размеченный вручную (455 сущностей суммарно) |
| `results/<doc>_entities.json` | Старый pipeline-выхлоп — для совместимости, новые прогоны не используют |

## Что считается ground truth

В `*_ground_truth.json` лежит список ожидаемых сущностей в формате:
```json
[
  {"text": "Иванов Сергей Петрович", "entity_type": "PER"},
  {"text": "ООО «Ромашка-Групп»", "entity_type": "ORG"},
  {"text": "7707083893", "entity_type": "RU_INN"}
]
```

Покрываемые типы (соответствуют таксономии Cleargate v0.4.0):

| Группа | Типы |
|--------|------|
| NER | `PER`, `ORG`, `LOC`, `ADDR`, `POSITION` |
| Regex (российские ID) | `RU_INN`, `RU_OGRN`, `RU_SNILS`, `RU_PASSPORT`, `RU_BANK_ACCOUNT`, `RU_BIK`, `RU_PHONE`, `RU_DATE`, `RU_CASE_NUMBER`, `RU_CONTRACT_NUMBER` |
| Regex (универсальные) | `EMAIL_ADDRESS` |
| LLM-найденные | `MON` (денежные суммы) |

Ground truth размечен консервативно: КПП, ОГРНИП, корсчета, URL, ID-коды паспорта НЕ включены, т.к. в Cleargate нет соответствующих recognizer'ов — иначе у всех моделей будут постоянные false-negative от отсутствующих типов.

## Как запустить сравнение моделей на ПК #2

Предполагается что:
- `start-local.bat` уже отработал хотя бы один раз (контейнеры собраны)
- Ollama на хосте отвечает на `http://localhost:11434`

```powershell
cd C:\path\to\Velum

# Один прогон, явно выбирая модель:
$env:MODELS = "qwen2.5:7b-instruct-q4_K_M gemma3:27b"
.\scripts\bench-models.bat
```

Что делает `bench-models.bat`:
1. Для каждой модели в `MODELS`:
   - `ollama pull <model>` если нет
   - `docker compose -f docker-compose.local.yml up -d --no-deps backend` с переменной `OLLAMA_MODEL=<model>`
   - Ждёт пока `http://localhost/health` ответит
   - Запускает `python scripts/benchmark_v040.py --tag <safe_model_name>`
2. После всех моделей: `python scripts/compare_bench_results.py` собирает один общий отчёт

Результаты:
- `bench-results/bench-<timestamp>-<model>.json` — машиночитаемый detail для каждой модели
- `bench-results/bench-<timestamp>-<model>.md` — markdown-отчёт по одной модели
- `bench-results/comparison-<timestamp>.md` — **главный side-by-side отчёт**

## Как читать сравнение

Главный файл `comparison-*.md` содержит три блока:

1. **Run summary** — какие модели и когда прогнали.
2. **Overall quality and latency** — таблица с precision/recall/F1/latency по каждой модели + дельта.
3. **Per-document detail** — F1 и TP/FP/FN для каждого из 10 документов и каждой модели + F1-дельта.

Положительная дельта на F1/precision/recall = поздняя модель **лучше**.
Положительная дельта на latency = поздняя модель **медленнее**.

## Запуск только одной модели (без сравнения)

Если хочется один раз прогнать без switch-а контейнеров:

```powershell
python scripts\benchmark_v040.py --base-url http://localhost --password admin --tag manual-run
```

## Что НЕ делает этот benchmark

- Не тестирует UI-side фичи (drag-drop, экспорт DOCX, deanonymize-by-substring).
- Не покрывает позиционные offset'ы в тексте — сравнение идёт чисто по `(text.lower(), entity_type)` парам.
- Не различает кореференции — если модель пометила «Иванов С.И.» и «он» — оба считаются отдельными PER-сущностями (что и требуется ground truth'ом).
