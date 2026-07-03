from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def read_local_json(root: Path, relative: str, fallback):
    path = root / relative
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_remote_json(base_url: str, relative: str, fallback):
    url = f"{base_url.rstrip('/')}/{relative}"
    try:
        with urlopen(url, timeout=20) as response:  # noqa: S310 - user-provided public radar URL
            return json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError):
        return fallback


def load_radar(root: str | None, base_url: str | None):
    if base_url:
        brief = read_remote_json(base_url, "data/brief.json", {})
        radar = read_remote_json(base_url, "data/radar.json", [])
        metadata = read_remote_json(base_url, "data/metadata.json", {})
    else:
        repo_root = Path(root or ".").resolve()
        brief = read_local_json(repo_root, "docs/data/brief.json", {})
        radar = read_local_json(repo_root, "docs/data/radar.json", [])
        metadata = read_local_json(repo_root, "docs/data/metadata.json", {})
    return brief or {}, radar if isinstance(radar, list) else [], metadata or {}


def summarize_items(items, limit: int) -> str:
    lines = []
    for index, item in enumerate(items[:limit], start=1):
        why = ", ".join(item.get("why_pick") or [])
        if why:
            why = f" | {why}"
        lines.append(
            f"{index}. {item.get('repo_name')} [{item.get('kind')}/{item.get('category')}] "
            f"score={item.get('recommendation_score')} - {item.get('summary')} {item.get('url')}{why}"
        )
    return "\n".join(lines)


def cmd_read_radar(args) -> int:
    brief, radar, metadata = load_radar(args.root, args.base_url)
    kind = args.kind
    picks = brief.get("top_picks") or []
    if kind != "all":
        picks = [item for item in picks if str(item.get("kind", "")).lower() == kind]

    if not picks:
        picks = [
            {
                "repo_name": item.get("repo_name"),
                "kind": item.get("kind"),
                "category": item.get("category"),
                "recommendation_score": item.get("recommendation_score"),
                "summary": item.get("summary"),
                "url": item.get("url"),
                "why_pick": [],
            }
            for item in radar
            if kind == "all" or str(item.get("kind", "")).lower() == kind
        ]
        picks.sort(key=lambda item: item.get("recommendation_score") or 0, reverse=True)

    print(f"GitHub Skill/Agent Radar brief")
    if metadata.get("synced_at"):
        print(f"Synced at: {metadata['synced_at']}")
    if not picks:
        print("No matching projects found in the current radar data.")
        return 0
    print(summarize_items(picks, args.limit))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read GitHub Skill/Agent Radar JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    read = sub.add_parser("read-radar", help="Print a concise radar brief")
    read.add_argument("--root", default=".", help="Repository root for local docs/data JSON")
    read.add_argument("--base-url", help="Public GitHub Pages base URL")
    read.add_argument("--kind", choices=("all", "skill", "agent"), default="all")
    read.add_argument("--limit", type=int, default=5)
    read.set_defaults(func=cmd_read_radar)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
