"""
collect_youtube.py

Fetch YouTube channel RSS for each entity's youtube_channel_ids and output items.
Writes to data/raw/YYYY-MM-DD.youtube.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

import feedparser
import yaml
from dateutil import tz
from dateutil.parser import parse as dtparse


@dataclass(frozen=True)
class Entity:
    id: str
    display_name: str
    youtube_channel_ids: List[str]


def load_watchlist(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def normalize_url(url: str) -> str:
    try:
        parts = urlparse(url)
        qs = dict(parse_qsl(parts.query, keep_blank_values=True))
        # drop common tracking
        for k in list(qs.keys()):
            if k.startswith("utm_") or k in ("ref", "fbclid", "gclid"):
                qs.pop(k, None)
        new_query = urlencode(qs, doseq=True)
        return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment))
    except Exception:
        return url


def parse_entry_datetime(entry: Dict[str, Any], default_tz) -> str:
    dt = None
    for key in ("published", "updated"):
        if key in entry and entry[key]:
            try:
                dt = dtparse(entry[key])
                break
            except Exception:
                continue
    if dt is None:
        dt = datetime.now(tz=default_tz)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz)
    return dt.astimezone(default_tz).isoformat()


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    watchlist_path = repo_root / "config" / "watchlist.yaml"
    cfg = load_watchlist(str(watchlist_path))

    tz_name = cfg.get("settings", {}).get("timezone", "America/Chicago")
    default_tz = tz.gettz(tz_name)

    tpl = cfg["sources"]["youtube_channel_rss_template"]

    entities: List[Entity] = []
    for e in cfg.get("entities", []):
        entities.append(
            Entity(
                id=e["id"],
                display_name=e["display_name"],
                youtube_channel_ids=list(e.get("youtube_channel_ids", []) or []),
            )
        )

    lookback_days = int(cfg.get("settings", {}).get("lookback_days", 2))
    cutoff = datetime.now(tz=default_tz) - timedelta(days=lookback_days)

    out: List[Dict[str, Any]] = []
    for ent in entities:
        for cid in ent.youtube_channel_ids:
            feed_url = tpl.format(channel_id=cid)
            feed = feedparser.parse(feed_url)

            for entry in feed.entries:
                link = normalize_url(entry.get("link", ""))
                title = (entry.get("title", "") or "").strip()
                summary = (entry.get("summary", "") or "").strip()
                published_iso = parse_entry_datetime(entry, default_tz)

                try:
                    dt = dtparse(published_iso)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=default_tz)
                    if dt < cutoff:
                        continue
                except Exception:
                    pass

                out.append(
                    {
                        "entity_id": ent.id,
                        "entity_name": ent.display_name,
                        "source_feed": "youtube",
                        "title": title,
                        "url": link,
                        "published": published_iso,
                        "summary": summary,
                    }
                )

    day = datetime.now(tz=default_tz).strftime("%Y-%m-%d")
    out_dir = repo_root / "data" / "raw"
    ensure_dir(out_dir)
    out_path = out_dir / f"{day}.youtube.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote {len(out)} YouTube items to {out_path}")


if __name__ == "__main__":
    main()
