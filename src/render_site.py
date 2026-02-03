"""
render_site.py (v2 UX)

Reads data/digest/*.json and writes a static site into /docs.
Outputs:
- docs/index.html (latest day view + filters + search + stats)
- docs/history.html (list of days)
- docs/days/YYYY-MM-DD.html (one per day; same UI)

Still pure static HTML (GitHub Pages-friendly).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple
from datetime import datetime
from collections import Counter, defaultdict

import yaml
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
    tier: int = 5


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
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso[:16]


def load_source_tiers(path: Path) -> Dict[int, List[str]]:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    tiers = cfg.get("tiers", {})
    out: Dict[int, List[str]] = {}
    for k, v in tiers.items():
        out[int(k)] = list(v)
    return out


def domain_matches(domain: str, pattern: str) -> bool:
    if pattern == "*":
        return True
    d = domain.lower()
    p = pattern.lower()
    return d == p or d.endswith("." + p) or p in d


def assign_tier(domain: str, tiers: Dict[int, List[str]]) -> int:
    for tier in sorted(tiers.keys()):
        patterns = tiers[tier]
        for pat in patterns:
            if domain_matches(domain, pat):
                return tier
    return 5


def load_digest(path: Path, tiers: Dict[int, List[str]]) -> List[DigestItem]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items: List[DigestItem] = []
    for r in raw:
        domain = (r.get("domain") or "").lower()
        t = assign_tier(domain, tiers)
        items.append(
            DigestItem(
                entity_id=r.get("entity_id", ""),
                entity_name=r.get("entity_name", ""),
                title=(r.get("title") or "").strip(),
                url=r.get("url", ""),
                domain=domain,
                published=r.get("published", ""),
                summary=(r.get("summary") or "").strip(),
                source_feed=r.get("source_feed", ""),
                tier=t,
            )
        )
    return items


BASE_CSS = """
:root {
  --bg: #0b0f14;
  --card: #111824;
  --text: #e6edf3;
  --muted: #9fb0c0;
  --link: #7dd3fc;
  --border: #1f2a3a;
  --chip: #0f2233;
  --good: #22c55e;
  --warn: #f59e0b;
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
  max-width: 1100px;
  margin: 0 auto;
  padding: 28px 18px 60px;
}
.header {
  display: flex;
  gap: 16px;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  margin-bottom: 18px;
}
.brand {
  font-size: 20px;
  font-weight: 800;
  letter-spacing: 0.2px;
}
.sub {
  color: var(--muted);
  font-size: 13px;
  margin-top: 2px;
}
.nav {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}
.pill {
  background: var(--chip);
  border: 1px solid var(--border);
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 12px;
  color: var(--text);
}
.pill.active { outline: 2px solid rgba(125, 211, 252, 0.35); }

.h1 {
  font-size: 28px;
  font-weight: 800;
  margin: 16px 0 6px;
}
.small { font-size: 12px; color: var(--muted); line-height: 1.2rem; }

