# /run-task

Execute a development task from `docs/tasks/` with full context loading.

## Usage

```
/run-task 03
/run-task 03-ner-pipeline
```

## What this does

1. Loads `docs/tasks/NN-task-name.md` into context
2. Loads CLAUDE.md (root + relevant subdirectory)
3. Loads referenced ADRs
4. Creates a feature branch: `task/NN-short-description`
5. Begins implementation following the task requirements
6. After implementation:
   - Runs tests (`pytest` for backend, `npm test` for frontend)
   - Runs linters (`ruff`, `mypy` for Python; `eslint`, `tsc` for TS)
   - Reports diff summary
   - Suggests commit message

## Pre-flight checks

- Working directory is clean (no unstaged changes)
- All previous tasks (dependencies) have been completed
- Required services are running (Ollama for ML tasks)

## Example

```
> /run-task 02

[Loading docs/tasks/02-regex-recognizers.md...]
[Loading docs/adr/0002-three-layer-ner-pipeline.md...]
[Loading docs/adr/0003-presidio-as-orchestrator.md...]
[Creating branch task/02-regex-recognizers...]

I'll implement Russian PII regex recognizers as specified in task 02.
This involves creating:
1. backend/app/services/regex_recognizers.py — 9 PatternRecognizer classes
2. backend/app/services/checksum_validators.py — INN/OGRN/SNILS validation
3. backend/tests/services/test_regex_recognizers.py — full test coverage
4. backend/tests/fixtures/synthetic_pii.json — synthetic test data

Starting with checksum_validators.py...
```
