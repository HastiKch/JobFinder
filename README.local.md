# Run JobFinder Locally

Use this guide when you want to run JobFinder from your own machine.

Back to the main project overview: [README.md](README.md)

Prefer the cloud workflow instead? See [README.github-actions.md](README.github-actions.md).

## Usability

Local runs are best for first-time setup, debugging provider credentials, changing
filters, testing prompts, and running one-off searches where you want immediate
terminal logs.

They are less convenient for routine scheduled searches because your machine,
Python environment, network connection, and credentials all have to be available
while the job is running.

## Pros

- Fastest feedback while editing keywords, filters, prompts, or CV content.
- Easy access to full terminal output and local files.
- Can scrape to a local Excel workbook with `JOBFINDER_SCRAPER_OUTPUT_MODE=excel`.
- Good place to test changes before committing or pushing them.

## Cons

- Your laptop must stay awake and online until the run completes.
- Python dependencies and credentials are your responsibility.
- Scheduling is not built into the local workflow.
- Local credential files must be handled carefully and never committed.

## Prerequisites

- Python 3.14 or newer.
- `latexmk` and `xelatex` when running evaluation with PDF output enabled.
- An Apify API token.
- An OpenAI API key when running evaluation.
- A Google service account and Google Sheet when using the full pipeline.
- A local clone of this repository.

Run all commands from the repository root.

## 1. Install Python Dependencies

With Conda:

```bash
conda create -n JobFinder python=3.14 -y
conda activate JobFinder
python -m pip install -r requirements.txt
cp .env.example .env
```

Install LaTeX tools for PDF generation. On Ubuntu:

```bash
sudo apt-get install -y latexmk texlive-xetex texlive-latex-extra
```

On macOS, install a TeX distribution that includes `latexmk` and `xelatex`, such
as MacTeX.

Optional: install the package in editable mode if you want the console scripts:

```bash
python -m pip install -e .
```

That enables:

```bash
jobfinder-pipeline
jobfinder-scrape
jobfinder-evaluate
```

## 2. Create Private Local Files

Your real keywords, prompt, and CV are private. They are ignored by Git.

Create them from the examples:

```bash
cp configs/keywords.example.txt configs/keywords.txt
cp prompts/master_prompt.example.txt prompts/master_prompt.txt
cp cv/master_cv.example.tex cv/master_cv.tex
```

Then edit:

| File | What to put there |
|---|---|
| `configs/keywords.txt` | One search keyword per line. |
| `configs/filters.json` | Search settings, title exclusions, company exclusions, status dropdown values, and applicant cap. |
| `prompts/master_prompt.txt` | Your evaluator instructions. |
| `cv/master_cv.tex` | Your private LaTeX CV. |
| `cv/photo.jpg` | Optional CV photo referenced by LaTeX. Commit it only if it is public. |

Do not commit these private files.

## 3. Configure `.env`

Open `.env` and set at least:

```bash
APIFY_API_TOKEN=apify_api_...
OPENAI_API_KEY=sk-...
```

`APIFY_API_TOKEN` can also contain fallback tokens in one setting, separated by
semicolons. Use between 1 and 12 tokens:

```bash
APIFY_API_TOKEN=apify_api_1;apify_api_2;apify_api_3;apify_api_4;apify_api_5;apify_api_6
```

The scraper tries tokens in order. If Apify says a token cannot pay for a run,
the scraper retires that token for the current process and retries the search
with the next configured token.

`OPENAI_API_KEY` is only required when the selected mode evaluates jobs.

Common settings:

