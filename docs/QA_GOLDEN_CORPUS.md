# CLEARGATE Golden Corpus

The committed golden corpus is synthetic and safe for GitHub. It lives in:

- `backend/tests/fixtures/golden/*.txt` — source legal-text snippets
- `backend/tests/fixtures/golden/*.expected.json` — expected anonymization behavior
- `backend/tests/services/test_golden_corpus.py` — executable regression checks
- `backend/tests/services/test_document_processor_pdf.py` — synthetic PDF/TXT
  ingestion checks, including DOCX preview generation

Each expected JSON file can declare:

- `expected_entities`: exact spans and entity types that must be detected.
- `forbidden_entities`: exact spans and entity types that must not be detected.
- `expected_type_counts`: minimum/maximum counts for important entity types.
- `llm_false_positives`: simulated LLM additions that post-processing must reject.

Run the golden suite:

```powershell
docker compose -f docker-compose.local.yml run --rm --no-deps `
  -e PYTHONPYCACHEPREFIX=/tmp/pycache `
  -v ./backend/tests:/app/tests:ro `
  backend sh -c "python -m pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/services/test_golden_corpus.py -q -o addopts=''"
```

When adding a regression:

1. Create a synthetic `.txt` document with no real client data.
2. Add a matching `.expected.json`.
3. Prefer exact entity spans copied from the source text.
4. Add forbidden spans for every false positive found in the UI.
5. Add `llm_false_positives` when deep scan previously degraded the markup.

Real documents do not belong in this corpus. Use the private QA workflow instead.
