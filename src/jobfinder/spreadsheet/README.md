# Spreadsheet Contracts

This package owns the canonical column names shared by scraper exports and
evaluator cleanup.

The contract lives in:

```text
src/jobfinder/spreadsheet/schema.py
```

## Column Sets

| Constant | Purpose |
|---|---|
| `EVALUATION_OUTPUT_COLUMNS` | Final AI columns kept after evaluation cleanup. |
| `REMOVED_AI_OUTPUT_COLUMNS` | Legacy AI metadata columns recognized and removed by evaluator cleanup. |
| `AI_OUTPUT_COLUMNS` | All AI columns, final plus removable legacy columns, used when excluding prompt input. |
| `DETAIL_COLUMNS` | Description/detail columns removed after evaluation. |
| `SCRAPER_OUTPUT_COLUMNS` | Full scraper export header. |
| `HEADER` | Backward-compatible alias for scraper export headers. |

## Current Final AI Columns

- `AI Verdict`
- `AI Fit Score`
- `AI Unsuitable Reasons`
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
