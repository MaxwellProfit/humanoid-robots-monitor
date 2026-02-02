"""
collect_news.py

Fetch Google News RSS results for each entity defined in config/watchlist.yaml.
Outputs a raw (not deduped) JSON list to data/raw/YYYY-MM-DD.json.

This script is intentionally minimal: stable inputs, stable outputs.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote_plus, urlparse, parse_qsl, urlencode, urlunparse

import feedparser
import yaml
from dateutil import tz
from dateutil.parser import parse as dtparse


@dataclass(frozen=True)
class Entity:
    id: str
    display_name: str
    google_news_query: str
    keywords: List[str]


def load_watchlist(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def normalize_url(url: str) -> str:
    """
    Normalize URLs for stability:
    - Remove common tracking params (utm_*, ref, fbclid, gclid)
    - Keep the rest
    """
    try:
        parts = urlparse(url)
        qs = dict(parse_qsl(parts.query, keep_blank_values=True))
        keys_to_drop = [k for k in qs.keys() if k.startswith("utm_")] + ["ref", "fbclid", "gclid"]
        for k in keys_to_drop:
            qs.pop(k, None)
        new_query = urlencode(qs, doseq=True)
        return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment))
    except Exception:
        return url


def parse_entry_datetime(entry: Dict[str, Any], default_tz) -> str:
    """
    Return ISO8601 string in local timezone.
    Google News RSS typically provides published or updated.
    """
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


def collect_google_news(entity: Entity, rss_template: str, default_tz) -> List[Dict[str, Any]]:
    q = quote_plus(entity.google_news_query)
    url = rss_template.format(query=q)
    feed = feedparser.parse(url)

    items: List[Dict[str, Any]] = []
    for e in feed.entries:
        link = e.get("link", "")
        title = e.get("title", "").strip()
        summary = e.get("summary", "").strip()
        published_iso = parse_entry_datetime(e, default_tz)

        items.append(
            {
                "entity_id": entity.id,
                "entity_name": entity.display_name,
                "source_feed": "google_news",
                "title": title,
                "url": normalize_url(link),
                "published": published_iso,
                "summary": summary,
            }
        )
    return items


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    watchlist_path = repo_root / "config" / "watchlist.yaml"
    cfg = load_watchlist(str(watchlist_path))

    tz_name = cfg.get("settings", {}).get("timezone", "America/Chicago")
    default_tz = tz.gettz(tz_name)

    rss_template = cfg["sources"]["google_news_rss_template"]

    entities: List[Entity] = []
    for e in cfg.get("entities", []):
        entities.append(
            Entity(
                id=e["id"],
                display_name=e["display_name"],
                google_news_query=e["google_news_query"],
                keywords=list(e.get("keywords", [])),
            )
        )

    all_items: List[Dict[str, Any]] = []
    for ent in entities:
        items = collect_google_news(ent, rss_template, default_tz)
        all_items.extend(items)

    # Optional: filter by lookback window to prevent old items from resurfacing
    lookback_days = int(cfg.get("settings", {}).get("lookback_days", 2))
    cutoff = datetime.now(tz=default_tz) - timedelta(days=lookback_days)

    filtered: List[Dict[str, Any]] = []
    for it in all_items:
        try:
            dt = dtparse(it["published"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=default_tz)
            if dt >= cutoff:
                filtered.append(it)
        except Exception:
            filtered.append(it)

    # Write output
    day = datetime.now(tz=default_tz).strftime("%Y-%m-%d")
    out_dir = repo_root / "data" / "raw"
    ensure_dir(out_dir)
    out_path = out_dir / f"{day}.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(filtered, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(filtered)} items to {out_path}")


if __name__ == "__main__":
    main()
