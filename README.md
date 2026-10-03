# Free daily DevOps job alerts

Built for your 2.8+ years of experience. The full copy-ready Python code is in `job_alerts.py`; GitHub runs it daily at **08:00 IST** using `.github/workflows/daily-jobs.yml`.

**Status: built locally; not activated.** You must complete the account authorization and GitHub setup below. No real email has been sent. The system never visits or scrapes job listing pages; it uses public APIs/RSS and your own alert emails.

## 1. Requirements and honest limits

| Requirement | What you need |
|---|---|
| GitHub | Free account and a repository; a private repository is recommended |
| Gmail delivery | Gmail address, 2-Step Verification, an available App Password |
| Gmail reading | Free Google Cloud project with Gmail API enabled, Desktop OAuth client and refresh token |
| Local setup | Python 3.12+ and Git; only needed for initial authorization/testing |
| Platform alerts | Your LinkedIn, Naukri, Foundit and Instahyre accounts |
| Adzuna, optional | Free developer app ID and key, approved usage allowance |
| JSearch, optional | RapidAPI account, genuinely free JSearch subscription with suitable limits and no paid overage |
| n8n alternative | Docker and an existing computer that stays on and connected |

There is no paid hosting dependency in the GitHub version. Private-repository Actions use your account's included minutes; other repositories share that allowance. Review usage, leave paid spending disabled, and keep runs below the included allowance. Public repositories have different billing rules and expose code/state. See [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

Important limits:

