"""Standalone runner to execute a scrape end-to-end and print the results.

Run from the `backend/` directory:

    python run_scrape.py
    python run_scrape.py --api-url <workday-cxs-jobs-url> --careers-url <careers-url>

This bypasses the DB so you can confirm the scraping pipeline works on its own.
"""

import argparse
import asyncio
from types import SimpleNamespace

from app.services.scraper_service import run_firm


# A real, public Workday job board used as a default so the scraper has
# something to hit out of the box (capped to a single page for safety).
DEFAULT_API_URL = (
    "https://nrf.wd3.myworkdayjobs.com/wday/cxs/nrf/External/jobs"
)
DEFAULT_CAREERS_URL = (
    "https://nrf.wd3.myworkdayjobs.com/External"
)

def parse_args():
    parser = argparse.ArgumentParser(description="Run a single firm scrape.")
    parser.add_argument("--name", default="WorkDay")
    parser.add_argument("--plugin", default="workday")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--careers-url", default=DEFAULT_CAREERS_URL)
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Limit Workday pagination (20 jobs/page). Use 0 for unlimited.",
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    firm = SimpleNamespace(
        name=args.name,
        plugin=args.plugin,
        plugin_config={
            "api_url": args.api_url,
            "careers_url": args.careers_url,
            "max_pages": args.max_pages or None,
        },
    )

    print(f"Scraping '{firm.name}' via plugin '{firm.plugin}'...")
    jobs = await run_firm(firm)
    print(f"\nScraped {len(jobs)} job(s).\n")

    for job in jobs[:10]:
        title = (job.extra_info or {}).get("title", "(no title)")
        print(f"  - {title}")
        print(f"      {job.office_location} | {job.status}")
        print(f"      {job.job_url}")

    if len(jobs) > 10:
        print(f"\n  ...and {len(jobs) - 10} more.")


if __name__ == "__main__":
    asyncio.run(main())
