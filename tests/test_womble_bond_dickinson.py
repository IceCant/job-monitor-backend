import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from app.plugins.womble_bond_dickinson import (
    WombleBondDickinsonPlugin,
    WombleBondDickinsonScrapeError,
)


class WombleBondDickinsonPluginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = WombleBondDickinsonPlugin(
            firm_name="Womble Bond Dickinson",
            plugin_config=dict(WombleBondDickinsonPlugin.default_config),
        )

    def test_uses_browser_when_http_scrape_is_empty(self) -> None:
        expected = [{"source_reference": "1374"}]
        self.plugin._scrape_with_requests = Mock(
            side_effect=WombleBondDickinsonScrapeError("no rows")
        )
        self.plugin._scrape_with_browser = AsyncMock(return_value=expected)

        results = asyncio.run(self.plugin.scrape())

        self.assertEqual(expected, results)
        self.plugin._scrape_with_browser.assert_awaited_once()

    def test_reports_both_failures(self) -> None:
        self.plugin._scrape_with_requests = Mock(
            side_effect=WombleBondDickinsonScrapeError("HTTP no rows")
        )
        self.plugin._scrape_with_browser = AsyncMock(
            side_effect=WombleBondDickinsonScrapeError("browser blocked")
        )

        with self.assertRaisesRegex(
            WombleBondDickinsonScrapeError,
            "HTTP no rows.*browser blocked",
        ):
            asyncio.run(self.plugin.scrape())

    def test_browser_grid_url_preserves_pagestamp_and_adds_layout(self) -> None:
        url = self.plugin._browser_grid_url(
            "https://jobs.wbd-uk.com/jobs/vacancy/find/results/",
            "/jobs/vacancy/find/results/ajaxaction/posbrowser_gridhandler/"
            "?pagestamp=abc-123",
        )

        self.assertIn("pagestamp=abc-123", url)
        self.assertIn("pageWidthInput=1440", url)
        self.assertIn("inDialog=false", url)


if __name__ == "__main__":
    unittest.main()