- **08:00 is the scheduled time, not a guaranteed delivery time.** GitHub may delay or drop scheduled jobs under load. Schedules run on the default branch; inactive public repositories can have schedules disabled. [GitHub schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
- **Remotive delays public jobs by 24 hours**, so strict last-24-hours mode will normally exclude them. [Remotive API terms](https://remotive.com/remote-jobs/api).
- **Himalayas refreshes its API cache daily.** Bounded pagination and free-tier quotas mean this system cannot promise all openings. [Himalayas API](https://github.com/Himalayas-App/remote-jobs-api).
- **JSearch does not guarantee LinkedIn, Indeed or Glassdoor coverage.** The digest displays the publisher actually returned by the API. Its current free allowance could not be independently read from its dynamic pricing page; no allowance is assumed in code. Verify it yourself before enabling. [JSearch pricing](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch/pricing).
- Gmail alert arrival is **not** proof a job was posted in the last 24 hours. Default `strict` mode excludes jobs without an absolute source posting date. Optional `alert_received` mode includes recently received alerts but labels the date as unverified; it relaxes the stated freshness requirement.
- Email templates change. The parser is a conservative heuristic, not a claim that every platform template is already verified. Unrecognized messages and messages with unknown posting dates remain unread and generate a notice. Test against real alerts before relying on it; do not commit private email samples.
- Location restrictions and work authorization still matter. “Remote USA” is not “work from anywhere.” Remote roles without a known eligible country or worldwide label are held out.
- Some sources provide a board listing URL or redirect, not an employer application URL. The email preserves that authorized apply/source URL and attribution instead of scraping for another link.

## 2. Folder structure

```text
JobSearch/
  .github/workflows/daily-jobs.yml
  .env.example
  .gitignore
  config.json                 # keywords, country lists, Gmail labels
  requirements.txt
  job_alerts.py               # fetch, MIME/HTML parse, filter, dedupe, digest, SMTP
  authorize_gmail.py          # one-time local OAuth authorization
  data/state.json            # delivered hashes, processed IDs, API quota reservations
  tests/test_job_alerts.py
  n8n/
    README.md
    compose.yml
    Dockerfile
    .env.example
    worker.py                # internal HTTP adapters with shared Python filters
    format-email.js
  preview.html               # generated, ignored by Git
```

## 3. Set up Python on your computer

Install Python 3.12+ from [python.org](https://www.python.org/downloads/). On Windows, enable the Python launcher. Open PowerShell in this folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe job_alerts.py --demo
Start-Process .\preview.html
```

On Linux/macOS use `python3 -m venv .venv`, then `.venv/bin/python` for the commands. No API keys are needed for the demo.

## 4. Gmail API OAuth (read and mark your alerts)

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create a project, for example `personal-job-alerts`. This use of Gmail API does not require a paid compute service.
2. APIs & Services → Library → search **Gmail API** → Enable.
3. Open Google Auth Platform (or OAuth consent screen). Configure app branding and your email. Choose External for a normal personal Gmail account. Add yourself as a test user while configuring it.
4. Add the scope `https://www.googleapis.com/auth/gmail.modify`. This is needed to read messages and remove unread status/add a processed label. It is a restricted Gmail scope; do not use this personal app as a public multi-user service.
5. Clients → Create client → **Desktop app**. Download the JSON, save it as `credentials.json` in this folder. Never upload it to the repository.
6. Run locally:

```powershell
.\.venv\Scripts\python.exe authorize_gmail.py
```

7. In the browser choose your Gmail account and authorize. A private `token.json` file is created. Its JSON includes the refresh token, client ID and client secret. Add its entire contents as the GitHub secret **GMAIL_TOKEN_JSON**.
8. For unattended operation, change the consent app's publishing status from Testing to **In production**, if permitted for your personal-use setup, and authorize again to obtain a fresh token. External apps in Testing normally issue refresh tokens that expire after seven days for Gmail scopes. A personal app may show an unverified-app warning; public distribution can require verification. If you cannot publish the app, expect to reauthorize regularly rather than promising permanent automation. [OAuth token expiration](https://developers.google.com/identity/protocols/oauth2#expiration).

The script refreshes short-lived access tokens automatically. Revoked refresh tokens require running authorization again and replacing the GitHub secret. Do not paste credentials into this chat. For local runs the program reads `token.json` automatically; you can leave `GMAIL_TOKEN_JSON` blank in `.env`.

## 5. Gmail App Password (send your digest)

1. Google Account → Security → enable **2-Step Verification**.
2. Open [App Passwords](https://myaccount.google.com/apppasswords).
3. Create an app password named `Daily Job Alerts`.
4. Store the 16-character value as **GMAIL_APP_PASSWORD**. Use your Gmail address for **GMAIL_USER** and the recipient address for **EMAIL_TO**.

The script connects to `smtp.gmail.com:587` with STARTTLS. The OAuth token above reads alerts; this App Password sends the digest. They are different credentials. App Passwords may be unavailable for managed accounts, Advanced Protection or certain 2-Step configurations. A Google account password change revokes App Passwords. [Google App Password help](https://support.google.com/accounts/answer/185833).

## 6. Label and filter incoming alerts

1. In Gmail sidebar choose **Create new label** → `JobAlerts` (exact spelling).
2. Create the job-platform alerts in section 7 and wait for a real email from each.
3. Open each legitimate alert → More → **Filter messages like these**. Use its actual sender plus an alert-specific subject if that sender also sends non-job mail.
4. Create filter → **Apply the label: JobAlerts**. Optionally apply to matching existing messages. **Do not select Mark as read**: the script reads unread messages only.
5. Repeat for the four sources. Do not label your outgoing digest as `JobAlerts`.

Processed messages become read and receive `JobAlertsProcessed`; the original label remains. They are only marked after SMTP acceptance and saved delivery state. Messages the parser cannot understand remain unread for review. Avoid manually reading alerts before the scheduled run if you want them included.

## 7. Configure alerts manually

Use the nine searches in `config.json`. Platform alert-count limits may require grouping related terms or prioritizing DevOps, Cloud and SRE searches. Interfaces and available filters vary; use only options actually provided by your account.

| Platform | Configure |
|---|---|
| Naukri | Search each role; All India or target cities; experience 0–3 years; create/save a daily email alert. Set profile experience accurately to 2.8+ years. |
| LinkedIn | Jobs search → role + India → Date posted Past 24 hours → Entry level/Associate, and relevant internship roles if wanted → Set alert → daily email. Create separate country and Remote searches. LinkedIn experience levels are categories, not exact numeric years; the code parses numeric requirements when available. |
| Foundit | Search role + India → 0–3 years wherever a numeric experience filter exists → save/create email alert, daily if offered. Repeat for target country editions only where supported. |
| Instahyre | Complete profile, real experience 2.8+ years, DevOps/cloud skills, India cities and remote preferences; enable available opportunity emails. Do not assume it offers a daily keyword-search alert or custom 0–3 range: matching notifications depend on the account/UI. |

For international searches use USA, UK, Canada, Germany, Netherlands, UAE, Singapore and Australia separately. Add worldwide remote searches where available. Search terms: **DevOps Engineer, Cloud Engineer, AWS Engineer, AWS DevOps, Cloud DevOps, Site Reliability Engineer / SRE, Platform Engineer, Kubernetes Engineer, Cloud Infrastructure Engineer**.

The parser handles numeric ranges in structured card fields first, otherwise title and card description. Real source snippets may omit requirements; those jobs show `Experience: Not specified`. Full descriptions are never fetched from restricted job sites.

## 8. Optional API keys and free request limits

### Adzuna

Register at [Adzuna developer portal](https://developer.adzuna.com/), obtain your app ID and key, and check the account's approved free usage/attribution terms. Add **ADZUNA_APP_ID** and **ADZUNA_APP_KEY**. Official authentication and endpoint information: [Adzuna overview](https://developer.adzuna.com/overview).

Default configuration makes up to 72 requests/day: nine keywords × eight supported country candidates × one page. Reduce country/keyword lists or leave Adzuna disabled if your approved quota does not cover this. UAE is covered through JSearch/alerts rather than assuming Adzuna supports it. Country availability can change; source failures appear in the digest. The script makes no automatic paid-plan upgrades. Adzuna's `created` is the date supplied by its API, which may be board ingestion rather than the employer's first publication.

### JSearch on RapidAPI

1. Open [JSearch](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch).
2. Check Pricing and select a **$0 subscription only if available**, with paid overage disabled or a hard stop enforced by your account/provider. If that cannot be guaranteed, leave JSearch disabled.
3. Copy the `X-RapidAPI-Key` for your app as **JSEARCH_API_KEY**.
4. Set GitHub **variable** `JSEARCH_MONTHLY_LIMIT` to your verified free request count. Use 0 to disable. For example, **only if your plan actually permits 100 requests/month**, set 100.

Code makes at most two JSearch requests/day (up to 62 in a 31-day month) and rotates the 81 keyword/country pairs. This is quota-efficient but does not query every keyword in every country daily. Gmail alerts complement it. A full nine-keyword × nine-country daily search costs at least 2,511 requests/month before pagination; it cannot be promised within an unspecified free tier.

Reservations are stored before requests, including failed requests. Provider billing periods may differ from UTC calendar months; set the local cap below the available allowance and rely on the provider's hard stop as the final guard. Other apps sharing the API key consume the same allowance. Live dry-runs consume quota too.

### Sources requiring no API key

Remotive, Remote OK, Himalayas and WWR public RSS. Source names and original listing links are included as attribution. [Remote OK API](https://remoteok.com/api), [Himalayas terms](https://github.com/Himalayas-App/remote-jobs-api#attribution-and-terms-of-use), [WWR RSS information](https://weworkremotely.com/remote-job-rss-feed). The feeds may be truncated or delayed; this is an aggregation aid, not guaranteed exhaustive coverage.

## 9. GitHub setup and secrets

Create an empty **private** GitHub repository. Push these files using GitHub Desktop or Git. From this folder, replacing the URL:

```powershell
git add .
git commit -m "Build daily job alert system"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/job-alerts.git
git push -u origin main
```

If `origin` already exists, use the existing remote or explicitly change it rather than running `remote add` again. These commands are setup instructions; no remote has been created by this build.

Repository → Settings → Secrets and variables → Actions → **New repository secret**:

| Secret | Value |
|---|---|
| `GMAIL_USER` | Sending Gmail address |
| `EMAIL_TO` | Recipient email address |
| `GMAIL_APP_PASSWORD` | Gmail App Password |
| `GMAIL_TOKEN_JSON` | Entire private `token.json` JSON |
| `ADZUNA_APP_ID` | Optional Adzuna ID |
| `ADZUNA_APP_KEY` | Optional Adzuna key |
| `JSEARCH_API_KEY` | Optional RapidAPI key |

In **Variables**, optionally set `JSEARCH_MONTHLY_LIMIT`, `DATE_POLICY` (`strict` or `alert_received`), and `GMAIL_ENABLED` (`true` or `false`). No OAuth secret or password belongs in variables, workflow code or `config.json`.

Actions must be enabled. Allow the workflow's `contents: write` permission; the default branch must permit bot commits to `data/state.json`. Use a dedicated repository if branch protection prevents this. Without successful state pushes, future runs can resend jobs and exceed the local API request budget.

The included workflow has `30 2 * * *`, serial concurrency, manual dry-run, tests, short-lived preview artifacts, and an `always()` state-persistence step. Keep `data/state.json` committed. Do not reset it to empty unless you intentionally want to forget delivered jobs. State contains hashes and Gmail message IDs, not credentials or email bodies. Keep the repository private.

## 10. Experience, dates and duplicate rules

- Exclude senior title/structured seniority: Senior, Sr., Lead, Principal, Staff, Architect, Manager, Head, Director.
- Include 0–1, 0–2, 0–3, 1–3, 2–3, 1–4, 2–5 and up to 3 years; include fresher/junior/associate/trainee/Engineer I/II.
- Exclude numeric minimum over 3. Your examples conflict: **3–5 is explicitly excluded**, while 1–4 and 2–5 are included. Exactly 3 or 3+ is included under your “minimum above 3” rule; change tests/code if you want 3+ excluded too.
- Structured experience wins over regex. Otherwise all detected numeric requirements in the available description are checked conservatively. Regex is not language understanding: company-age text, preferred requirements, spelled-out numbers and complex alternatives can need adaptation.
- Unknown experience is included only when the title/structured seniority is not excluded. Every digest card shows the experience value.
- Keywords are checked in the title, so a generic software developer mentioning AWS in the description does not pass. Closely related infrastructure, DevSecOps, production and release/build engineering roles also pass; sales/marketing titles are excluded.
- Strict freshness: source timestamp must fall in `[run time minus 24 hours, run time]`. Date-only values are interpreted at midnight UTC; this is an approximation from limited source data, not precise publication proof. Jobs without any parseable date are held out. A delayed scheduler or skipped day can miss openings outside that strict window.
- Dedupe uses normalized title + company + canonical apply/source URL plus source IDs where supplied. UTM/tracking fragments are removed for comparison. Different tracking redirects or independent board URLs for the same employer job may still appear twice: cross-board identity cannot be guaranteed without matching employer IDs. Original links are preserved in the digest.
- Email notices distinguish incomplete source coverage from a genuine empty result. A clean empty result says “No new jobs today.”

**Delivery guarantee:** seen IDs are saved only after SMTP accepts the digest. There is no universal exactly-once transaction between SMTP, Gmail labels and GitHub commits. If SMTP accepts an email and the process crashes before state saves/pushes, retry may resend it. Automatic SMTP retries are deliberately not used. Check Sent mail and workflow state after an ambiguous failure before rerunning. This limitation also applies to the n8n send/commit boundary.

## 11. Test manually

Fill local `.env` with Gmail user, recipient and App Password; authorize OAuth as above. Optional API credentials can remain blank.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe job_alerts.py --demo
.\.venv\Scripts\python.exe job_alerts.py --dry-run
Start-Process .\preview.html
```

`--demo` is offline, does not send or change state. `--dry-run` fetches real sources and creates preview; it does not send or mark Gmail, but persists JSearch request reservations because real calls count. Before live use inspect each platform's parsed company, location, experience, timestamp and link. Unknown fields are labelled; skipped/unparsed messages need template adaptation in `parse_alert()`.

To send for real:

```powershell
.\.venv\Scripts\python.exe job_alerts.py
```

On GitHub: Actions → Daily job alerts → Run workflow → leave `dry_run` checked → inspect logs and download preview artifact. Once verified, run again with `dry_run` unchecked to send. Scheduled runs always send. Commit any local delivery/budget changes before switching to GitHub. Use exactly one scheduler; running local/n8n/GitHub writers concurrently is unsupported.

## 12. Troubleshooting

| Symptom | Fix |
|---|---|
| Python not found | Install Python/launcher; use `py -3.12` on Windows, or explicit venv path |
| SMTP 535 / authentication failed | Check Gmail address and App Password, remove spaces, enable 2-Step; recreate password if revoked |
| OAuth `invalid_grant` | Refresh token expired/revoked; publish personal consent app if possible, reauthorize, replace secret |
| OAuth access denied | Add yourself as test user, enable Gmail API, check consent/client/scopes |
| Gmail missing label | Create exactly `JobAlerts`; make sure OAuth authorized the same Gmail account |
| Gmail alerts absent | Ensure label and unread status; disable auto-mark-as-read filter; verify sender filter |
| Alert remains unread | Parser did not recognize cards or strict mode lacks posting dates; inspect a private sample and adapt parser, or consciously enable labelled date fallback |
| Very few jobs | Strict 24h dates, senior/experience/geography filters, feed delays or bounded pagination; inspect source notices |
| 401/403 on provider | Wrong API key, missing subscription, country restrictions or quota; verify provider dashboard |
| 429 | Free quota/rate exceeded; lower pages/country lists/request cap; do not upgrade automatically |
| State push rejected | Enable contents-write permissions and permit bot branch commits; don't rerun an ambiguous delivery until checking Sent mail |
| No 08:00 run | Default branch missing workflow, Actions disabled, schedule delay/inactivity restriction; use manual workflow |
| Source warnings | Partial failures still produce an email; check provider status/configuration. The log omits credential-bearing request URLs |

See [`n8n/README.md`](n8n/README.md) for the Docker alternative and exact node settings.
