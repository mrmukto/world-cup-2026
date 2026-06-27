# World Cup 2026 · Live Tracker

A static, auto-updating FIFA World Cup 2026 site — group standings, a full schedule
table, and an interactive knockout bracket with zoom/pan and hover-for-team-details.
Hosted free on **GitHub Pages**; data refreshed automatically by **GitHub Actions**.

## How the "auto-update" works

GitHub Pages only serves static files — it can't poll an API on its own. So:

1. A scheduled GitHub Action (`.github/workflows/update-data.yml`) runs every 30 min.
2. It calls `scripts/update_data.py`, which fetches live standings + results.
3. The script rewrites `data/tournament.json` and commits it back to the repo.
4. Pages serves the new JSON; the page re-fetches it every 2 minutes in the browser.

No server, no database, no hosting cost.

```
GitHub Actions (cron) → Football API → writes data/tournament.json → commit
                                                   │
GitHub Pages serves it ── browser fetches every 2 min ── bracket + tables update
```

## Deploy in 5 steps

1. Create a repo and drop these files in at the root.
2. Push. Then **Settings → Pages → Build from branch → `main` / root**.
   Your site is live at `https://<user>.github.io/<repo>/`.
3. Get a free API key at <https://www.football-data.org/client/register>.
4. **Settings → Secrets and variables → Actions → New repository secret**:
   name `FOOTBALL_DATA_TOKEN`, value = your key.
5. **Actions** tab → enable workflows → run **Update World Cup data** once to test.

That's it. The bracket and tables will start reflecting real results automatically.

## Files

| File | Purpose |
|------|---------|
| `index.html` | The whole site (UI, bracket, zoom/pan, tooltips). No build step. |
| `data/tournament.json` | All data the site reads. Sample values until the fetcher runs. |
| `scripts/update_data.py` | Pulls standings + results, rewrites the JSON. |
| `.github/workflows/update-data.yml` | Cron job that runs the script and commits. |

## Data source options

The script targets **football-data.org** (free, World Cup included, 10 req/min).
To switch providers, only edit the fetch/mapping functions in `update_data.py`:

- **API-Football** — `/standings?league=1&season=2026` returns all 12 group tables; 100 req/day free.
- **worldcup26.ir** — open-source, no auth for the demo endpoints; simplest to wire up.

The JSON schema stays the same regardless of source, so `index.html` never changes.

## Notes

- Kickoff times are stored in **UTC** and converted in the browser. The timezone
  picker (top right) covers Bangladesh, Saudi Arabia, UTC, and the visitor's local time.
- Knockout slots show placeholders (`1A`, `W r32-1`, best-third combos) until the
  draw resolves; the fetcher fills real teams + scores as matches finish.
- GitHub's scheduled cron can run a few minutes late under load — fine for this use.
- If you push frequently, the data commits add noise to history; that's expected.
