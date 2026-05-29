JobFinder searches job sites for you, saves matching jobs in Google Sheets, and can use AI to score each job and create tailored CV PDF links.

## ✅ Before You Start

You need these accounts:

1. A GitHub account.
2. An Apify account and API token. An API token is a private key that lets JobFinder use Apify.
3. An OpenAI API key if you want AI job scoring and tailored CVs.
4. A Google Sheet where results should appear.
5. A Google Drive folder where tailored CV PDFs should be saved.

You also need the private setup text for this job search:

1. Your job keywords.
2. Your AI instructions or prompt. A prompt is the text that tells the AI how to judge a job.
3. Your CV text.
4. Your Google token JSON. This is a private Google permission file. If you do not already have it, ask the repository owner or a technical helper to create it from the developer setup guide.

Keep all of these private. Do not paste them into normal files in GitHub.

## 🍴 Fork

Forking means making your own copy of this GitHub project.

1. Open the original JobFinder repository page on GitHub.
2. Click **Fork** in the top-right corner.
3. On the next page, leave the settings as they are.
4. Click **Create fork**.
5. Wait until GitHub opens your new copy.

You should now be on a page whose name looks like:

```text
your-github-name/JobFinder
```

## 🔑 Add Secrets

Secrets are private saved values. GitHub hides them after you save them, and the workflow (the saved online job that runs JobFinder) can use them without showing them in the repository. A repository is the GitHub project page.

1. In your fork, click **Settings**.
2. In the left menu, click **Secrets and variables**.
3. Click **Actions**.
4. Click **New repository secret**.
5. Paste one secret name and one secret value.
6. Click **Add secret**.
7. Repeat this for each secret in the table below.

Add these required secrets:

| Secret name | What to paste |
|---|---|
| `APIFY_API_TOKEN` | Your Apify API token. You can paste one token, or several tokens separated by `;`. |
| `GOOGLE_SPREADSHEET_ID` | The ID from your Google Sheet URL. For `https://docs.google.com/spreadsheets/d/ABC123/edit`, paste only `ABC123`. |
| `GOOGLE_TOKEN_JSON` | The full contents of your `google_token.json` file. |
| `JOB_KEYWORDS_TEXT` | Your job search keywords, one per line. |

Add these too if you want the full AI workflow:

| Secret name | What to paste |
|---|---|
| `OPENAI_API_KEY` | Your OpenAI API key. |
| `JOB_EVAL_CV_DRIVE_FOLDER_ID` | The ID from your Google Drive folder URL. |
| `MASTER_PROMPT_TEXT` | Your full AI instruction text. |
| `MASTER_CV_TEX` | Your full CV text. |
| `CV_PHOTO_BASE64` | Optional. A private CV photo converted to base64 text. Base64 is a text version of an image file. Skip this if you do not use a private photo. |

If you only want to collect jobs without AI scoring, you can skip the AI secrets and choose `scrape_only` when you run it.

## ▶️ Run It

GitHub Actions is the GitHub area that runs this tool online.

1. In your fork, click **Actions**.
2. If GitHub asks you to enable workflows, click **I understand my workflows, go ahead and enable them**.
3. In the left menu, click **JobFinder Pipeline**.
4. Click **Run workflow**.
5. Leave **Branch** as `main`. A branch is a version of the project.
6. For **Job sources to scrape**, choose `all` unless you only want one site.
7. For **Provider posted-time window**, choose `since_previous_run` for normal daily use.
8. For **Maximum applicants per job**, choose `50` to skip crowded jobs.
9. For **Pipeline mode**, choose `scrape_and_evaluate` for AI scoring, or `scrape_only` for job collection only.
10. For **Not-suitable rows in the final output**, choose `single_label_only` for a shorter sheet, or `keep_all` to keep every row.
11. Click the green **Run workflow** button.

The run may take a while. You can stay on the Actions page and click the newest run to watch its progress.

## 📬 Get Results

JobFinder writes results to the Google Sheet you saved in `GOOGLE_SPREADSHEET_ID`.

1. Open your Google Sheet.
2. Look for a new dated tab at the bottom.
3. In `scrape_only` mode, the tab contains scraped jobs.
4. In `scrape_and_evaluate` mode, the same tab also gets AI columns such as verdict, fit score, and CV PDF link.

GitHub also saves a small run report:

1. Open your fork on GitHub.
2. Click **Actions**.
3. Click the latest **JobFinder Pipeline** run.
4. Scroll to **Artifacts**. Artifacts are files GitHub saves after a run.
5. Download **jobfinder-run-reports**.

The workflow also runs automatically every day on the saved schedule. GitHub schedules use UTC, which is world standard time:

1. Around **07:17 UTC**.
2. Fallback around **11:37 UTC** if the first scheduled run did not succeed.
3. Fallback around **15:17 UTC** if no earlier scheduled run succeeded.

In Berlin, these are one hour later in winter and two hours later in summer. GitHub may also start scheduled runs a little late.

The automatic run uses the default choices: all sources, jobs since the previous run, maximum 50 applicants, AI scoring on, and a shorter final sheet.

## ❓ FAQ

### It says the run failed — what do I do?

Open the failed run in **Actions** and look for the first red error message. Most failures mean a secret is missing or pasted incorrectly. Check the exact secret name, then go to **Settings → Secrets and variables → Actions** and update it.

### Where do I see my job results?

Open the Google Sheet whose ID you saved as `GOOGLE_SPREADSHEET_ID`. Each successful run creates a new dated tab at the bottom of the sheet.

### How do I stop it?

To stop future automatic runs, open your fork on GitHub, go to **Actions**, click **JobFinder Pipeline**, click the **...** menu, and choose **Disable workflow**. You can enable it again later from the same page.
