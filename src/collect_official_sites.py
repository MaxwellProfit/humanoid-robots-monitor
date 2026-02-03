"""
collect_official_sites.py

Monitors official sites using sitemaps and/or specific pages.
This is NOT full scraping. It:
- fetches sitemap URLs
- extracts page URLs
- fetches HEAD or GET for last-modified/etag where possible
- for a small set of pages, extracts title + a short snippet

Writes to data/raw/YYYY-MM-DD.official.json
Maintains a small state store in data/state/site_state.json
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

import requests
import yaml
from bs4 import BeautifulSoup
from dateutil import tz
from dateutil.parser import parse as dtparse


@dataclass(frozen=True)
class Entity:
    id: str
    display_name: str
    official_sitemaps: List[str]
    official_pages: List[str]


def load_watchlist(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def normalize_url(url: str) -> str:
    try:
        parts = urlparse(url)
        qs = dict(parse_qsl(parts.query, keep_blank_values=True))
        for k in list(qs.keys()):
            if k.startswith("utm_") or k in ("ref", "fbclid", "gclid"):
                qs.pop(k, None)
        new_query = urlencode(qs, doseq=True)
        return urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, new_query, parts.fragment))
    except Exception:
        return url


def fetch_text(url: str, timeout: int = 20) -> str:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "humanoid-robots-monitor/1.0"})
    r.raise_for_status()
    return r.text


def parse_sitemap_urls(xml_text: str) -> List[Tuple[str, Optional[str]]]:
    """
    Returns list of (loc, lastmod?) from sitemap XML.
    Handles sitemapindex + urlset.
    """
    soup = BeautifulSoup(xml_text, "xml")
    urls: List[Tuple[str, Optional[str]]] = []

    # sitemap index
    sitemap_tags = soup.find_all("sitemap")
    if sitemap_tags:
        for sm in sitemap_tags:
            loc = sm.find_text("loc")
            if loc:
                urls.append((loc.strip(), sm.find_text("lastmod")))
        return urls

    # urlset
    url_tags = soup.find_all("url")
    for u in url_tags:
        loc = u.find_text("loc")
        if not loc:
            continue
        lastmod = u.find_text("lastmod")
        urls.append((loc.strip(), lastmod.strip() if lastmod else None))
    return urls


def extract_title_snippet(html: str) -> Tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.string.strip() if soup.title and soup.title.string else "").strip()
    # crude snippet from first meaningful paragraph
    snippet = ""
    for p in soup.find_all(["p", "h1", "h2"], limit=20):
        txt = re.sub(r"\s+", " ", p.get_text(" ", strip=True))
        if len(txt) >= 60:
            snippet = txt[:240]
            break
    return title, snippet


def load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"pages": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: Dict[str, Any]) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def should_include_url(u: str) -> bool:
    # keep it conservative; you can expand later
    # skip common non-content paths
    bad = ("/privacy", "/legal", "/terms", "/cookies", "/career", "/jobs", "/support")
    lu = u.lower()
    return not any(b in lu for b in bad)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    watchlist_path = repo_root / "config" / "watchlist.yaml"
    cfg = load_watchlist(str(watchlist_path))

    tz_name = cfg.get("settings", {}).get("timezone", "America/Chicago")
    default_tz = tz.gettz(tz_name)
    lookback_days = int(cfg.get("settings", {}).get("lookback_days", 2))
    cutoff = datetime.now(tz=default_tz) - timedelta(days=lookback_days)

    entities: List[Entity] = []
    for e in cfg.get("entities", []):
        entities.append(
            Entity(
                id=e["id"],
                display_name=e["display_name"],
                official_sitemaps=list(e.get("official_sitemaps", []) or []),
                official_pages=list(e.get("official_pages", []) or []),
            )
        )

    state_dir = repo_root / "data" / "state"
    ensure_dir(state_dir)
    state_path = state_dir / "site_state.json"
    state = load_state(state_path)
    pages_state: Dict[str, Any] = state.get("pages", {})

    session = requests.Session()
    session.headers.update({"User-Agent": "humanoid-robots-monitor/1.0"})

    def record_hit(entity: Entity, url: str, published_iso: str, title: str, snippet: str) -> Dict[str, Any]:
        return {
            "entity_id": entity.id,
            "entity_name": entity.display_name,
            "source_feed": "official_site",
            "title": title or f"Update detected: {urlparse(url).netloc}",
            "url": normalize_url(url),
            "published": published_iso,
            "summary": snippet,
        }

    hits: List[Dict[str, Any]] = []

    for ent in entities:
        # Build candidate URL list from sitemaps
        candidate_urls: List[Tuple[str, Optional[str]]] = []

        # Expand sitemaps (including sitemap index)
        for sm_url in ent.official_sitemaps:
            try:
                xml = session.get(sm_url, timeout=25).text
                first = parse_sitemap_urls(xml)

                # If it's a sitemap index, fetch each child sitemap (limited)
                if first and any(u[0].endswith(".xml") for u in first[:3]):
                    # fetch up to 8 child sitemaps to keep it cheap
                    for child_url, _ in first[:8]:
                        try:
                            child_xml = session.get(child_url, timeout=25).text
                            candidate_urls.extend(parse_sitemap_urls(child_xml))
                        except Exception:
                            continue
                else:
                    candidate_urls.extend(first)
            except Exception:
                continue

        # Add explicit pages
        for p in ent.official_pages:
            candidate_urls.append((p, None))

        # Reduce + filter
        seen = set()
        filtered: List[Tuple[str, Optional[str]]] = []
        for url, lastmod in candidate_urls:
            url = normalize_url(url)
            if url in seen:
                continue
            seen.add(url)
            if not should_include_url(url):
                continue
            filtered.append((url, lastmod))

        # Keep a cap so Actions runs quickly
        filtered = filtered[:200]

        for url, lastmod in filtered:
            # Determine "published" from sitemap lastmod if present, else use now
            published_iso = None
            if lastmod:
                try:
                    dt = dtparse(lastmod)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=default_tz)
                    published_iso = dt.astimezone(default_tz).isoformat()
                except Exception:
                    published_iso = None

            if not published_iso:
                published_iso = datetime.now(tz=default_tz).isoformat()

            # Only consider URLs with lastmod within lookback when lastmod exists
            if lastmod:
                try:
                    if dtparse(published_iso) < cutoff:
                        continue
                except Exception:
                    pass

            # HEAD/GET for etag/last-modified
            prev = pages_state.get(url, {})
            prev_etag = prev.get("etag")
            prev_lm = prev.get("last_modified")

            etag = None
            last_modified = None
            changed = False

            try:
                r = session.head(url, timeout=15, allow_redirects=True)
                etag = r.headers.get("ETag")
                last_modified = r.headers.get("Last-Modified")
            except Exception:
                # Some sites block HEAD; fall back to GET headers
                try:
                    r = session.get(url, timeout=20, allow_redirects=True)
                    etag = r.headers.get("ETag")
                    last_modified = r.headers.get("Last-Modified")
                except Exception:
                    continue

            if etag and prev_etag and etag != prev_etag:
                changed = True
            if last_modified and prev_lm and last_modified != prev_lm:
                changed = True

            # If we have sitemap lastmod and it's recent, treat as a “hit” even without header change
            if lastmod and not changed:
                changed = True

            # Update state
            pages_state[url] = {"etag": etag, "last_modified": last_modified, "seen_at": datetime.now(tz=default_tz).isoformat()}

            if not changed:
                continue

            # Fetch minimal page content to get title/snippet (cap per entity/day)
            title = ""
            snippet = ""
            try:
                html = session.get(url, timeout=25, allow_redirects=True).text
                title, snippet = extract_title_snippet(html)
            except Exception:
                pass

            hits.append(record_hit(ent, url, published_iso, title, snippet))

    state["pages"] = pages_state
    save_state(state_path, state)

    day = datetime.now(tz=default_tz).strftime("%Y-%m-%d")
    out_dir = repo_root / "data" / "raw"
    ensure_dir(out_dir)
    out_path = out_dir / f"{day}.official.json"
    out_path.write_text(json.dumps(hits, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote {len(hits)} official-site items to {out_path}")


if __name__ == "__main__":
    main()