.controls {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
  margin: 14px 0 18px;
}
@media (min-width: 780px) {
  .controls { grid-template-columns: 1.2fr 1fr; }
}
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 14px;
  margin: 10px 0;
}
.kpi {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.kpi .pill { cursor: default; }
.input {
  width: 100%;
  background: #0f1622;
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 10px 12px;
  font-size: 13px;
}
.filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
}
.chk {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: #0f1622;
  cursor: pointer;
  user-select: none;
  font-size: 12px;
}
.chk input { accent-color: #7dd3fc; }
.section-title {
  font-size: 16px;
  font-weight: 800;
  margin: 20px 0 10px;
}
.item-title {
  font-size: 14px;
  font-weight: 700;
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
.badge {
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: #0f1622;
}
.badge.t1 { border-color: rgba(34,197,94,.35); }
.badge.t2 { border-color: rgba(34,197,94,.22); }
.badge.t3 { border-color: rgba(245,158,11,.25); }
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
.hidden { display:none; }
"""

def heuristic_summary(items: List[DigestItem]) -> str:
    """
    Free summary: most-mentioned entities + top domains + rough theme words from titles.
    Not "AI", but useful.
    """
    if not items:
        return "No items found for this day."

    entities = Counter([it.entity_name for it in items]).most_common(4)
    domains = Counter([it.domain for it in items if it.domain]).most_common(5)

    # rough tokenization from titles
    stop = set(["the","a","an","and","or","to","of","in","on","for","with","is","are","as","from","at","by","new","about"])
    words = Counter()
    for it in items:
        for w in it.title.lower().replace("—"," ").replace(":"," ").replace(","," ").split():
            w = "".join(ch for ch in w if ch.isalnum())
            if len(w) < 4 or w in stop:
                continue
            words[w] += 1
    themes = [w for w,_ in words.most_common(6)]

    ent_txt = ", ".join([f"{name} ({cnt})" for name,cnt in entities])
    dom_txt = ", ".join([f"{d} ({cnt})" for d,cnt in domains])
    theme_txt = ", ".join(themes) if themes else "—"

    return (
        f"Entity activity: {ent_txt}. "
        f"Top sources: {dom_txt}. "
        f"Common themes in titles: {theme_txt}."
    )


def render_page(title: str, subtitle: str, body_html: str, repo_url: str, base_path: str) -> str:
    # base_path like "/humanoid-robots-monitor/"
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
        <a class="pill" href="{base_path}index.html">Latest</a>
        <a class="pill" href="{base_path}history.html">History</a>
        <a class="pill" href="{html_escape(repo_url)}" target="_blank" rel="noopener noreferrer">Repo</a>
      </div>
    </div>

    <div class="h1">{html_escape(title)}</div>

    {body_html}

    <div class="footer">Generated automatically.</div>
  </div>

<script>
function applyFilters() {{
  const q = (document.getElementById('q')?.value || '').toLowerCase().trim();
  const checked = Array.from(document.querySelectorAll('input[name="entity"]:checked')).map(x => x.value);
  const items = Array.from(document.querySelectorAll('[data-entity]'));

  let shown = 0;
  for (const el of items) {{
    const ent = el.getAttribute('data-entity');
    const text = el.getAttribute('data-text');
    const entOk = (checked.length === 0) || checked.includes(ent);
    const qOk = (!q) || (text && text.includes(q));
    const ok = entOk && qOk;
    el.classList.toggle('hidden', !ok);
    if (ok) shown += 1;
  }}
  const counter = document.getElementById('shownCount');
  if (counter) counter.textContent = String(shown);
}}

document.addEventListener('input', (e) => {{
  if (e.target && (e.target.id === 'q' || e.target.name === 'entity')) {{
    applyFilters();
  }}
}});

document.addEventListener('DOMContentLoaded', () => {{
  applyFilters();
}});
</script>

</body>
</html>
"""


def render_controls(items: List[DigestItem], entities_ordered: List[str]) -> str:
    counts = Counter([it.entity_name for it in items])
    chk_html = []
    for ent in entities_ordered:
        eid = entity_slug(ent)
        chk_html.append(
            f'''<label class="chk"><input type="checkbox" name="entity" value="{html_escape(eid)}"/> {html_escape(ent)} <span class="badge">{counts.get(ent,0)}</span></label>'''
        )

    return f"""
<div class="card">
  <div class="kpi">
    <span class="pill">Items shown: <strong id="shownCount">0</strong></span>
    <span class="pill">Total items: <strong>{len(items)}</strong></span>
  </div>
  <div class="controls">
    <div>
      <div class="small">Search titles/domains</div>
      <input id="q" class="input" type="text" placeholder="e.g., Optimus, Figure 02, Atlas, funding, demo..." />
      <div class="small" style="margin-top:8px;">Filter by entity (leave all unchecked to show everything)</div>
      <div class="filters">
        {''.join(chk_html)}
      </div>
    </div>
    <div>
      <div class="small">Summary (free)</div>
      <div class="small" style="margin-top:8px; color: var(--text); line-height: 1.35rem;">
        {html_escape(heuristic_summary(items))}
      </div>
      <div class="small" style="margin-top:10px;">(Optional AI summaries can be added later.)</div>
    </div>
  </div>
</div>
"""


def entity_slug(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_")


def render_items(items: List[DigestItem], entities_ordered: List[str]) -> str:
    """
    Render all items as a single list (not grouped),
    sorted by tier then time desc.
    """
    def sort_key(it: DigestItem):
        return (it.tier, -safe_dt(it.published).timestamp())

    items_sorted = sorted(items, key=sort_key)

    parts: List[str] = []
    parts.append('<div class="section-title">All items</div>')

    for it in items_sorted:
        ent = it.entity_name or "Other"
        ent_id = entity_slug(ent)
        t = html_escape(it.title)
        u = html_escape(it.url)
        dom = html_escape(it.domain)
        tm = html_escape(fmt_time(it.published))
        summary = html_escape(it.summary) if it.summary else ""
        summary_html = f'<div class="small">{summary}</div>' if summary else ""
        tier_badge = f'<span class="badge t{it.tier}">tier {it.tier}</span>'

        data_text = f"{it.title} {it.domain} {it.entity_name}".lower()
        data_text = html_escape(data_text)

        parts.append(
            f"""
            <div class="card" data-entity="{html_escape(ent_id)}" data-text="{data_text}">
              <div class="item-title"><a href="{u}" target="_blank" rel="noopener noreferrer">{t}</a></div>
              <div class="meta">
                <span>{tm}</span>
                <span>{dom}</span>
                <span>{tier_badge}</span>
                <span class="badge">{html_escape(ent)}</span>
              </div>
              {summary_html}
            </div>
            """
        )

    return "\n".join(parts)


def render_history(days: List[str], base_path: str) -> str:
    links = "\n".join([f'<a class="pill" href="{base_path}days/{d}.html">{html_escape(d)}</a>' for d in reversed(days[-60:])])
    body = f"""
<div class="card">
  <div class="small">Recent days (last {min(60, len(days))})</div>
  <div class="daylist" style="margin-top:12px;">{links}</div>
</div>
"""
    return body


def top_sources(items: List[DigestItem], n: int = 8) -> List[Tuple[str, int]]:
    c = Counter([it.domain for it in items if it.domain])
    return c.most_common(n)


def render_top_sources(items: List[DigestItem]) -> str:
    ts = top_sources(items, n=10)
    chips = "".join([f'<span class="pill">{html_escape(dom)} <strong>({cnt})</strong></span>' for dom, cnt in ts])
    return f"""
<div class="card">
  <div class="small">Top sources today</div>
  <div class="filters" style="margin-top:10px;">{chips}</div>
</div>
"""


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    digest_dir = repo_root / "data" / "digest"
    docs_dir = repo_root / "docs"
    days_dir = docs_dir / "days"
    docs_dir.mkdir(parents=True, exist_ok=True)
    days_dir.mkdir(parents=True, exist_ok=True)

    tiers_path = repo_root / "config" / "source_tiers.yaml"
    tiers = load_source_tiers(tiers_path) if tiers_path.exists() else {5: ["*"]}

    # Hardcode these two to avoid asking you again:
    # Update repo_url to YOUR repo URL once if you want.
    repo_url = "https://github.com/"
    base_path = "/humanoid-robots-monitor/"  # must match repo name for GitHub Pages

    digest_files = sorted(digest_dir.glob("*.json"))
    if not digest_files:
        raise SystemExit("No digest files found in data/digest/. Run dedupe_digest.py first.")

    days = [p.stem for p in digest_files]
    latest_path = digest_files[-1]
    latest_day = latest_path.stem

    # Render each day page
    for p in digest_files:
        day = p.stem
        items = load_digest(p, tiers)

        # entity order by count desc
        ent_counts = Counter([it.entity_name for it in items])
        entities_ordered = [name for name, _ in ent_counts.most_common()]

        controls = render_controls(items, entities_ordered)
        sources_block = render_top_sources(items)
        items_block = render_items(items, entities_ordered)

        body = controls + sources_block + items_block
        html = render_page(
            title=f"Robot Digest — {day}",
            subtitle="Daily coverage across tracked humanoid-robot entities",
            body_html=body,
            repo_url=repo_url,
            base_path=base_path,
        )
        (days_dir / f"{day}.html").write_text(html, encoding="utf-8")

    # Render index.html as latest
    latest_items = load_digest(latest_path, tiers)
    ent_counts = Counter([it.entity_name for it in latest_items])
    entities_ordered = [name for name, _ in ent_counts.most_common()]

    index_body = (
        render_controls(latest_items, entities_ordered)
        + render_top_sources(latest_items)
        + render_items(latest_items, entities_ordered)
    )
    (docs_dir / "index.html").write_text(
        render_page(
            title=f"Robot Digest — {latest_day}",
            subtitle="Daily coverage across tracked humanoid-robot entities",
            body_html=index_body,
            repo_url=repo_url,
            base_path=base_path,
        ),
        encoding="utf-8",
    )

    # Render history.html
    (docs_dir / "history.html").write_text(
        render_page(
            title="History",
            subtitle="Browse previous daily digests",
            body_html=render_history(days, base_path=base_path),
            repo_url=repo_url,
            base_path=base_path,
        ),
        encoding="utf-8",
    )

    print("Rendered index.html, history.html, and day pages.")


if __name__ == "__main__":
    main()
