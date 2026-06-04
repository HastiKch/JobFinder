# Spreadsheet Contracts

This package owns the canonical column names shared by scraper exports and
evaluator cleanup.

The contract lives in:

```text
src/jobfinder/spreadsheet/schema.py
```

## Prerequisites

- Python 3.14 or newer.
- No external services. This package is a local schema contract.

## Quick Start

Inspect the current scraper header:

```bash
env PYTHONPATH=src python -c "from jobfinder.spreadsheet.schema import SCRAPER_OUTPUT_COLUMNS; print(SCRAPER_OUTPUT_COLUMNS)"
```

Run schema-sensitive tests:

```bash
python -m pytest tests/test_scraper_export_rows.py tests/test_evaluator_parsing.py tests/test_evaluator_storage.py
```

## Column Sets

| Constant | Purpose |
|---|---|
| `EVALUATION_OUTPUT_COLUMNS` | AI columns written by scraper/evaluator. `AI Tailored CV` is removed during final cleanup when PDF output is enabled. |
| `REMOVED_AI_OUTPUT_COLUMNS` | Legacy AI metadata columns recognized and removed by evaluator cleanup. |
| `AI_OUTPUT_COLUMNS` | All AI columns, final plus removable legacy columns, used when excluding prompt input. |
| `DETAIL_COLUMNS` | Description/detail columns removed after evaluation. |
| `SCRAPER_OUTPUT_COLUMNS` | Full scraper export header. |
| `HEADER` | Backward-compatible alias for scraper export headers. |

## Current AI Columns

- `AI Verdict`
- `AI Fit Score` (0-26)
- `AI Unsuitable Reasons`
- `AI Tailored CV`
- `AI CV PDF`

`AI Tailored CV` is a temporary evaluator column and is removed during final
cleanup when PDF output is enabled.

## Current Scraper Columns

The scraper writes:

1. Application/status and provider identity columns.
2. Job content columns.
3. Link columns.
4. Blank final AI columns for the evaluator to fill.

Keeping the AI columns in the initial export lets the evaluator update values in
place without changing downstream sheet structure midway through a run.

## Maintenance Rules

- Do not duplicate column lists in scraper or evaluator modules.
- Any column change should update tests, root docs, and relevant folder docs.
- Removing detail columns after evaluation is intentional. Those columns can be
  large and expensive to keep in final review tabs.
- If adding AI metadata columns again, decide whether they are final output or
  cleanup-only before changing `EVALUATION_OUTPUT_COLUMNS`.

## Use This For Your Own Project

Forks should treat column names as a public contract. If you change them, update
all of these together:

- `spreadsheet/schema.py`
- scraper row/export code
- evaluator parsing and storage code
- Google Sheets and Excel expectations in tests
- README sections that describe output columns

For private review preferences, prefer adding separate manual columns in Google
Sheets over changing core column names.

## Troubleshooting

| Problem | What to check |
|---|---|
| Evaluator cannot find rows to process | Confirm the sheet still has the expected scraper headers and `AI Verdict`. |
| A column disappears after evaluation | `DETAIL_COLUMNS`, legacy AI metadata, and sometimes `AI Tailored CV` are removed by final cleanup. |
| New column is blank in exports | Add it to `SCRAPER_OUTPUT_COLUMNS` and row-generation code, then update tests. |
