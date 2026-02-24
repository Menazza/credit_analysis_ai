# Gold Document Test Suite

Deterministic regression tests for the credit analysis pipeline.

## Structure

Each gold document folder contains:

- `extraction.xlsx` — Extraction Excel (from document_extractor)
- `notes.json` — (optional) Notes JSON for covenant/accounting quality
- `expected/` — Snapshot files for comparison
  - `normalized_facts_snapshot.json`
  - `metrics_snapshot.json`
  - `rating_snapshot.json`
  - `memo_bullets_snapshot.json`

## Bootstrap

To create a new gold document from an existing extraction:

```bash
cd backend
python -m tests.gold_runner --bootstrap tests/gold/shoprite_2025 --extraction ../test_results/pipeline_output/statements_shp-afs-2025.xlsx --notes ../test_results/pipeline_output/notes_shp-afs-2025.json
```

## Run Gold Tests

```bash
cd backend
python -m tests.gold_runner
# or
python -m tests.gold_runner tests/gold/shoprite_2025
```

Exit code 0 = PASS, non-zero = FAIL.

## Determinism Rules

- Mapping Pass A+B: ordered rules, stable sorting
- LLM suggestions: never auto-apply
- No randomization: no random seeds or nondeterministic logic in pipeline