| Setting | Default | Description |
|---|---:|---|
| `APIFY_API_TOKEN` | blank | One Apify token, or 1 to 12 tokens separated by `;` for ordered credit fallback. |
| `JOBFINDER_SCRAPER_SOURCES` | `linkedin` | Use `linkedin`, `indeed`, `stepstone`, `both`, `all`, or comma-separated source names such as `linkedin,stepstone`. |
| `JOBFINDER_SCRAPER_OUTPUT_MODE` | `excel` | Use `excel`, `google_sheets`, or `both`. The full pipeline forces Google Sheets. |
| `JOBFINDER_PIPELINE_MODE` | `scrape_and_evaluate` | For `run_job_pipeline.py`, use `scrape_only` or `scrape_and_evaluate`. |
| `JOBFINDER_SCRAPER_SEARCH_CONCURRENCY` | `15` | Number of Apify searches run at the same time. |
| `JOBFINDER_SCRAPER_APIFY_MEMORY_LIMIT_MB` | `0` | Optional total Apify memory cap used to reduce search concurrency; `0` disables the cap. |
| `JOBFINDER_SCRAPER_APIFY_BATCH_SIZE` | `1` | Optional LinkedIn search batch size. Keep `1` unless actor results expose source search URLs for attribution. |
| `JOBFINDER_SCRAPER_MAX_RESULTS_PER_SEARCH` | `500` | Maximum LinkedIn results per keyword. |
| `JOBFINDER_SCRAPER_POSTED_TIME_WINDOW` | `since_previous_run` | Use `since_previous_run`, `last_24h`, `last_7d`, or `backfill` to control provider posted-time filters. LinkedIn uses second-based windows; Indeed and Stepstone use the closest supported actor day bucket when possible. |
| `JOBFINDER_SCRAPER_SEARCH_WINDOW_BUFFER_SECONDS` | `3600` | Extra search-window padding before exact posted-time filtering, to avoid missing jobs while the run is starting. |
| `JOBFINDER_SCRAPER_MAX_APPLICANTS` | `100` | Maximum applicants per job after scraping. Use `0` for no limit. |
| `APIFY_RUN_MEMORY_MB` | `512` | Memory assigned to each Apify actor run. |
| `APIFY_RUN_TIMEOUT_SECONDS` | `3600` | Maximum Apify actor runtime per keyword search. |
| `APIFY_CLIENT_TIMEOUT_SECONDS` | `120` | HTTP timeout for individual Apify API calls while starting, polling, and reading results. |
| `APIFY_TRANSIENT_ERROR_RETRIES` | `5` | Number of retry attempts for temporary Apify API/run errors before failing the run. |
| `APIFY_RETRY_DELAY_SECONDS` | `30` | Base delay before retrying a temporary Apify issue; later retries back off from this value. |
| `JOBFINDER_SCRAPER_TIMEZONE` | `Europe/Berlin` | Timezone for terminal logs and new Excel/Google Sheets tab names. |
| `JOBFINDER_SCRAPER_POSTED_TIMEZONE` | `Europe/Berlin` | Timezone for the `Posted` column. |
| `GOOGLE_SPREADSHEET_ID` | blank | Optional locally. You can also save the ID in `google_spreadsheet_id.txt`. |
| `INDEED_COUNTRY` | `DE` | Indeed country code when `JOBFINDER_SCRAPER_SOURCES` includes `indeed`. |
| `INDEED_LOCATION` | `Germany` | Indeed location when `JOBFINDER_SCRAPER_SOURCES` includes `indeed`. |
| `INDEED_MAX_RESULTS_PER_SEARCH` | `500` | Maximum Indeed results per keyword, capped at the actor limit of 1000. |
| `INDEED_MAX_CONCURRENCY` | `5` | Maximum Indeed actor searches run at the same time. |
| `STEPSTONE_LOCATION` | `deutschland` | Stepstone location slug for keyword searches. |
| `STEPSTONE_CATEGORY` | blank | Optional Stepstone category slug used only for category fallback searches. |
| `STEPSTONE_START_URLS` | blank | Optional comma- or newline-separated Stepstone search/job URLs. When set, Stepstone runs one direct-URL actor search instead of one run per keyword. |
| `STEPSTONE_MAX_RESULTS_PER_SEARCH` | `500` | Maximum Stepstone results per keyword or direct URL run. |
| `STEPSTONE_MAX_CONCURRENCY` | `10` | Maximum pages the Stepstone actor processes concurrently inside a run. |
| `STEPSTONE_MAX_REQUEST_RETRIES` | `3` | Stepstone actor page retry count. |
| `JOB_EVAL_SOURCE` | blank | Use `excel` or `google_sheets`; blank auto-selects Google Sheets when a spreadsheet ID exists, otherwise Excel. |
| `JOB_EVAL_SHEET` | `latest` | Worksheet or Google Sheet tab to evaluate. |
| `JOB_EVAL_OPENAI_MODEL` | `gpt-5-mini` | OpenAI model used for evaluation. |
| `JOB_EVAL_CONCURRENCY` | `8` | Number of OpenAI job evaluations run at the same time. |
| `JOB_EVAL_BATCH_SIZE` | `40` | Number of jobs processed per evaluator batch. |
| `JOB_EVAL_OPENAI_RETRIES` | `3` | Retry attempts for failed OpenAI requests. |
| `JOB_EVAL_OPENAI_TIMEOUT` | `120` | OpenAI request timeout in seconds. |
| `JOB_EVAL_MAX_OUTPUT_TOKENS` | `9000` | Maximum tokens allowed in each evaluation response. |
| `JOB_EVAL_CV_PDF_OUTPUT` | `true` | Compile generated LaTeX CVs to PDFs and save them to Google Drive. |
| `JOB_EVAL_CV_PHOTO_FILE` | `cv/photo.jpg` | Optional photo copied into each temporary LaTeX build directory. |
| `JOB_EVAL_CV_PDF_TIMEOUT` | `120` | Max seconds per LaTeX compilation. |
| `JOB_EVAL_CV_DRIVE_PARENT_FOLDER` | `JobFinder` | Google Drive parent folder for timestamped run folders. |
| `JOB_EVAL_CV_PDF_APPLICANT_NAME` | `Applicant` | Applicant name used in upload-safe PDF filenames like `12_CV_Applicant_GIS_Analyst_Acme.pdf`. |
| `JOB_EVAL_LARGE_QUEUE_THRESHOLD` | `200` | Enable request pacing when more than this many rows are queued for OpenAI. |
| `JOB_EVAL_LARGE_QUEUE_SLEEP_MS` | `2000` | Milliseconds to wait between OpenAI request starts for large queues. |
| `JOB_EVAL_SAVE_BATCH_SIZE` | `1` | Number of completed evaluations to save per write. `1` preserves row-by-row crash recovery. |
| `JOB_EVAL_UNSUITABLE_ROW_POLICY` | `single_label_only` | Use `single_label_only` to keep `Not Suitable` rows with exactly one label and remove the rest, or `keep_all` to preserve every evaluated row. |

