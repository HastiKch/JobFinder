# Run JobFinder With GitHub Actions

Use this guide when you want GitHub to run JobFinder for you.

Back to the main project overview: [README.md](README.md)

Prefer running from your own machine instead? See [README.local.md](README.local.md).

## Usability

GitHub Actions is the recommended production workflow. After setup, you can run
the job search manually from the GitHub UI or let it run on the configured daily
schedule without keeping your laptop open.

This mode is best when your configuration is stable and you want repeatable
runs, central logs, and private values stored as GitHub repository secrets.

## Pros

- Runs online without your local machine.
- Supports manual and scheduled runs.
- Keeps private keywords, prompt, CV, API keys, and Google credentials in GitHub secrets.
- Starts from a clean Ubuntu runner each time, which makes production runs repeatable.
- Uploads run reports as workflow artifacts.

## Cons

- Requires repository secrets to be configured carefully.
- Iteration is slower than local runs because code and config changes need to be pushed.
- Logs, artifacts, and failures are viewed in GitHub instead of your terminal.
- Uses GitHub Actions minutes and still consumes Apify, Google, and OpenAI quota.

## Prerequisites

- A GitHub repository with Actions enabled.
- An Apify API token.
- An OpenAI API key when using `scrape_and_evaluate`.
- A Google service account JSON key.
- A Google Sheet shared with the service-account email as Editor.
- Google Drive API enabled, plus a `JobFinder` Drive folder shared with the
  service-account email as Editor if you want PDFs in a user-visible folder.
- Private keyword, prompt, and CV content ready to paste into repository secrets.

## How The Workflow Runs

The workflow is defined in:

```text
.github/workflows/jobs.yml
```

It runs the pipeline on GitHub:

1. Checks out the repository.
2. Sets up Python 3.14.
3. Installs LaTeX tools and dependencies from `requirements.txt`.
4. Validates required GitHub secrets.
5. Writes private keywords, prompt, CV, and Google credentials into temporary runner files.
6. Runs a provider-access preflight.
7. Scrapes jobs into Google Sheets.
8. Evaluates every unevaluated row with OpenAI when `scrape_and_evaluate` is selected.
9. Compiles generated LaTeX CVs to PDFs and uploads them to Google Drive.
10. Uploads JSON and Markdown run reports as artifacts.
11. Removes private runtime files from the runner.

## 1. Push The Repository To GitHub

Make sure your local repository points to the GitHub repo:

```bash
git remote -v
```

For this repository, it should look like:

```text
git@github.com:AmirDonyadide/JobFinder.git
```

Push your latest committed code:

```bash
git push
```

## 2. Create Or Choose A Google Sheet

Open the Google Sheet you want JobFinder to write to.

Copy only the spreadsheet ID from the URL. For this URL:

```text
https://docs.google.com/spreadsheets/d/1abcDEFghiJKLmnop123/edit
```

The spreadsheet ID is:

```text
1abcDEFghiJKLmnop123
```

This value goes into the GitHub secret `GOOGLE_SPREADSHEET_ID`.

## 3. Create A Google Service Account

Use one Google service account for both Sheets and Drive in GitHub Actions. It
does not require browser re-authorization and works well on temporary CI
runners.

1. Open Google Cloud Console.
2. Enable the Google Sheets API and Google Drive API.
3. Go to `IAM & Admin -> Service Accounts`.
4. Create a service account.
5. Create and download a JSON key for that service account.
6. Copy the `client_email` value from the JSON key.
7. Open your target Google Sheet and share it with that email as Editor.
8. Share an existing Google Drive folder named `JobFinder` with that email as
   Editor, or let the workflow create a service-account-owned `JobFinder`
   folder.

Copy the full JSON key into the GitHub secret:

```text
GOOGLE_SERVICE_ACCOUNT_JSON
```

## 4. Prepare Private Content

The workflow writes private files from GitHub secrets at runtime. Prepare these
values before adding secrets:

