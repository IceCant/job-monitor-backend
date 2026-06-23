from __future__ import annotations

import importlib
import inspect
import pkgutil
from dataclasses import dataclass
from typing import Any

from app.plugins import __path__ as plugins_path
from app.plugins.base import BasePlugin


@dataclass(frozen=True)
class FirmDefinition:
    key: str
    name: str
    enabled: bool
    careers_url: str | None
    description: str
    required_config: list[str]
    default_config: dict[str, Any]
    plugin_class: type[BasePlugin]


def _discover_plugins() -> dict[str, type[BasePlugin]]:
    plugin_map: dict[str, type[BasePlugin]] = {}

    for module_info in pkgutil.iter_modules(plugins_path):
        module_name = module_info.name
        if module_name in {"base", "registry"}:
            continue

        module = importlib.import_module(f"app.plugins.{module_name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if not issubclass(obj, BasePlugin) or obj is BasePlugin:
                continue
            if getattr(obj, "discoverable", True) is False:
                continue
            key = getattr(obj, "plugin_name", None) or module_name
            plugin_map[key] = obj

    return plugin_map


PLUGIN_MAP = _discover_plugins()


def get_plugin_class(plugin_key: str) -> type[BasePlugin]:
    plugin_class = PLUGIN_MAP.get(plugin_key)
    if plugin_class is None:
        available = ", ".join(sorted(PLUGIN_MAP.keys()))
        raise ValueError(f"Unknown plugin '{plugin_key}'. Available: {available}")
    return plugin_class


def get_firm_definition(plugin_key: str) -> FirmDefinition:
    plugin_class = get_plugin_class(plugin_key)
    return FirmDefinition(
        key=plugin_key,
        name=getattr(plugin_class, "display_name", plugin_key),
        enabled=bool(getattr(plugin_class, "enabled", True)),
        careers_url=getattr(plugin_class, "careers_url", None),
        description=getattr(plugin_class, "description", "") or "",
        required_config=list(getattr(plugin_class, "required_config", []) or []),
        default_config=dict(getattr(plugin_class, "default_config", {}) or {}),
        plugin_class=plugin_class,
    )


def list_firm_definitions(include_disabled: bool = True) -> list[FirmDefinition]:
    firms = [get_firm_definition(key) for key in sorted(PLUGIN_MAP.keys())]
    if include_disabled:
        return firms
    return [firm for firm in firms if firm.enabled]


def list_plugins() -> list[dict[str, object]]:
    return [
        {
            "key": key,
            "name": getattr(cls, "display_name", key),
            "class_name": cls.__name__,
            "enabled": bool(getattr(cls, "enabled", True)),
            "careers_url": getattr(cls, "careers_url", None),
            "description": getattr(cls, "description", "") or "",
            "required_config": getattr(cls, "required_config", []) or [],
            "default_config": getattr(cls, "default_config", {}) or {},
        }
        for key, cls in sorted(PLUGIN_MAP.items(), key=lambda x: x[0])
    ]
