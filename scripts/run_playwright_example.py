import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.plugins.sample.playwright_example import PlaywrightExamplePlugin  # noqa: E402


HTML = """
<div class='job-card'>
  <a href='/jobs/101'>
    <h2>Litigation Associate</h2>
  </a>
  <div class='location'>Melbourne</div>
  <div class='practice-area'>Disputes</div>
  <div class='pqe'>3-5 PQE</div>
  <div class='description'>Work on major commercial disputes.</div>
  <div data-job-id='PLAY-101'></div>
</div>
<div class='job-card'>
  <a href='/jobs/102'>
    <h2>Corporate Lawyer</h2>
  </a>
  <div class='location'>Sydney</div>
  <div class='practice-area'>Corporate</div>
  <div class='pqe'>2-4 PQE</div>
  <div class='description'>Advisory and transactions.</div>
  <div data-job-id='PLAY-102'></div>
</div>
"""


async def main() -> None:
    plugin = PlaywrightExamplePlugin(
        firm_name="Playwright Demo Firm",
        plugin_config={
            "start_url": "https://example.com/careers",
            "html": HTML,
            "card_selector": ".job-card",
            "title_selector": "h2",
            "link_selector": "a",
            "location_selector": ".location",
            "practice_selector": ".practice-area",
            "pqe_selector": ".pqe",
            "description_selector": ".description",
            "reference_selector": "[data-job-id]",
            "headless": True,
        },
    )

    jobs = await plugin.scrape()
    print(f"Scraped {len(jobs)} jobs")
    for job in jobs:
        print(job["title"], "->", job["job_url"])


if __name__ == "__main__":
    asyncio.run(main())

