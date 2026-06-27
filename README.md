# World Cup 2026 · Live Tracker

A static, auto-updating FIFA World Cup 2026 site — group standings, a full schedule
table, and an interactive knockout bracket with zoom/pan and hover-for-team-details.
Hosted free on **GitHub Pages**; data refreshed automatically by **GitHub Actions**.

## How the "auto-update" works

GitHub Pages only serves static files — it can't poll an API on its own. So:

1. A scheduled GitHub Action (`.github/workflows/update-data.yml`) runs every 15 min.
2. It calls `scripts/update_data.py`, which fetches live standings + results from the
   free, **key-less** worldcup26.ir API.
3. The script rewrites `data/tournament.json` and commits it back to the repo.
4. Pages serves the new JSON; the page re-fetches it every 2 minutes in the browser.

No server, no database, no API key, no hosting cost.

```
GitHub Actions (cron) → worldcup26.ir → writes data/tournament.json → commit
                                                   │
GitHub Pages serves it ── browser fetches every 2 min ── bracket + tables update
```

## Deploy in 5 steps

1. Create a repo and drop these files in at the root.
2. Push. Then **Settings → Pages → Build from branch → `main` / root**.
   Your site is live at `https://<user>.github.io/<repo>/`.
3. **Actions** tab → enable workflows → run **Update World Cup data** once to test.

That's it — no API key or secret to configure. The bracket and tables start
reflecting real results automatically.

## Files

| File | Purpose |
|------|---------|
| `index.html` | The whole site (UI, bracket, zoom/pan, tooltips). No build step. |
| `data/tournament.json` | All data the site reads. Sample values until the fetcher runs. |
| `scripts/update_data.py` | Pulls standings + results, rewrites the JSON. |
| `.github/workflows/update-data.yml` | Cron job that runs the script and commits. |

## Data source

The script targets **worldcup26.ir** — a free, open, **no-key** REST API for WC 2026
(`/get/teams`, `/get/games`). Group standings are computed from finished group matches,
and knockout scores/teams are patched in as rounds complete (winners propagate through
the bracket automatically).

To switch providers, only edit the fetch/mapping functions in `update_data.py`; the JSON
schema stays the same, so `index.html` never changes. Alternatives if needed:

- **football-data.org** — free tier, requires an API key (`FOOTBALL_DATA_TOKEN`).
- **API-Football** — `/standings?league=1&season=2026`; 100 req/day free, key required.

## Notes

- Kickoff times are stored in **UTC** and converted in the browser. The timezone
  picker (top right) covers Bangladesh, Saudi Arabia, UTC, and the visitor's local time.
- Knockout slots show placeholders (`1A`, `W r32-1`, best-third combos) until the
  draw resolves; the fetcher fills real teams + scores as matches finish.
- GitHub's scheduled cron can run a few minutes late under load — fine for this use.
- If you push frequently, the data commits add noise to history; that's expected.
