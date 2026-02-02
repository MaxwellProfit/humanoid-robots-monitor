"""
render_site.py

Reads data/digest/*.json and writes a static site into /site.
Outputs:
- site/index.html (latest day + recent days list)
- site/days/YYYY-MM-DD.html (one per day)

This is intentionally simple HTML for GitHub Pages.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple
from datetime import datetime

from dateutil.parser import parse as dtparse


@dataclass
class DigestItem:
    entity_id: str
    entity_name: str
    title: str
    url: str
    domain: str
    published: str
    summary: str
    source_feed: str


def load_digest(path: Path) -> List[DigestItem]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items: List[DigestItem] = []
    for r in raw:
        items.append(
            DigestItem(
                entity_id=r.get("entity_id", ""),
                entity_name=r.get("entity_name", ""),
                title=r.get("title", "").strip(),
                url=r.get("url", ""),
                domain=r.get("domain", ""),
                published=r.get("published", ""),
                summary=r.get("summary", "").strip(),
                source_feed=r.get("source_feed", ""),
            )
        )
    return items


def group_by_entity(items: List[DigestItem]) -> Dict[str, List[DigestItem]]:
    grouped: Dict[str, List[DigestItem]] = {}
    for it in items:
        grouped.setdefault(it.entity_name or "Other", []).append(it)
    # Sort each group by published desc
    for k in grouped:
        grouped[k].sort(key=lambda x: safe_dt(x.published), reverse=True)
    return dict(sorted(grouped.items(), key=lambda kv: kv[0].lower()))


def safe_dt(s: str) -> datetime:
    try:
        return dtparse(s)
    except Exception:
        return datetime.min


def html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#039;")
    )


def fmt_time(iso: str) -> str:
    try:
        dt = dtparse(iso)
        # Show local time if tz present; otherwise just date/time
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso[:16]


BASE_CSS = """
:root {
  --bg: #0b0f14;
  --card: #111824;
  --text: #e6edf3;
  --muted: #9fb0c0;
  --link: #7dd3fc;
  --border: #1f2a3a;
  --chip: #0f2233;
}

* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji", "Segoe UI Emoji";
  background: var(--bg);
  color: var(--text);
}
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }

.container {
  max-width: 980px;
  margin: 0 auto;
  padding: 28px 18px 60px;
}
.header {
  display: flex;
  gap: 16px;
  align-items: baseline;
  justify-content: space-between;
  flex-wrap: wrap;
  margin-bottom: 18px;
}
.brand {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 0.2px;
}
.sub {
  color: var(--muted);
  font-size: 13px;
}
.nav {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.pill {
  background: var(--chip);
  border: 1px solid var(--border);
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 12px;
  color: var(--text);
}

.h1 {
  font-size: 28px;
  font-weight: 750;
  margin: 18px 0 10px;
}
.h2 {
  font-size: 16px;
  font-weight: 700;
  margin: 24px 0 10px;
  color: var(--text);
}
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 14px;
  margin: 10px 0;
}
.item-title {
  font-size: 14px;
  font-weight: 650;
  margin: 0 0 6px;
  line-height: 1.25rem;
}
.meta {
  font-size: 12px;
  color: var(--muted);
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.small {
  font-size: 12px;
  color: var(--muted);
  margin-top: 8px;
  line-height: 1.2rem;
}
.footer {
  margin-top: 30px;
  color: var(--muted);
  font-size: 12px;
}
.daylist {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
}
"""

def render_page(title: str, subtitle: str, body_html: str, day_links: List[Tuple[str, str]] | None = None) -> str:
    day_links = day_links or []
    day_html = ""
    if day_links:
        chips = "\n".join([f'<a class="pill" href="{href}">{html_escape(day)}</a>' for day, href in day_links])
        day_html = f"""
        <div class="h2">Recent days</div>
        <div class="daylist">{chips}</div>
        """

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{html_escape(title)}</title>
  <style>{BASE_CSS}</style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div>
        <div class="brand">Humanoid Robots Monitor</div>
        <div class="sub">{html_escape(subtitle)}</div>
      </div>
      <div class="nav">
        <a class="pill" href="/humanoid-robots-monitor/">Latest</a>
        <a class="pill" href="https://github.com/">Repo</a>
      </div>
    </div>

    <div class="h1">{html_escape(title)}</div>

    {body_html}

    {day_html}

    <div class="footer">Generated automatically.</div>
  </div>
</body>
</html>
"""


def render_digest_body(day: str, items: List[DigestItem]) -> str:
    grouped = group_by_entity(items)
    parts: List[str] = []

    # top stats
    parts.append(f'<div class="small">{len(items)} items • {html_escape(day)}</div>')

    for entity_name, group in grouped.items():
        parts.append(f'<div class="h2">{html_escape(entity_name)} <span class="small">({len(group)})</span></div>')
        for it in group:
            t = html_escape(it.title)
            u = html_escape(it.url)
            dom = html_escape(it.domain)
            tm = html_escape(fmt_time(it.published))
            summary = html_escape(it.summary) if it.summary else ""
            summary_html = f'<div class="small">{summary}</div>' if summary else ""

            parts.append(
                f"""
                <div class="card">
                  <div class="item-title"><a href="{u}" target="_blank" rel="noopener noreferrer">{t}</a></div>
                  <div class="meta">
                    <span>{tm}</span>
                    <span>{dom}</span>
                  </div>
                  {summary_html}
                </div>
                """
            )

    return "\n".join(parts)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    digest_dir = repo_root / "data" / "digest"
    site_dir = repo_root / "site"
    days_dir = site_dir / "days"
    site_dir.mkdir(parents=True, exist_ok=True)
    days_dir.mkdir(parents=True, exist_ok=True)

    digest_files = sorted(digest_dir.glob("*.json"))
    if not digest_files:
        raise SystemExit("No digest files found in data/digest/. Run dedupe_digest.py first.")

    # Most recent = latest
    latest_path = digest_files[-1]
    latest_day = latest_path.stem

    # Build day links list (most recent first), limit to 14
    day_links: List[Tuple[str, str]] = []
    for p in reversed(digest_files[-14:]):
        day_links.append((p.stem, f"days/{p.stem}.html"))

    # Render each day page
    for p in digest_files:
        day = p.stem
        items = load_digest(p)
        body = render_digest_body(day, items)
        html = render_page(
            title=f"Daily Digest — {day}",
            subtitle="Daily links and coverage across tracked entities",
            body_html=body,
            day_links=day_links,
        )
        (days_dir / f"{day}.html").write_text(html, encoding="utf-8")

    # Render index.html as latest day page (copy of latest)
    latest_items = load_digest(latest_path)
    latest_body = render_digest_body(latest_day, latest_items)

    index_html = render_page(
        title=f"Daily Digest — {latest_day}",
        subtitle="Daily links and coverage across tracked entities",
        body_html=latest_body,
        day_links=day_links,
    )
    (site_dir / "index.html").write_text(index_html, encoding="utf-8")

    print(f"Rendered site/index.html and {len(digest_files)} day pages.")


if __name__ == "__main__":
    main()