## 4. Set Up Google Sheets For The Full Pipeline

The full local pipeline always writes to Google Sheets before evaluating jobs.
Use the scraper-only command if you only want a local Excel file.

Use a Google service account for Google Sheets access:

1. Open Google Cloud Console.
2. Enable the Google Sheets API and Google Drive API.
3. Go to `IAM & Admin -> Service Accounts`.
4. Create a service account.
5. Create and download a JSON key for that service account.
6. Copy the `client_email` value from the JSON key.
7. Open your target Google Sheet and share it with that email as Editor.
8. Share a Google Drive folder named `JobFinder` with that email as Editor, or
   let JobFinder create it for the service account.

Save the downloaded JSON key in this repository as a shared credential when one
service account should handle both Sheets and Drive fallback access:

```text
google_service_account.json
```

If Google downloaded the key with a project-specific name such as
`jobfinder-495809-abc123.json`, rename it:

```bash
mv ~/Downloads/jobfinder-*.json google_service_account.json
```

For separate service accounts, save the keys as:

```text
google_sheets_service_account.json
google_drive_service_account.json
```

You can also set `GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE`,
`GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE`, or `GOOGLE_SERVICE_ACCOUNT_FILE` in `.env`
to point at custom credential paths.

Then set `GOOGLE_SPREADSHEET_ID` in `.env`, or save the spreadsheet ID in:

```text
google_spreadsheet_id.txt
```

Copy only the spreadsheet ID from the URL. For this URL:

```text
https://docs.google.com/spreadsheets/d/1abcDEFghiJKLmnop123/edit
```

The spreadsheet ID is:

```text
1abcDEFghiJKLmnop123
```

Do not commit Google credential files or `google_spreadsheet_id.txt`.

Local OAuth with `google_client_secret.json` and `google_token.json` is still
supported as a fallback, but service-account auth matches the GitHub Actions
workflow and is simpler to move online later.

For PDF uploads into a normal personal Gmail/Google Drive account, use OAuth for
Drive because service accounts cannot use your personal Drive storage quota:

1. In Google Cloud, configure the OAuth consent screen and publish it to
   Production.
2. Create an OAuth client of type Desktop app.
3. Download the client JSON as `google_client_secret.json`.
4. Run:

   ```bash
   env PYTHONPATH=src python - <<'PY'
from jobfinder.integrations.google.drive import build_google_drive_service

   build_google_drive_service(error_cls=RuntimeError)
   print("Created or refreshed google_token.json")
   PY
   ```

