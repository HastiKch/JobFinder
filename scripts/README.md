# Scripts

The `scripts/` directory gives fork maintainers conventional command paths that
delegate to the real JobFinder package. They are useful when a runner or local
environment expects commands under `scripts/`, while the implementation stays in
`src/jobfinder`.

## Prerequisites

- Python 3.14 or newer.
- Runtime dependencies from `requirements.txt`.
- The same private files and credentials required by the underlying scraper,
  evaluator, or pipeline command.

## Quick Start

From the repository root:

```bash
python -m pip install -r requirements.txt
python scripts/run_pipeline.py --mode scrape_only --preflight
```

For local development, prefer the editable install from the root README:

```bash
python -m pip install -e .
```

## Script Map

| Script | Calls | Use it for |
|---|---|---|
| `run_pipeline.py` | `jobfinder.pipeline.cli:main` | Scrape to Google Sheets, then optionally evaluate. |
| `scrape_jobs.py` | `jobfinder.scraper.cli:main` | Scrape only to Excel, Google Sheets, or both. |
| `evaluate_jobs.py` | `jobfinder.evaluator.cli:main` | Evaluate an existing Excel workbook or Google Sheet tab. |

Each script prepends the repository `src` directory to `sys.path`, so it can run
without an editable package install as long as dependencies are installed.

## Usage Examples

```bash
python scripts/run_pipeline.py --preflight
python scripts/run_pipeline.py --mode scrape_only
python scripts/scrape_jobs.py
python scripts/evaluate_jobs.py --source google_sheets --sheet latest
```

## Use This For Your Own Project

Keep these files as wrappers in a fork. Change runtime behavior in
`src/jobfinder`, `.env`, `configs/filters.json`, or `.github/workflows/jobs.yml`
instead of adding logic here.

If you rename console scripts or package modules, update these wrappers, the root
wrappers, `pyproject.toml`, and the README examples together.

## Troubleshooting

| Problem | What to check |
|---|---|
| `No module named 'jobfinder'` | Run scripts from the repository root, or install with `python -m pip install -e .`. |
| Missing token or config errors | Create `.env`, `configs/keywords.txt`, prompt, and CV files from the examples. |
| Script behaves differently from root command | Compare the matching root wrapper and `pyproject.toml` console-script entry. They should point at the same module. |

## Maintainer Notes

- Keep these scripts as wrappers only. Workflow logic belongs in
  `src/jobfinder`.
- If CLI names or module paths change, update root wrappers and these scripts
  together.
- CI compiles these scripts but does not run them as separate smoke tests.
