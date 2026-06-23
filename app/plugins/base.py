from abc import ABC, abstractmethod
from typing import Any


class BasePlugin(ABC):
    """Base contract for all scraper plugins."""

    # Human/API key used to identify the firm scraper, e.g. "nrf".
    plugin_name = "base"
    display_name = "Base Plugin"
    discoverable = True
    enabled = True
    careers_url: str | None = None
    # Optional description and config key hints shown in plugin listing API.
    description = ""
    required_config: list[str] = []
    default_config: dict[str, Any] = {}

    def __init__(self, firm_name: str, plugin_config: dict[str, Any] | None = None, **kwargs: Any):
        self.firm_name = firm_name
        self.plugin_config = plugin_config or {}
        # Keep kwargs so plugins can opt into direct named params if desired.
        self.kwargs = kwargs

    @abstractmethod
    async def scrape(self) -> list[Any]:
        """Return jobs as JobResult objects or dicts with the JobResult shape."""
