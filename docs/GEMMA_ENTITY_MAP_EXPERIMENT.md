# Gemma4 Entity-Map Experiment

## Status

This is a rollback-safe experimental path, not the production default.

Production/pilot default remains:

```env
CLEARGATE_ENTITY_ENGINE=classic
CLEARGATE_LLM_MODEL=gemma4:26b
CLEARGATE_DISABLE_LLM_LAYER=false
```

The current recommendation is to keep `classic` enabled for the pilot group and
use Gemma4 entity-map modes only for controlled QA runs.

## Why Not "Ask Gemma To Anonymize The Document"

Direct free-form LLM anonymization was tested and rejected as the primary
architecture. It can:

- hallucinate spans that are not present in the document;
- miss exact legal names that deterministic recognizers already found;
- rewrite text instead of preserving the source document structure;
- produce unstable JSON under long legal-document context.

The safer architecture is:

1. Deterministic recognizers produce candidate entities with exact offsets.
2. Gemma4 receives the source text plus candidate IDs.
3. Gemma4 may select candidate IDs or propose new exact spans.
4. The backend accepts only spans that can be validated against the source text.
5. The existing policy layer still filters generic words, legal role labels,
   support contacts, public tool names, and other known false positives.

This keeps the LLM as an assistant for candidate selection, not as the source of
truth for document rewriting.

## Engine Modes

`CLEARGATE_ENTITY_ENGINE=classic`

Stable default. Uses rules, spaCy, GLiNER, policy filters, and the existing
optional verifier/deep-scan path.

`CLEARGATE_ENTITY_ENGINE=gemma_shadow`

Runs Gemma4 entity-map in the background and records comparison metadata, but
returns the classic output. This is the safest A/B mode.

`CLEARGATE_ENTITY_ENGINE=gemma_primary`

Uses high-precision deterministic candidates plus validated Gemma4 selections.
This is experimental and slower.

`CLEARGATE_ENTITY_ENGINE=hybrid_consensus`

Sends deterministic candidates to Gemma4 and accepts only validated selections.
This is experimental and slower.

## Golden-Corpus Result

Evaluation run on 2026-05-15:

```powershell
.\.venv-codex\Scripts\python.exe scripts\evaluate_entity_engines.py `
  --engines classic_no_llm,gemma_primary,hybrid_consensus `
  --spacy-model ru_core_news_sm `
  --gliner-model none `
  --ollama-model gemma4:26b `
  --ollama-host http://localhost:11434 `
  --output reports\entity-engine-eval.json `
  --fail-on-regression
```

Summary:

| Engine | Expected recall | Forbidden hits | Extra detections | Count violations | Duration |
|---|---:|---:|---:|---:|---:|
| classic_no_llm | 123/123 (100.0%) | 0 | 0 | 0 | 291 ms |
| gemma_primary | 123/123 (100.0%) | 0 | 0 | 0 | 42969 ms |
| hybrid_consensus | 123/123 (100.0%) | 0 | 0 | 0 | 42746 ms |

Interpretation:

- The deterministic/classic pipeline currently passes the synthetic golden
  corpus with no measured regression and is much faster.
- Gemma4 candidate-map modes are safe on this corpus, but do not yet improve the
  measured score enough to justify enabling them by default.
- More private QA documents are needed before promoting any Gemma mode.

## IT Rollback

To disable the experiment:

```bash
cd /opt/cleargate
grep -q '^CLEARGATE_ENTITY_ENGINE=' .env \
  && sed -i 's/^CLEARGATE_ENTITY_ENGINE=.*/CLEARGATE_ENTITY_ENGINE=classic/' .env \
  || echo 'CLEARGATE_ENTITY_ENGINE=classic' >> .env

docker compose \
  -f docker-compose.yml \
  -f docker-compose.gpu.yml \
  -f releases/CLEARGATE-v1.0.4-pilot/docker-compose.release.yml \
  --profile gpu up -d --force-recreate backend
```

No data migration is required.

## Next Quality Gate

Before enabling `gemma_primary` or `hybrid_consensus` for real users:

1. Add 20-50 private QA documents with manually reviewed expected entities.
2. Run the evaluator against both `classic` and candidate-map modes.
3. Promote only if the Gemma mode improves recall without increasing false
   positives or document processing time beyond an accepted SLA.