If you do not already have the private local files, create them from the examples
and fill them in first:

```bash
cp configs/keywords.example.txt configs/keywords.txt
cp prompts/master_prompt.example.txt prompts/master_prompt.txt
cp cv/master_cv.example.tex cv/master_cv.tex
```

| Local source | GitHub secret |
|---|---|
| `configs/keywords.txt` | `JOB_KEYWORDS_TEXT` |
| `prompts/master_prompt.txt` | `MASTER_PROMPT_TEXT` |
| `cv/master_cv.tex` | `MASTER_CV_TEX` |
| `cv/photo.jpg` | `CV_PHOTO_BASE64` (optional, base64 encoded) |
| `google_service_account.json` | `GOOGLE_SERVICE_ACCOUNT_JSON` |

On macOS, copy each value like this:

```bash
pbcopy < configs/keywords.txt
pbcopy < prompts/master_prompt.txt
pbcopy < cv/master_cv.tex
pbcopy < google_service_account.json
```

Paste each copied value into the matching GitHub secret.

If your LaTeX CV references a private photo and you do not commit a public
`cv/photo.jpg`, encode it for the optional `CV_PHOTO_BASE64` secret:

```bash
base64 -i cv/photo.jpg | pbcopy
```

## 5. Add GitHub Repository Secrets

In GitHub:

```text
Repository -> Settings -> Secrets and variables -> Actions -> New repository secret
```

Add these secrets exactly:

| Secret name | Required for | What to paste |
|---|---|---|
| `APIFY_API_TOKEN` | All runs | One Apify API token, or 1 to 12 tokens separated by `;`, for example `apify_api_1;apify_api_2;apify_api_3`. |
| `OPENAI_API_KEY` | `scrape_and_evaluate` | Your OpenAI API key, for example `sk-...` or `sk-proj-...`. |
| `GOOGLE_SPREADSHEET_ID` | All runs | The spreadsheet ID from the Google Sheet URL. |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | All runs | The full contents of the service-account JSON key. |
| `JOB_KEYWORDS_TEXT` | All runs | The full contents of `configs/keywords.txt`. |
| `MASTER_PROMPT_TEXT` | `scrape_and_evaluate` | The full contents of `prompts/master_prompt.txt`. |
| `MASTER_CV_TEX` | `scrape_and_evaluate` | The full contents of `cv/master_cv.tex`. |
| `CV_PHOTO_BASE64` | Optional | Base64-encoded `cv/photo.jpg` for LaTeX PDF generation when the photo is private. |

## 6. Run The Workflow Manually

In GitHub:

```text
Repository -> Actions -> JobFinder Pipeline -> Run workflow
```

Choose the source:

- `linkedin`
- `indeed`
- `stepstone`
- `both`
- `all`

Choose the posted-time window:

- `since_previous_run`: use the current daily behavior. Provider searches
  cover the time since the newest historical `Posted` value in the spreadsheet
  where supported, with a safety buffer, and results are narrowed to that
  posted-date interval.
- `last_24h`: scrape jobs posted in the last 24 hours.
- `last_7d`: scrape jobs posted in the last 7 days.
- `backfill`: scrape without a provider posted-time filter.

Choose the maximum applicants per job:

- `50`
- `100`
- `200`
- `no_limit`

Choose the pipeline mode:

- `scrape_and_evaluate`: scrape jobs, then evaluate them with OpenAI.
- `scrape_only`: create the new scraped Google Sheet tab without OpenAI evaluation.

Choose the unsuitable-row policy:

- `single_label_only`: keep `Not Suitable` rows with exactly one unsuitable-reason label, and remove the rest.
- `keep_all`: keep every evaluated row, including all `Not Suitable` rows.

Click **Run workflow**.

The workflow creates a new dated tab in your Google Sheet. In
`scrape_and_evaluate` mode, it then evaluates the jobs in that tab and writes
Drive PDF links to the `AI CV PDF` column.

## 7. Scheduled Runs

