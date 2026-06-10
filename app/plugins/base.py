# app/plugins/base.py

from abc import ABC, abstractmethod

class BasePlugin(ABC):

    @abstractmethod
    async def scrape(self):
        pass