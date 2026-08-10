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
