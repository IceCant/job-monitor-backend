import argparse
import asyncio
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.plugins.registry import get_firm_definition, list_firm_definitions  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one plugin directly and print JSON output.")
    parser.add_argument("plugin", nargs="?", help="Plugin key (firm key), e.g. workday")
    parser.add_argument("--list", action="store_true", help="List plugin keys and exit")
    parser.add_argument("--config", help="Inline JSON object to merge into default_config")
    parser.add_argument("--config-file", help="Path to a JSON config file to merge into default_config")
    parser.add_argument("--firm-name", help="Override display firm name for test output")
    parser.add_argument("--limit", type=int, default=5, help="How many rows to print in terminal preview")
    parser.add_argument("--out", help="Write full JSON results to file")
    return parser.parse_args()


def _load_json_file(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("config file must contain a JSON object")
    return data


def _to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if is_dataclass(item):
        return asdict(item)
    if hasattr(item, "__dict__"):
        return dict(item.__dict__)
    return {"value": str(item)}


async def main() -> None:
    args = parse_args()

    if args.list:
        for firm in list_firm_definitions(include_disabled=True):
            print(f"- {firm.key}: {firm.name} (enabled={firm.enabled})")
        return

    if not args.plugin:
        raise SystemExit("Missing plugin key. Use --list to see available plugins.")

    firm = get_firm_definition(args.plugin)
    plugin_class = firm.plugin_class

    config = dict(plugin_class.default_config or {})
    if args.config_file:
        config.update(_load_json_file(args.config_file))
    if args.config:
        inline = json.loads(args.config)
        if not isinstance(inline, dict):
            raise ValueError("--config must be a JSON object")
        config.update(inline)

    plugin = plugin_class(
        firm_name=args.firm_name or firm.name,
        plugin_config=config,
        careers_url=firm.careers_url,
        **config,
    )

    raw_results = await plugin.scrape()
    results = [_to_dict(item) for item in raw_results]

    print(f"\nPlugin: {firm.key}")
    print(f"Firm Name: {args.firm_name or firm.name}")
    print(f"Found {len(results)} jobs\n")

    preview_limit = max(1, args.limit)
    for row in results[:preview_limit]:
        print(json.dumps(row, indent=2, ensure_ascii=False, default=str))
        print("-" * 80)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False, default=str)
        print(f"Saved full JSON output to {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
