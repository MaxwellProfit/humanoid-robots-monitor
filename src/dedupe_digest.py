"""
dedupe_digest.py

Reads data/raw/YYYY-MM-DD.json (from collect_news.py),
dedupes items, and writes data/digest/YYYY-MM-DD.json.

Dedupe strategy:
1) Canonicalize URL (already mostly done in collect step, but we repeat defensively).
2) Remove exact duplicates by canonical URL.
3) Remove near-duplicates by fuzzy title similarity (within each entity), preferring:
   - primary/official domains (light heuristic)
   - shorter URL (often cleaner)
   - earlier published time (tie-breaker)

Outputs a stable, sorted digest for downstream rendering.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from dateutil.parser import parse as dtparse
from rapidfuzz import fuzz


TRACKING_KEYS_EXACT = {"ref", "fbclid", "gclid"}
TRACKING_PREFIXES = ("utm_",)


# Light heuristic: treat these as more "primary" than random reposts.
PRIMARY_DOMAIN_KEYWORDS = (
    "tesla.com",
    "bostondynamics.com",
    "apptronik.com",
    "figure.ai",
    "sanctuary.ai",
    "sec.gov",
    "investor",
    "ir.",
    "newsroom",
    "press",
    "blog",
)


@dataclass
class Item:
    entity_id: str
    entity_name: str
    source_feed: str
    title: str
    url: str
    published: str
    summary: str
    domain: str


def canonicalize_url(url: str) -> str:
    try:
        p = urlparse(url)
        qs = dict(parse_qsl(p.query, keep_blank_values=True))

        # Drop tracking params
        for k in list(qs.keys()):
            if k in TRACKING_KEYS_EXACT or k.startswith(TRACKING_PREFIXES):
                qs.pop(k, None)

        new_query = urlencode(qs, doseq=True)
        return urlunparse((p.scheme, p.netloc, p.path, p.params, new_query, p.fragment))
    except Exception:
        return url


def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def is_primary_domain(domain: str) -> bool:
    d = domain.lower()
    return any(k in d for k in PRIMARY_DOMAIN_KEYWORDS)


def parse_dt_safe(iso: str) -> datetime:
    try:
        return dtparse(iso)
    except Exception:
        return datetime.min


def normalize_title(t: str) -> str:
    t = t.strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t


def choose_better(a: Item, b: Item) -> Item:
    """
    Decide which duplicate to keep.
    Priority:
    1) Primary-ish domain
    2) Shorter URL (often cleaner)
    3) Earlier published (keeps first report)
    """
    a_primary = is_primary_domain(a.domain)
    b_primary = is_primary_domain(b.domain)
    if a_primary and not b_primary:
        return a
    if b_primary and not a_primary:
        return b

    if len(a.url) != len(b.url):
        return a if len(a.url) < len(b.url) else b

    adt = parse_dt_safe(a.published)
    bdt = parse_dt_safe(b.published)
    if adt != bdt:
        return a if adt < bdt else b

    # Default to a
    return a


def load_items(path: Path) -> List[Item]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items: List[Item] = []
    for r in raw:
        url = canonicalize_url(r.get("url", ""))
        dom = domain_of(url)
        items.append(
            Item(
                entity_id=r.get("entity_id", ""),
                entity_name=r.get("entity_name", ""),
                source_feed=r.get("source_feed", ""),
                title=r.get("title", "").strip(),
                url=url,
                published=r.get("published", ""),
                summary=r.get("summary", "").strip(),
                domain=dom,
            )
        )
    return items


def dedupe_exact(items: List[Item]) -> List[Item]:
    by_url: Dict[str, Item] = {}
    for it in items:
        if not it.url:
            continue
        if it.url not in by_url:
            by_url[it.url] = it
        else:
            by_url[it.url] = choose_better(by_url[it.url], it)
    return list(by_url.values())


def dedupe_fuzzy_within_entity(items: List[Item], threshold: int = 92) -> List[Item]:
    """
    Fuzzy dedupe titles within each entity. If two items' titles are very similar,
    keep the better one.
    """
    grouped: Dict[str, List[Item]] = {}
    for it in items:
        grouped.setdefault(it.entity_id, []).append(it)

    kept: List[Item] = []
    for entity_id, group in grouped.items():
        group_sorted = sorted(group, key=lambda x: parse_dt_safe(x.published), reverse=True)

        accepted: List[Item] = []
        for cand in group_sorted:
            cand_title = normalize_title(cand.title)
            dup_idx = None
            for i, acc in enumerate(accepted):
                score = fuzz.token_set_ratio(cand_title, normalize_title(acc.title))
                if score >= threshold:
                    dup_idx = i
                    break

            if dup_idx is None:
                accepted.append(cand)
            else:
                accepted[dup_idx] = choose_better(accepted[dup_idx], cand)

        kept.extend(accepted)

    return kept


def to_json(items: List[Item]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for it in items:
        out.append(
            {
                "entity_id": it.entity_id,
                "entity_name": it.entity_name,
                "title": it.title,
                "url": it.url,
                "domain": it.domain,
                "published": it.published,
                "summary": it.summary,
                "source_feed": it.source_feed,
            }
        )
    return out


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    raw_dir = repo_root / "data" / "raw"
    digest_dir = repo_root / "data" / "digest"
    ensure_dir(digest_dir)

    # Default: process today’s file if present; otherwise process the newest raw file.
   raw_files = sorted(raw_dir.glob("*.json"))
   if not raw_files:
       raise SystemExit("No raw JSON files found in data/raw/. Run collectors first.")
   
   # Determine "day" by newest file's leading date
   newest = raw_files[-1].name
   day = newest.split(".")[0]  # YYYY-MM-DD from YYYY-MM-DD[.suffix].json
   
   day_files = sorted(raw_dir.glob(f"{day}*.json"))
   if not day_files:
       raise SystemExit(f"No raw files found for day {day}")
   
   items = []
   for p in day_files:
       items.extend(load_items(p))

    before = len(items)

    items = dedupe_exact(items)
    after_exact = len(items)

    items = dedupe_fuzzy_within_entity(items, threshold=92)
    after_fuzzy = len(items)

    # Sort output for stable display: newest first, then entity.
    items = sorted(
        items,
        key=lambda x: (parse_dt_safe(x.published), x.entity_name.lower(), x.domain),
        reverse=True,
    )

    out_path = digest_dir / f"{day}.json"
    out_path.write_text(json.dumps(to_json(items), ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"Raw: {before} | After exact: {after_exact} | After fuzzy: {after_fuzzy} | Wrote {out_path}"
    )


if __name__ == "__main__":
    main()
