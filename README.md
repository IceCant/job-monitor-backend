# job-monitor-backend

## Run

Default DB is PostgreSQL via `DATABASE_URL`.

```bash
export DATABASE_URL="postgresql+psycopg2://postgres:postgres@localhost:5432/jobmonitor"
```

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
hypercorn app.main:app --reload --bind 127.0.0.1:8000
```

## Plugin System

- One plugin class = one firm
- Add plugin files in `app/plugins/`
- Create a class extending `BasePlugin` with a unique `plugin_name`
- Set `display_name` and `enabled = True/False` in Python
- Implement `async scrape()` and return `JobResult` list (or dicts with matching fields)
- Plugins are auto-discovered and shown in the Firms page/API without creating DB firm rows
- Legacy `firms` table is not required for normal operation

## Job History

Each job record has lifecycle timestamps, while event history is stored in `job_changes`:

- `first_seen`
- `last_seen`
- `removed_at`
- `status`
- `full_description`

Statuses used by the backend:

- `NEW`
- `LIVE`
- `UPDATED`
- `REMOVED`
- `REPOSTED`
- `NEEDS_REVIEW`

Important behavior:

- Removed jobs stay in the database
- Failed scrapes do not mark jobs as removed
- Matching is optimized with indexed lookup maps, not naive compare-everything loops

Useful endpoints:

- `GET /api/scraper/plugins` to list discovered plugins
- `POST /api/scraper/run` to run all or a single firm scrape
- `GET /api/jobs/{job_id}` to see full description and change history

See `app/plugins/README.md` for a template plus:

- `json_example` (returns JSON dict rows)
- `bs4_example` (scrapes HTML with BeautifulSoup)

## Smoke Test

```bash
python3 -u scripts/smoke_test_scrape_history.py
```
