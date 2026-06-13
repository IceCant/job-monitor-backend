# Scraper Plugin Guide

Each plugin class is one firm.

Drop a new Python file in `backend/app/plugins/` and define a class that extends `BasePlugin`.

## Contract

- Set `plugin_name` (the stable firm key)
- Set `display_name` (the label shown in the UI)
- Set `enabled = True` or `False` directly in Python
- Optionally set `careers_url`, `default_config`, and `required_config`
- Implement `async def scrape(self)`
- Return a list of either:
  - `JobResult` objects, or
  - dictionaries with `JobResult` fields (`job_url`, `firm_name`, etc.)
- Include as much detail as possible: title, description, reference/job id, location, practice area, PQE

## Minimal Example

```python
from app.plugins.base import BasePlugin
from app.schemas.job_result import JobResult


class MyFirmPlugin(BasePlugin):
    plugin_name = "my_firm"
    display_name = "My Firm"
    enabled = True
    description = "My firm career site scraper"
    required_config = ["jobs_api"]
    default_config = {"jobs_api": "https://example.com/api/jobs"}

    async def scrape(self):
        api_url = self.plugin_config["jobs_api"]
        # fetch and parse your jobs here...
        return [
            JobResult(
                job_url="https://example.com/job/123",
                firm_name=self.firm_name,
                title="Associate",
                office_location="Melbourne",
                practice_area="Corporate",
                pqe_level="3-5",
                description="Full job description here",
                source_reference="REF-123",
                status="LIVE",
                extra_info={"source": "my_firm"},
            )
        ]
```

## How Firms Work Now

- You do **not** need to create a separate DB firm row for normal usage.
- You generally do **not** need the `firms` table; plugin classes are the source of truth.
- The backend discovers firms by importing plugin classes from `app/plugins/`.
- The firms list in the UI/API comes from those plugin classes.
- Manual run works by `firm_key` / `plugin_name`.
- Disable a firm by changing `enabled = False` in the plugin class.

Plugins are auto-discovered at startup/import time. You can check loaded plugins via `GET /api/scraper/plugins`.

## Test One Plugin Without Running Services

Use the standalone test runner to validate one firm plugin and inspect JSON output directly.

```bash
python3 scripts/test_plugin.py --list
python3 scripts/test_plugin.py playwright_example --limit 3
python3 scripts/test_plugin.py playwright_example --config-file /path/to/config.json --out /tmp/playwright_jobs.json
```

Inline config override example:

```bash
python3 scripts/test_plugin.py playwright_example --config '{"start_url":"https://example.com/careers","headless":true}'
```

## Job Lifecycle Expectations

The backend keeps full job history and does **not** delete removed jobs.

Stored fields include:

- firm
- title
- practice area
- location
- PQE
- job URL
- first seen
- last seen
- removed date
- status
- full description
- change history

Supported statuses:

- `NEW`
- `LIVE`
- `UPDATED`
- `REMOVED`
- `REPOSTED`
- `NEEDS_REVIEW`

If a scrape fails, jobs are **not** marked removed.

## Example 1: JSON-return Plugin

Use plugin key: `json_example`

```json
{
  "plugin": "json_example",
  "plugin_config": {
    "jobs": [
      {
        "job_url": "https://example.com/jobs/1",
        "firm_name": "Example Firm",
        "office_location": "Melbourne",
        "practice_area": "Corporate",
        "pqe_level": "2-4",
        "status": "LIVE",
        "extra_info": {"title": "Associate"}
      }
    ]
  }
}
```

If `jobs` is omitted, it returns built-in sample rows.

## Example 2: BeautifulSoup Plugin

Use plugin key: `bs4_example`

```json
{
  "plugin": "bs4_example",
  "plugin_config": {
    "source_url": "https://example.com/careers",
    "card_selector": ".job-card",
    "title_selector": "h2",
    "location_selector": ".location",
    "link_selector": "a"
  }
}
```

## Example 3: Playwright Plugin (Dynamic Pages)

Use plugin key: `playwright_example`

```json
{
  "plugin": "playwright_example",
  "plugin_config": {
    "start_url": "https://example.com/careers",
    "card_selector": ".job-card",
    "title_selector": "h2",
    "link_selector": "a",
    "location_selector": ".location",
    "practice_selector": ".practice-area",
    "pqe_selector": ".pqe",
    "description_selector": ".description",
    "reference_selector": "[data-job-id]",
    "wait_for_selector": ".job-card",
    "headless": true
  }
}
```

Quick local runner with inline HTML sample:

```bash
python3 -m playwright install chromium
python3 scripts/run_playwright_example.py
```

For local testing without HTTP requests, provide inline HTML:

```json
{
  "plugin": "bs4_example",
  "plugin_config": {
    "source_url": "https://example.com/careers",
    "html": "<div class='job-card'><a href='/jobs/42'><h2>Analyst</h2></a><span class='location'>Sydney</span></div>"
  }
}
```