Do not commit `google_client_secret.json` or `google_token.json`.

## 5. Run A Preflight Check

Preflight validates configuration and provider access without running the full
scrape/evaluate job:

```bash
python run_job_pipeline.py --preflight
```

For scrape-only mode:

```bash
python run_job_pipeline.py --mode scrape_only --preflight
```

## 6. Run JobFinder

Full Google Sheets pipeline:

```bash
python run_job_pipeline.py
```

Equivalent console script after `python -m pip install -e .`:

```bash
jobfinder-pipeline
```

Scrape to Google Sheets without evaluation:

```bash
python run_job_pipeline.py --mode scrape_only
```

Scrape only with `JOBFINDER_SCRAPER_OUTPUT_MODE` from `.env`:

```bash
python linkedin_job_scraper.py
```

Evaluate the latest Google Sheet tab:

```bash
python job_fit_evaluator.py --source google_sheets --sheet latest
```

Evaluate the latest local Excel worksheet:

```bash
python job_fit_evaluator.py --source excel --sheet latest
```

## 7. Read The Results

- `python linkedin_job_scraper.py` writes `jobs.xlsx` when `JOBFINDER_SCRAPER_OUTPUT_MODE=excel`.
- Google Sheets runs create a new dated tab in the configured spreadsheet.
- `python run_job_pipeline.py` evaluates the latest new Google Sheet tab in place.
- Completed evaluations are saved as rows finish, so a later failure keeps already completed rows.
- By default, final cleanup keeps only one-label `Not Suitable` rows. Set `JOB_EVAL_UNSUITABLE_ROW_POLICY=keep_all` to preserve all evaluated rows.
- After evaluation with PDF output enabled, the final AI columns are `AI Verdict`, `AI Fit Score` (0-26), `AI Unsuitable Reasons`, and `AI CV PDF`; the temporary `AI Tailored CV` column is removed during final cleanup.
- `AI CV PDF` contains a Google Drive PDF link on success, or a LaTeX/Drive error for that row.

## 8. Troubleshooting Local Runs

| Problem | What to check |
|---|---|
| `Missing required setting(s): APIFY_API_TOKEN` | Add `APIFY_API_TOKEN` to `.env` or your shell environment. |
| `Missing required setting(s): OPENAI_API_KEY` | Add `OPENAI_API_KEY`, or run with `--mode scrape_only`. |
| Google authentication fails | Confirm `google_service_account.json` is a service-account key and the sheet is shared with its `client_email` as Editor. |
| PDF upload fails | Enable the Google Drive API and share the `JobFinder` Drive folder with the service-account email as Editor. |
| `LaTeX compilation failed` in `AI CV PDF` | Install `latexmk` and `xelatex`, check the generated LaTeX, and make sure `JOB_EVAL_CV_PHOTO_FILE` points to any referenced photo. |
| Spreadsheet not found | Check that `GOOGLE_SPREADSHEET_ID` is only the spreadsheet ID, not the full URL. |
| Scraper writes Excel but pipeline fails | The full pipeline forces Google Sheets; complete the Google Sheets setup first. |
| No jobs found | Check keywords, `configs/filters.json`, source selection, Apify actor status, and posted-date filters. |
| OpenAI rate-limit retries | Lower `JOB_EVAL_CONCURRENCY` and `JOB_EVAL_BATCH_SIZE` in `.env`. |
| Apify timeout or transient errors | Reduce keyword count, reduce max results, lower concurrency, or increase `APIFY_RUN_TIMEOUT_SECONDS`. |
| Private files are missing | Recreate `configs/keywords.txt`, `prompts/master_prompt.txt`, and `cv/master_cv.tex` from the examples. |

## Security Notes

Never commit local credentials or private inputs. These files are ignored by Git
and should stay local:

```text
.env
google_client_secret.json
google_service_account*.json
*service_account*.json
*service-account*.json
jobfinder-*.json
google_token.json
google_spreadsheet_id.txt
configs/keywords.txt
prompts/master_prompt.txt
cv/master_cv.tex
cv/photo.jpg  # unless intentionally public
```

If you expose a service-account JSON key, delete that key in Google Cloud and
create a fresh one before using JobFinder again.
