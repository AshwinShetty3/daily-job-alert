# Self-hosted n8n alternative (Docker)

Use this instead of GitHub Actions if you already have a computer that stays on. The n8n community self-hosted software can run without a cloud subscription; hardware, electricity and internet are not literally free. Do not run this and GitHub simultaneously against the same delivery state.

This version uses native n8n scheduling, HTTP, Merge, Filter, Remove Duplicates, Code and SMTP nodes. A small private Python worker supplies the source adapters and identical experience/date rules. This avoids having two different interpretations of your experience filter. Both zero-job and partial-source-failure emails are handled.

Official references: [n8n Docker installation](https://docs.n8n.io/hosting/installation/docker/), [Schedule Trigger](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.scheduletrigger/), [Gmail Trigger](https://docs.n8n.io/integrations/builtin/trigger-nodes/n8n-nodes-base.gmailtrigger/), [Remove Duplicates](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.removeduplicates/).

## Start Docker

1. Install Docker Desktop, start its engine, and check `docker version`. Use the free personal-use tier only if eligible.
2. In this project's root folder:

```powershell
Copy-Item n8n/.env.example n8n/.env
# Generate two independent values; paste into N8N_ENCRYPTION_KEY and WORKER_SECRET.
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32)); print(secrets.token_hex(32))"
```

3. Edit `n8n/.env`. Add the OAuth JSON obtained from the main README as one line, surrounded with single quotes in the env file:

```dotenv
GMAIL_TOKEN_JSON='{"token":"...","refresh_token":"...","token_uri":"https://oauth2.googleapis.com/token","client_id":"...","client_secret":"...","scopes":["https://www.googleapis.com/auth/gmail.modify"]}'
```

Use the actual entire `token.json`, not the example values. Add optional API keys and a verified JSearch free cap. `GMAIL_ENABLED=false` can disable inbox reading for an initial source-only test.

4. Start from the project root:

```powershell
docker compose -f n8n/compose.yml up -d --build
```

5. Open [local n8n](http://localhost:5678), create your owner account. The port is bound to localhost; the worker has no published host port. Keep `N8N_ENCRYPTION_KEY` unchanged so existing stored credentials remain readable. Preserve the Docker volume and `data/` folder. The image uses the stable release channel; after testing, pin the image tag/digest to the installed version if you want reproducible deployments.

6. Create an **HTTP Header Auth** credential: header name `X-Worker-Secret`, value matching `WORKER_SECRET`. Select it in every worker HTTP node. Store the Gmail App Password in n8n's SMTP credential, not a Code node or JSON.

No Docker commands were run during this build. Node settings below are copy-ready instructions rather than a version-specific imported workflow export.

## Daily digest workflow: node by node

Set Workflow Settings → timezone **Asia/Kolkata**. Save/publish the workflow after the manual test succeeds. Limit it to one active execution; don't schedule overlapping runs or manually execute during a live run. The HTTP server processes requests serially, but multiple digest executions can still race before delivery commits.

### 1. Schedule Trigger

Every day, hour **8**, minute **0**. Alternatively custom cron `0 8 * * *` in Asia/Kolkata. Connect a Manual Trigger to the same source nodes for initial testing. Docker timezone variables are also set in `compose.yml`.

### 2. Seven HTTP Request source nodes

Each is **POST**, Authentication → Generic Credential → Header Auth → the worker credential. Send JSON body `{}`. Response format JSON. Set timeout **900000 ms** so paginated adapters have time to finish. Run at most once per day; these endpoints make real provider requests.

| Node name | URL |
|---|---|
| Remotive | `http://worker:8000/source/remotive` |
| Remote OK | `http://worker:8000/source/remoteok` |
| Himalayas | `http://worker:8000/source/himalayas` |
| WWR | `http://worker:8000/source/wwr` |
| Adzuna | `http://worker:8000/source/adzuna` |
| JSearch | `http://worker:8000/source/jsearch` |
| Gmail alerts | `http://worker:8000/source/gmail` |

Connect Schedule Trigger to all seven. Each returns one envelope `{jobs: [], warnings: [], message_ids: []}` even if the provider has no jobs or fails. A worker connection failure stops the workflow; do not continue to SMTP when the worker itself is unavailable.

Gmail uses the same OAuth refresh token and unread `JobAlerts` polling as Python. It extracts HTML cards; it doesn't scrape the linked pages.

### 3. Merge

Mode **Append**, inputs **7**, connect all source responses. If your n8n version only permits two inputs, chain six Append Merge nodes. This merges seven envelopes in a single scheduled execution.

### 4. Code — Collect sources

Run Once for All Items:

```javascript
return [{json: {sources: $input.all().map(item => item.json)}}];
```

### 5. HTTP Request — Classify keyword, experience, geography and date

POST `http://worker:8000/filter`, worker Header Auth, JSON body via expression:

```javascript
={{ $json }}
```

Returns `{items: [...]}`. Numeric structured fields win; unavailable numeric experience falls back to regex; senior roles and dates outside the window are rejected. It adds one metadata sentinel per source to preserve source notices and Gmail IDs even when every job is rejected.

### 6. Code — Expand classified items

Run Once for All Items:

```javascript
return $input.first().json.items.map(item => ({json: item}));
```

### 7. Filter

Boolean condition: `={{ $json.eligible }}` **is true**. Metadata sentinels pass automatically, so the no-jobs path continues rather than silently ending with zero n8n items.

### 8. Remove Duplicates

Operation **Remove Items Repeated Within Current Input** → Compare **Selected Fields** → field `dedupe_key`. Keep other fields. This removes duplicate title/company/canonical-link jobs within today's input. The worker handles the durable “already emailed” check later.

Do not use n8n's previous-execution dedupe here: it may remember jobs before SMTP succeeds, making failed deliveries disappear on retry. Its history can also be bounded. Durable state must be written **after** successful sending.

### 9. Code — Reassemble for durable delivery preparation

Run Once for All Items:

```javascript
const rows = $input.all().map(i => i.json);
return [{json: {sources: [{
  jobs: rows.filter(r => r.kind === 'job').map(r => r.job),
  warnings: rows.filter(r => r.kind === 'metadata').flatMap(r => r.warnings || []),
  message_ids: rows.filter(r => r.kind === 'metadata').flatMap(r => r.message_ids || []),
}]}}];
```

### 10. HTTP Request — Prepare and check delivered IDs

Name this node exactly **Prepare**. POST `http://worker:8000/prepare`, same Header Auth, JSON body `={{ $json }}`.

Returns one digest containing `token`, `jobs`, `count`, `warnings`, and fully escaped `html`. The worker checks durable seen IDs, repeats the filters defensively, renders India and Outside India / Remote sections, and saves a pending delivery record under `data/pending/`. It has not marked the jobs delivered or the emails processed.

### 11. Code — Format email

Run Once for All Items. Paste `format-email.js`:

```javascript
const digest = $input.first().json;
return [{json: {
  ...digest,
  subject: digest.count ? `DevOps job alert: ${digest.count} new matches`
    : digest.warnings.length ? 'Job alert: no new matches; coverage incomplete'
    : 'No new jobs today',
  html: digest.html,
}}];
```

The HTML itself is produced by `digest()` in the shared Python module; this Code node sets the subject and passes it to SMTP. It contains every requested field and source attribution.

### 12. Send Email (SMTP)

Credential: host `smtp.gmail.com`, port `587`, user your Gmail address, password the App Password, SSL/TLS off for implicit TLS, STARTTLS enabled/required where offered. Do not enable insecure certificate acceptance. Gmail with implicit TLS on port 465 is also supported by n8n if its SMTP UI does not expose STARTTLS settings.

From: your Gmail address. To: your recipient. Subject `={{ $json.subject }}`. Email format HTML. Body `={{ $json.html }}`. Keep **Continue On Fail disabled** and **Retry On Fail disabled**: ambiguous SMTP acceptance must be inspected before retrying. Enable **Always Output Data** if the node/version otherwise returns no output after successful send.

During initial setup disconnect this node and inspect the generated HTML first. Reconnect only when ready to send.

### 13. HTTP Request — Commit delivery and process Gmail

Connect only the successful SMTP output here. POST `http://worker:8000/commit`, worker Header Auth. JSON body expression:

```javascript
={{ { token: $('Prepare').first().json.token } }}
```

This stores seen IDs, records processed messages, then marks the Gmail alerts read/adds `JobAlertsProcessed`. In this version JSON state is kept on the Docker host in `data/state.json`; it does not require GitHub commits. Back it up. For an acknowledgement failure after state was saved, repeat **Commit only** with the same token, not the entire send workflow.

## Gmail Trigger: use a separate ingestion workflow

Schedule Trigger and Gmail Trigger start **different executions**. Directly connecting both to a Merge node does not buffer emails until 08:00 and can send digests at arbitrary times. Keep the daily workflow above as the sole sender.

An optional second workflow can add alerts to the Gmail queue:

1. Create Gmail OAuth2 credentials in n8n. In Google Cloud, create a **Web application** OAuth client for this integration and copy the redirect URL shown in n8n into its authorized redirect URIs. This is separate from the Python Desktop client. Request the Gmail permissions needed by the Gmail Trigger and label action; follow the publishing/refresh-token guidance in the main README.
2. **Gmail Trigger** → poll every minute or hour, filter using the actual verified platform sender addresses (collect from your own messages) and alert subjects. Keep Simplify enabled if only IDs are required. Restrict to unread messages as appropriate. Do not mark them read.
3. **Gmail node → Message → Add Label** → message ID `={{ $json.id }}`, label `JobAlerts`. Disable any option that marks the message read.
4. Save/publish. No SMTP node in this ingestion workflow. The daily `/source/gmail` adapter reads the accumulated queue at 08:00.

This optional workflow replaces or complements Gmail's own labeling filters. If your Gmail filters already add `JobAlerts`, no Gmail Trigger is needed for reliable daily aggregation. Gmail itself is the durable queue, so n8n need not store private raw email bodies in a second database.

The resulting topology is:

```text
Gmail Trigger → Gmail Add Label → unread JobAlerts inbox queue

Schedule 08:00 → HTTP APIs/RSS + HTTP Gmail queue reader
              → Merge → Code collect → HTTP classify → Code expand
              → Filter → Remove Duplicates (current input)
              → Code reassemble → HTTP Prepare (durable dedupe + HTML)
              → Code email → SMTP → HTTP Commit
```

## Test and troubleshoot

- Execute manually with SMTP disconnected, inspect source envelopes and filtered jobs, then inspect Prepare HTML. Unknown dates remain excluded in strict mode.
- Empty source results still produce metadata sentinels and one no-jobs digest. Source outages produce an incomplete-coverage notice.
- For Docker errors: `docker compose -f n8n/compose.yml logs --tail 100 worker n8n`. Don't post tokens or passwords from environment/configuration.
- 403 from worker: Header Auth secret does not match `WORKER_SECRET`.
- SMTP failure: no Commit call should happen. Fix credentials, inspect Sent mail if acceptance was ambiguous, then retry only after checking delivery.
- Commit failure: inspect `data/state.json` and pending token file, retry only Commit. Never delete seen state to fix unrelated failures.
- No scheduled run: computer sleeping/off, Docker stopped, workflow unpublished, wrong timezone, or execution still in progress.
- Pending files from previews/failed sends can be cleaned up after review; keep any record needed to repair an ambiguous delivery. They are ignored by Git.
- Exactly-once delivery is not guaranteed across SMTP and state persistence. The same crash-window limitation described in the main README applies.

Do not enable both this workflow and GitHub Actions. They would have independent or conflicting delivery state and quota accounting.