The workflow also runs automatically once per day during the 07:00 UTC hour.

The schedule is in `.github/workflows/jobs.yml`:

```yaml
schedule:
  - cron: "17 7 * * *"
```

GitHub may delay scheduled workflows slightly. That is normal.

To change the schedule, edit the `cron` value in `.github/workflows/jobs.yml`,
commit the change, and push it to GitHub.

Scheduled runs keep the existing defaults: all sources, `since_previous_run`,
max applicants `50`, `scrape_and_evaluate`, and `single_label_only`. The final
tab keeps `Not Suitable` rows only when they have exactly one unsuitable-reason
label. Source geography is Germany-only: LinkedIn uses the Germany location and
geo ID from `configs/filters.json`, Indeed uses `DE` / `Germany`, and Stepstone
uses `deutschland`.

## 8. Runtime Settings In GitHub Actions

The current workflow sets these runtime values in `.github/workflows/jobs.yml`:

```yaml
JOBFINDER_SCRAPER_OUTPUT_MODE: "google_sheets"
JOBFINDER_SCRAPER_SOURCES: ${{ github.event.inputs.sources || 'all' }}
JOBFINDER_PIPELINE_MODE: ${{ github.event.inputs.run_mode || 'scrape_and_evaluate' }}
JOBFINDER_SCRAPER_POSTED_TIME_WINDOW: ${{ github.event.inputs.posted_time_window || 'since_previous_run' }}
JOBFINDER_SCRAPER_MAX_APPLICANTS: ${{ github.event.inputs.max_applicants == 'no_limit' && '0' || github.event.inputs.max_applicants || '50' }}
JOBFINDER_SCRAPER_SEARCH_CONCURRENCY: "15"
JOBFINDER_SCRAPER_SEARCH_WINDOW_BUFFER_SECONDS: "3600"
APIFY_RUN_MEMORY_MB: "512"
APIFY_RUN_TIMEOUT_SECONDS: "3600"
APIFY_CLIENT_TIMEOUT_SECONDS: "120"
APIFY_TRANSIENT_ERROR_RETRIES: "5"
APIFY_RETRY_DELAY_SECONDS: "30"
INDEED_COUNTRY: "DE"
INDEED_LOCATION: "Germany"
STEPSTONE_LOCATION: "deutschland"
STEPSTONE_MAX_CONCURRENCY: "10"
STEPSTONE_MAX_REQUEST_RETRIES: "3"
JOBFINDER_SCRAPER_TIMEZONE: Europe/Berlin
JOBFINDER_SCRAPER_POSTED_TIMEZONE: Europe/Berlin
JOB_EVAL_OPENAI_MODEL: "gpt-5-mini"
JOB_EVAL_CONCURRENCY: "8"
JOB_EVAL_BATCH_SIZE: "40"
JOB_EVAL_CV_PDF_OUTPUT: "true"
JOB_EVAL_CV_PHOTO_FILE: cv/photo.jpg
JOB_EVAL_CV_PDF_APPLICANT_NAME: "Applicant"
JOB_EVAL_CV_PDF_TIMEOUT: "120"
JOB_EVAL_LARGE_QUEUE_THRESHOLD: "200"
JOB_EVAL_LARGE_QUEUE_SLEEP_MS: "2000"
JOB_EVAL_UNSUITABLE_ROW_POLICY: ${{ github.event.inputs.unsuitable_rows || 'single_label_only' }}
```

This keeps 15 Apify keyword searches running in parallel, with 512 MB assigned
to each actor run. Each keyword search gets up to 60 minutes of actor runtime.
Temporary Apify API issues such as 502/503/504 responses, rate limits, HTTP
timeouts, and short memory-limit pressure are retried before the workflow fails.
If `APIFY_API_TOKEN` contains multiple semicolon-separated tokens, the scraper
uses them in order. When Apify returns a billing/auth/access error for one token,
that token is skipped for the rest of the workflow run and the same search is
retried with the next configured token.

