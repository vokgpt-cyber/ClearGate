# CLEARGATE v0.9 Release QA

v0.9 is the first deployable local build target for legal-document review with
DOCX plus practical PDF ingestion.

## Scope

- DOCX upload, review, anonymization, export, LLM-response import, and
  deanonymized DOCX export.
- PDF upload for text PDFs, with internal DOCX preview/export generation.
- OCR fallback for scanned PDF pages when Tesseract is available in the
  backend runtime.
- Deep Scan as a QA assistant: it proposes additional entities, but does not
  silently rewrite existing markup.
- Local backup helper for session data and private QA corpora.
- Synthetic golden corpus and PDF/TXT ingestion regressions.

## Manual QA Checklist

Run on 5-10 private documents that must stay outside Git:

1. DOCX: upload -> anonymize -> export DOCX -> reopen exported DOCX.
2. DOCX: run Deep Scan -> review suggestions -> apply only valid suggestions.
3. DOCX: import an anonymized LLM response -> deanonymize -> export.
4. PDF text document: upload -> verify preview -> anonymize -> export DOCX.
5. PDF scanned document: upload -> confirm OCR text appears or warning is logged.
6. Check that titles, role labels, and currencies are not anonymized.
7. Check that organizations, English organizations, amounts, dates, INN, KPP,
   OGRN, addresses, bank details, phones, and emails are anonymized.
8. Delete at least one session and verify its session folder disappears.
9. Run `.\backup.bat` and verify archive + bundle are created.

## Automated Gate

```powershell
docker compose -f docker-compose.local.yml run --rm --no-deps `
  -e PYTHONPYCACHEPREFIX=/tmp/pycache `
  -v ./backend/tests:/app/tests:ro `
  -v ./backend/pyproject.toml:/app/pyproject.toml:ro `
  backend sh -c "python -m pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/services/test_golden_corpus.py tests/services/test_document_processor_pdf.py -q -o addopts=''"
```

Before release, also run:

```powershell
python scripts/truncation_scan.py
git diff --check
```
