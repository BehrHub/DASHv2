# Barrister Dashboard — CleanDash

Business intelligence dashboard for Barrister's field service career:
career-to-date stats, performance trends, jurisdiction/territory
breakdown, client standings, journey replay, and financial ledger — all
computed from real event data.

## Running locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploying on Streamlit Community Cloud

Point a new Streamlit Cloud app at this repo's `main` branch, with
`app.py` as the entry point. `requirements.txt` is read automatically.

### Important: live-added events and redeploys

Events added or edited through the app (Add Event page) are written to
`session_data.json` on the running container's local disk. This
persists across normal page reloads and user sessions for as long as
that container instance stays up.

**A fresh deploy (new `git push`) rebuilds the container from scratch
and wipes anything in `session_data.json` that wasn't baked into the
committed source data.** Before pushing any code change, export/back
up whatever's been added live since the last deploy first.

## Debugging protocol

When a reported bug doesn't resolve after a fix:

- **Max two rounds of asking the user to check something** (screenshot,
  terminal output, browser refresh) before switching approach entirely.
- **By the third attempt, stop asking and self-diagnose instead.** Pull
  the actual file/output directly and verify against it — don't
  theorize about what might be wrong on the user's end when the actual
  source of truth (the code, the deployed file, the real data) is
  checkable directly.
- **When something partially worked and something didn't, isolate the
  difference precisely** — check exactly which specific file(s) the
  working part touched vs. the non-working part, rather than re-sending
  everything again and hoping.
- Think structurally about what changed (git conflict resolution scope,
  which files were actually included in a fix, deploy timing) instead
  of defaulting to "try a hard refresh" as the first explanation.

## Project structure

```
app.py                    — entry point, page routing, header/nav
components/
  ui.py                   — Main page: ticker, hero card, territory
  trends.py                — Performance Trends chart
  add_event.py             — Events page: upcoming list + add/edit form
  journey.py                — Journey replay timeline
  client_hub.py             — Client Hub: standings + directory
  ledger.py                  — Ledger: financial closeout + monthly breakdown
services/
  data_source.py           — real baked-in event data + session overlay
  metrics.py                — all derived stats/calculations
  local_store.py             — session_data.json read/write
  money_view.py               — Gross/Annualized toggle math
assets/
  styles.css                 — global page styling
```
