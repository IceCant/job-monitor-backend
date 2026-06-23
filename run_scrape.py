"""Standalone runner to execute a scrape end-to-end and print the results.

Run from the `backend/` directory:

    python run_scrape.py
    python run_scrape.py --plugin nrf

This bypasses the DB so you can confirm the scraping pipeline works on its own.
"""

import argparse
import asyncio

from app.plugins.registry import get_firm_definition, list_firm_definitions
from app.services.scraper_service import run_firm


def parse_args():
    parser = argparse.ArgumentParser(description="Run a single firm scrape.")
    parser.add_argument("--plugin", default="nrf")
    parser.add_argument("--list", action="store_true", help="List available firm plugins and exit")
    return parser.parse_args()


async def main():
    args = parse_args()

    if args.list:
        for firm in list_firm_definitions(include_disabled=True):
            print(f"- {firm.key}: {firm.name} (enabled={firm.enabled})")
        return

    firm = get_firm_definition(args.plugin)

    print(f"Scraping '{firm.name}' via plugin '{firm.key}'...")
    jobs = await run_firm(firm)
    print(f"\nScraped {len(jobs)} job(s).\n")

    for job in jobs[:10]:
        title = job.title or (job.extra_info or {}).get("title", "(no title)")
        print(f"  - {title}")
        print(f"      {job.office_location} | {job.status}")
        print(f"      {job.job_url}")

    if len(jobs) > 10:
        print(f"\n  ...and {len(jobs) - 10} more.")


if __name__ == "__main__":
    asyncio.run(main())
