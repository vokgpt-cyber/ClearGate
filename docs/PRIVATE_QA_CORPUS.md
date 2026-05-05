# Private QA Corpus And Backups

Use this workflow for real or client-like documents. These files must stay local
and are ignored by Git.

Recommended local layout:

```text
qa/private_corpus/
  input/
    001_loan.real.docx
    002_distribution.real.docx
  notes/
    qa_findings.md
  exports/
    ANON_001_loan.private.docx
```

Git ignore coverage:

- `qa/private_corpus/`
- `backend/tests/fixtures/private_corpus/`
- `*.real.docx`
- `*.real.pdf`
- `*.private.docx`
- `*.private.pdf`

Manual QA checklist:

1. Upload the document.
2. Run fast anonymization.
3. Verify false positives: titles, role labels, currency codes, generic headings.
4. Verify misses: organizations, English company names, amounts, dates, INN, KPP,
   OGRN, addresses, bank accounts, BIK, phones, emails.
5. Run deep scan.
6. Confirm deep scan does not remove or downgrade structured regex hits.
7. Download anonymized DOCX and visually compare formatting.
8. Record only synthetic reproduction text in committed tests.

Backup guidance:

- Treat GitHub as a backup for source code only.
- Back up `backend/data/`, `logs/`, and private QA corpora separately.
- Use encrypted archives or a trusted encrypted backup target.
- Do not put real documents, session databases, mapping tables, or audit logs in Git.
- Keep at least one offline backup before destructive cleanup of local sessions.