The evaluator allows up to 8 OpenAI requests at the same time, with jobs grouped
locally in batches of 40. When more than 200 rows are queued, the evaluator
spaces OpenAI request starts by 2000 ms. Each row is saved back to the same
sheet immediately after it is evaluated, so a later failure keeps completed rows.

If you see OpenAI rate-limit or retry warnings, reduce these values in
`.github/workflows/jobs.yml`:

```yaml
JOB_EVAL_CONCURRENCY: "5"
JOB_EVAL_BATCH_SIZE: "20"
```

## 9. Read The Results

- The Google Sheet receives a new dated tab for each run.
- `scrape_only` stops after writing scraped rows.
- `scrape_and_evaluate` writes final AI values back to the same tab.
- By default, the final tab keeps only one-label `Not Suitable` rows.
- Manual workflow runs can choose `keep_all` to preserve every evaluated row.
- The workflow uploads `jobfinder-run-reports` artifacts with JSON reports and a Markdown run summary.
- Private runtime files are removed from the GitHub runner in the final cleanup step.

## 10. Updating Configuration

Use repository files for shared, non-secret configuration:

| Change | Where |
|---|---|
| Search source defaults, schedule, speed, timeout, and evaluator concurrency | `.github/workflows/jobs.yml` |
| LinkedIn and Stepstone search defaults, title exclusions, company exclusions, applicant cap, status words | `configs/filters.json` |
| Python dependencies | `requirements.txt` |

Use GitHub secrets for private values:

| Change | Secret |
|---|---|
| Search keywords | `JOB_KEYWORDS_TEXT` |
| Evaluator prompt | `MASTER_PROMPT_TEXT` |
| CV content | `MASTER_CV_TEX` |
| Private CV photo | `CV_PHOTO_BASE64` |
| API keys | `APIFY_API_TOKEN`, `OPENAI_API_KEY` |
| Google Sheets and Drive access | `GOOGLE_SPREADSHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON` |

## Troubleshooting GitHub Actions

| Problem | What to check |
|---|---|
| `Missing repository secret ...` | Add the named secret under GitHub repo settings. |
| `GOOGLE_SERVICE_ACCOUNT_JSON` error | Copy the full service-account JSON key downloaded from Google Cloud. |
| Google authentication fails | Confirm the spreadsheet is shared with the service-account `client_email` as Editor. |
| Drive PDF links fail | Enable Google Drive API and share the `JobFinder` folder with the service-account `client_email` as Editor, or let the service account create it. |
| `LaTeX compilation failed` in `AI CV PDF` | Check that `latexmk`/`xelatex` installed, the generated LaTeX is valid, and any referenced photo is available through committed `cv/photo.jpg` or `CV_PHOTO_BASE64`. |
| Spreadsheet not found | Check that `GOOGLE_SPREADSHEET_ID` is only the ID, not the full URL. |
| Workflow cannot push or fetch repo | Check GitHub authentication and repository permissions. |
| OpenAI rate-limit retries | Lower `JOB_EVAL_CONCURRENCY` and `JOB_EVAL_BATCH_SIZE`. |
| No jobs found | Check keywords, filters, Apify actor status, source selection, and posted-date filters. |
| Private keywords/prompt/CV missing | Confirm `JOB_KEYWORDS_TEXT`, `MASTER_PROMPT_TEXT`, and `MASTER_CV_TEX` secrets are set. |
| Workflow does not run on schedule | Check that GitHub Actions are enabled for the repository. Scheduled workflows can be delayed by GitHub. |
| Scheduled run uses the wrong mode or source | Scheduled runs use the workflow defaults in `.github/workflows/jobs.yml`, not the last manual choices. |

## Security Notes

Use GitHub repository secrets for all private online values. Never commit API
keys, Google credentials, real keywords, prompts, or CV content.

If you expose a service-account JSON key, delete that key in Google Cloud and
create a fresh one before using it in GitHub.
