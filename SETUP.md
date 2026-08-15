# Google Sheets persistence — one-time setup

Why: Streamlit Cloud rebuilds the app's container from scratch on every
`git push`, and also whenever the app wakes up after going idle. Anything
written only to the container's local disk (the old `session_data.json`)
is lost when that happens. A Google Sheet lives outside the container, so
it survives both. After this setup, the Sheet is the single source of
truth — every add/complete/edit/delete writes straight to it.

Do this once. Takes about 10 minutes.

## 1. Create a Google Cloud project (or use an existing one)

Go to https://console.cloud.google.com/ → create a new project (any name,
e.g. "Barrister Dashboard").

## 2. Enable two APIs

With that project selected, go to **APIs & Services → Library** and enable:
- **Google Sheets API**
- **Google Drive API**

## 3. Create a service account

**APIs & Services → Credentials → Create Credentials → Service account.**
Name it anything (e.g. `barrister-dash`). No roles/permissions needed on
this screen — skip that step. Click Done.

## 4. Create a key for it

Open the service account you just made → **Keys** tab → **Add Key →
Create new key → JSON**. This downloads a `.json` file — this is the
credential. Keep it private; treat it like a password.

Open that file. You'll need several fields out of it in step 7.

## 5. Create the actual Google Sheet

Go to https://sheets.google.com → create a new blank spreadsheet, e.g.
name it **Barrister Live Data**. Leave it empty — the app creates the
`Timeline` and `Pipeline` tabs itself on first load, and auto-fills them
with the current 99 completed / 7 scheduled events as a one-time seed.

Copy the **Spreadsheet ID** out of its URL:
```
https://docs.google.com/spreadsheets/d/THIS_PART_IS_THE_ID/edit
```

## 6. Share the Sheet with the service account

In the downloaded JSON from step 4, find `"client_email"` — it looks like
`barrister-dash@your-project.iam.gserviceaccount.com`.

Back in the Google Sheet, click **Share**, paste that email in, give it
**Editor** access, uncheck "Notify people," and send.

## 7. Add the secrets

You need this same block in two places: the deployed app (Streamlit
Cloud) and your local dev copy (Mac mini), since they're separate
environments.

**On Streamlit Cloud:** open the app → **Settings → Secrets** → paste:

```toml
[gcp_service_account]
type = "service_account"
project_id = "PASTE_project_id_FROM_JSON"
private_key_id = "PASTE_private_key_id_FROM_JSON"
private_key = "PASTE_private_key_FROM_JSON_INCLUDING_BEGIN_END_LINES"
client_email = "PASTE_client_email_FROM_JSON"
client_id = "PASTE_client_id_FROM_JSON"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "PASTE_client_x509_cert_url_FROM_JSON"
universe_domain = "googleapis.com"

[gsheets]
spreadsheet_id = "PASTE_THE_SHEET_ID_FROM_STEP_5"
```

Paste `private_key` exactly as it appears in the JSON, quotes and all —
it contains literal `\n` sequences and TOML parses those correctly as
long as you don't retype or reformat it.

**Locally (Mac mini, for `run_preview.sh`):** create
`.streamlit/secrets.toml` in the project root with the exact same
content. This file is gitignored — it will never get pushed, which is
correct, since it's a credential.

## 8. Deploy

Push this code change (it already has the Sheets integration built in
and gracefully falls back to old local-only behavior if these secrets
aren't set yet, so nothing breaks in the meantime). Once the secrets are
saved and the app reboots, the **first page load** will notice the Sheet
is empty and seed it automatically with the current 99/7 baseline — a
one-time operation, never repeated once the Sheet has rows in it.

## 9. Verify it worked

Add or complete a test event in the app. Open the Google Sheet directly —
the row should appear within a couple seconds. That confirms writes are
live. If instead you see a red banner at the top of the app saying
Sheets isn't connected, double check steps 6 and 7 (sharing + secrets
are the two most common misses).

From here on, the yellow/green "Download Master Workbook" button on the
Events page still works exactly as before — it just now exports whatever
is currently in the Sheet.
