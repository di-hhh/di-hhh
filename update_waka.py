#!/usr/bin/env python3
"""Fetch WakaTime stats + summaries and update README.md with charts and stats.

Generates:
  - waka-activity.svg   — 7-day bar chart
  - waka-ring-ai.svg    — AI vs Manual coding donut
  - waka-ring-editors.svg — Editors donut
  - waka-ring-os.svg    — Operating systems donut
  - waka-ring-categories.svg — Categories donut

No external dependencies. Pure stdlib.
"""

from __future__ import annotations

import json, math, os, re, sys, io
from base64 import b64encode
from datetime import datetime, timezone
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ── UTF-8 stdout (Windows compat) ────────────────────────────────────────
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ── Constants ────────────────────────────────────────────────────────────
README_PATH = "README.md"
START_TAG = "<!--START_SECTION:waka-->"
END_TAG = "<!--END_SECTION:waka-->"
DIST_DIR = "dist"

API_BASE = "https://wakatime.com"
STATS_PATH = "/api/v1/users/current/stats/last_7_days"
SUMMARIES_PATH = "/api/v1/users/current/summaries?range=last_7_days"

LANG_LIMIT = 10

# Color palette for charts
PALETTE = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6",
           "#06b6d4", "#f97316", "#84cc16", "#ec4899", "#6366f1"]

# ── Helpers ──────────────────────────────────────────────────────────────

def date_range(stats: dict[str, Any]) -> str:
    rng = stats.get("range", {})
    if isinstance(rng, str):
        rng = {}
    s = rng.get("start_date", "") or str(stats.get("start", ""))[:10] or "?"
    e = rng.get("end_date",   "") or str(stats.get("end",   ""))[:10] or "?"
    return f"{s} ~ {e}"


def best_day(stats: dict[str, Any]) -> str:
    bd = stats.get("best_day")
    if not bd:
        return "N/A"
    ds, ts = bd.get("date", ""), bd.get("text", "")
    if not ds or not ts:
        return "N/A"
    try:
        ds = datetime.strptime(ds, "%Y-%m-%d").strftime("%a %b %d")
    except (ValueError, TypeError):
        pass
    return f"{ds} — {ts}"



# ── API ──────────────────────────────────────────────────────────────────

def _auth(api_key: str) -> str:
    return f"Basic {b64encode(api_key.encode('utf-8')).decode('ascii')}"


def _get(url: str, auth: str) -> dict[str, Any] | None:
    try:
        req = Request(url, headers={"Authorization": auth})
        with urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except (HTTPError, URLError) as e:
        print(f"warn: {url} — {e}")
        return None


def fetch_stats(api_key: str) -> dict[str, Any] | None:
    body = _get(API_BASE + STATS_PATH, _auth(api_key))
    if body is None:
        return None
    if body.get("error") or body.get("errors"):
        print(f"warn: stats API error — {body.get('error') or body.get('errors')}")
        return None
    return body.get("data")


def fetch_summaries(api_key: str) -> list[dict[str, Any]] | None:
    body = _get(API_BASE + SUMMARIES_PATH, _auth(api_key))
    if body is None:
        return None
    if body.get("error") or body.get("errors"):
        print(f"warn: summaries API error — {body.get('error') or body.get('errors')}")
        return None
    data = body.get("data")
    return data if isinstance(data, list) else None


# ── SVG: Daily Activity Bar Chart ────────────────────────────────────────

def svg_daily_activity(days: list[dict[str, Any]]) -> str | None:
    """7-day vertical bar chart with grow-in animation (no title)."""
    if not days:
        return None
    daily: list[tuple[str, float]] = []
    for d in days:
        gt = d.get("grand_total", {})
        daily.append((d.get("range", {}).get("date", "")[-5:], gt.get("total_seconds", 0.0)))
    if len(daily) < 1:
        return None

    max_s = max(v for _, v in daily) or 1
    W, H = 600, 200
    ML, MR, MT, MB = 50, 12, 8, 32  # reduced MT since no title
    cw, ch = W - ML - MR, H - MT - MB
    gap = 10
    bw = max(8, (cw - gap * (len(daily) - 1)) // len(daily))

    bottom_y = MT + ch  # bars grow from this y coordinate

    # Build CSS: one @keyframes, one class per bar with its own transform-origin + delay
    css = ['<style>',
           '@keyframes g{from{transform:scaleY(0)}to{transform:scaleY(1)}}',
           '.grid{stroke:#e5e7eb;stroke-width:.5}',
           '.tick{fill:#6b7280;font-size:10px;font-family:system-ui,sans-serif}',
           '.lab{fill:#374151;font-size:10px;font-family:system-ui,sans-serif;text-anchor:middle}',
           '.val{fill:#6b7280;font-size:9px;font-family:system-ui,sans-serif;text-anchor:middle}']

    x = ML + gap // 2
    for i, (ds, secs) in enumerate(daily):
        cx = x + bw / 2.0
        delay = i * 0.08
        css.append(
            f'.b{i}{{animation:g 0.4s {delay:.2f}s ease-out forwards;'
            f'fill:#3b82f6;rx:3;transform-origin:{cx:.1f}px {bottom_y:.0f}px}}')
        css.append(f'.b{i}:hover{{fill:#2563eb}}')
        x += bw + gap
    css.append('</style>')

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img">',
        *css,
    ]

    # Grid + Y-axis
    ticks = 4
    step = max_s / ticks if max_s else 1
    for i in range(ticks + 1):
        y = MT + ch - (ch * i / ticks)
        parts.append(f'<line x1="{ML}" y1="{y:.1f}" x2="{W-MR}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{ML-4}" y="{y+3:.1f}" class="tick" text-anchor="end">{step*i/3600:.1f}h</text>')

    # Bars
    x = ML + gap // 2
    for i, (ds, secs) in enumerate(daily):
        bh = (secs / max_s) * ch if max_s else 0
        bh = max(0, min(ch, bh))
        by = bottom_y - bh
        parts.append(
            f'<rect x="{x:.1f}" y="{by:.1f}" width="{bw}" height="{bh:.1f}" '
            f'class="b{i}"><title>{ds}: {secs/3600:.1f}h</title></rect>')
        if secs > 0:
            vt = f"{secs/3600:.1f}h" if secs >= 3600 else f"{int(secs/60)}m"
            parts.append(f'<text x="{x+bw/2:.1f}" y="{by-3:.1f}" class="val">{vt}</text>')
        parts.append(f'<text x="{x+bw/2:.1f}" y="{H-10}" class="lab">{ds}</text>')
        x += bw + gap

    parts.append("</svg>")
    return "\n".join(parts)


# ── SVG: Ring / Donut Chart ──────────────────────────────────────────────

def svg_ring(title: str, items: list[tuple[str, float]], filename: str, *,
             center_label: str = "", width: int = 280, height: int = 260) -> str | None:
    """Donut chart with per-segment stroke-dasharray draw-in animation.

    Each segment gets its own @keyframes (no CSS custom properties for max
    GitHub sanitizer compatibility). Segments animate one after another with
    0.3s delay between them.
    """
    if not items:
        return None
    total = sum(v for _, v in items)
    if total <= 0:
        return None

    cx, cy = 98, 88
    mid_r = 54.0
    sw = 20.0
    circumference = 2.0 * math.pi * mid_r

    colored = [(name, val, PALETTE[i % len(PALETTE)]) for i, (name, val) in enumerate(items)]

    # Build CSS: one @keyframes per segment + one class per segment
    css = ['<style>',
           '.tl{fill:#111827;font-size:11px;font-weight:600;font-family:system-ui,sans-serif;text-anchor:middle}',
           '.lg{fill:#374151;font-size:10px;font-family:system-ui,sans-serif}',
           '.lp{fill:#6b7280;font-size:9px;font-family:system-ui,sans-serif}',
           '.ct{fill:#111827;font-size:15px;font-weight:700;font-family:system-ui,sans-serif;text-anchor:middle}',
           '.cu{fill:#6b7280;font-size:10px;font-family:system-ui,sans-serif;text-anchor:middle}',
           '.swatch{opacity:0;animation:fadein 0.3s ease-out forwards}',
           '@keyframes fadein{from{opacity:0}to{opacity:1}}']

    cumulative = 0.0
    seg_class_names: list[str] = []
    for i, (name, val, color) in enumerate(colored):
        pct = val / total
        dash_len = pct * circumference
        delay = i * 0.3
        # Each segment animates dasharray from 0 to target length
        css.append(
            f'@keyframes s{i}{{'
            f'from{{stroke-dasharray:0 {circumference:.4f}}}'
            f'to{{stroke-dasharray:{dash_len:.4f} {circumference - dash_len:.4f}}}}}')
        cls = f's{i}'
        css.append(
            f'.{cls}{{animation:s{i} 0.3s {delay:.2f}s ease-out forwards;'
            f'fill:none;stroke:{color};stroke-width:{sw};'
            f'stroke-dashoffset:{circumference * 0.25 - cumulative:.4f};stroke-linecap:butt}}')
        seg_class_names.append(cls)
        cumulative += dash_len
    css.append('</style>')

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img">',
        *css,
        f'<text x="{cx}" y="16" class="tl">{title}</text>',
    ]

    # Ring segments
    for cls in seg_class_names:
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{mid_r:.1f}" class="{cls}"/>')

    # Center text
    if center_label:
        parts.append(f'<text x="{cx:.1f}" y="{cy-4:.1f}" class="ct" style="opacity:0;animation:fadein 0.4s {0.3*len(colored):.2f}s ease-out forwards">{_fmt_num(int(total))}</text>')
        parts.append(f'<text x="{cx:.1f}" y="{cy+12:.1f}" class="cu" style="opacity:0;animation:fadein 0.4s {0.3*len(colored):.2f}s ease-out forwards">{center_label}</text>')

    # Legend
    ly = int(cy + mid_r + sw + 8)
    n = len(colored)
    cols = 2 if n > 4 else 1
    per_col = (n + cols - 1) // cols
    for i, (name, val, color) in enumerate(colored):
        col = i // per_col
        row = i % per_col
        lx = 14 + col * (width // 2)
        y = ly + row * 16
        delay = 0.3 * len(colored) + i * 0.1
        parts.append(
            f'<rect x="{lx}" y="{y-5}" width="8" height="8" rx="2" fill="{color}" '
            f'style="opacity:0;animation:fadein 0.3s {delay:.2f}s ease-out forwards"/>')
        pct = val / total * 100
        parts.append(
            f'<text x="{lx+12}" y="{y+2}" class="lg" '
            f'style="opacity:0;animation:fadein 0.3s {delay:.2f}s ease-out forwards">{name}</text>')
        parts.append(
            f'<text x="{lx+12+85}" y="{y+2}" class="lp" '
            f'style="opacity:0;animation:fadein 0.3s {delay:.2f}s ease-out forwards">{pct:.1f}%</text>')

    parts.append("</svg>")
    svg = "\n".join(parts)
    _save_svg(filename, svg)
    return f'<img src="https://raw.githubusercontent.com/di-hhh/di-hhh/main/dist/{filename}" width="{width}" alt="{title}"/>'


def _fmt_num(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def svg_stacked_bar(title: str, items: list[tuple[str, float, str]],
                    filename: str) -> str | None:
    """Horizontal stacked bar with scaleX reveal animation.

    items: [(name, percent, time_text), ...]
    If percentages sum to less than 98%, an "Other" segment fills the bar.
    """
    if not items:
        return None

    W, H = 600, 150
    bar_x, bar_y, bar_w, bar_h = 16, 36, 568, 24
    legend_y = bar_y + bar_h + 20

    # Ensure bar is always fully filled
    total_pct = sum(pct for _, pct, _ in items)
    all_items = list(items)
    if total_pct < 98.0 and total_pct > 0:
        remaining = max(0.0, 100.0 - total_pct)
        all_items.append(("Other", remaining, ""))

    n = len(all_items)
    anim_dur = 0.6  # total reveal duration

    # CSS: reveal animation for the bar group, fade-in for legend
    css = [
        '<style>',
        f'@keyframes r{{from{{transform:scaleX(0)}}to{{transform:scaleX(1)}}}}',
        '@keyframes fi{from{opacity:0}to{opacity:1}}',
        f'.bar{{animation:r {anim_dur}s ease-out forwards;'
        f'transform-origin:{bar_x}px {bar_y + bar_h/2:.0f}px}}',
        '.tt{fill:#111827;font-size:13px;font-weight:600;font-family:system-ui,sans-serif}',
        '.sw{fill:#374151;font-size:10px;font-family:system-ui,sans-serif}',
        '.sp{fill:#6b7280;font-size:10px;font-family:system-ui,sans-serif}',
        '.st{fill:#6b7280;font-size:9px;font-family:system-ui,sans-serif}',
        '</style>',
    ]

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}" role="img">',
        *css,
        f'<text x="16" y="20" class="tt">{title}</text>',
    ]

    # Segments — wrapped in a <g> that scales from left
    parts.append(f'<g class="bar">')
    x = bar_x
    last_i = n - 1
    for i, (name, pct, time_txt) in enumerate(all_items):
        if pct <= 0:
            continue
        seg_w = pct / 100.0 * bar_w
        # Force last segment to fill exactly to the bar end
        if i == last_i:
            seg_w = (bar_x + bar_w) - x
        if seg_w < 0.5:
            continue
        color = PALETTE[i % len(PALETTE)]
        parts.append(
            f'<rect x="{x:.1f}" y="{bar_y}" width="{seg_w:.2f}" height="{bar_h}" '
            f'fill="{color}"><title>{name}: {pct:.1f}%{chr(32)+"("+time_txt+")" if time_txt else ""}</title></rect>')
        if seg_w > 40 and name != "Other":
            parts.append(
                f'<text x="{x + seg_w/2:.1f}" y="{bar_y + bar_h/2 + 4:.1f}" '
                f'text-anchor="middle" fill="#fff" font-size="10" '
                f'font-family="system-ui,sans-serif" font-weight="600">{pct:.1f}%</text>')
        x += seg_w
    parts.append('</g>')

    # Bar outline — fades in after the bar reveals
    parts.append(
        f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" '
        f'fill="none" stroke="#d1d5db" stroke-width="1" rx="4" '
        f'style="opacity:0;animation:fi 0.3s {anim_dur}s ease-out forwards"/>')

    # Legend — fades in after the bar animation
    cols = 2 if n > 5 else 1
    per_col = (n + cols - 1) // cols
    for i, (name, pct, time_txt) in enumerate(all_items):
        col = i // per_col
        row = i % per_col
        lx = 16 + col * (W // 2)
        ly = legend_y + row * 15
        color = PALETTE[i % len(PALETTE)]
        delay = anim_dur + i * 0.08
        parts.append(
            f'<rect x="{lx}" y="{ly - 5}" width="8" height="8" rx="2" fill="{color}" '
            f'style="opacity:0;animation:fi 0.3s {delay:.2f}s ease-out forwards"/>')
        parts.append(
            f'<text x="{lx + 12}" y="{ly + 2}" class="sw" '
            f'style="opacity:0;animation:fi 0.3s {delay:.2f}s ease-out forwards">{name}</text>')
        parts.append(
            f'<text x="{lx + 12 + 110}" y="{ly + 2}" class="sp" '
            f'style="opacity:0;animation:fi 0.3s {delay:.2f}s ease-out forwards">{pct:.1f}%</text>')
        if time_txt:
            parts.append(
                f'<text x="{lx + 12 + 150}" y="{ly + 2}" class="st" '
                f'style="opacity:0;animation:fi 0.3s {delay:.2f}s ease-out forwards">{time_txt}</text>')

    parts.append("</svg>")
    svg = "\n".join(parts)
    _save_svg(filename, svg)
    return f'<img src="https://raw.githubusercontent.com/di-hhh/di-hhh/main/dist/{filename}" width="{W}" alt="{title}"/>'


def _ring_pair(chart_a: str | None, chart_b: str | None) -> str:
    """Wrap two <img> tags in an HTML table row so they display side by side."""
    a = chart_a or ""
    b = chart_b or ""
    if not a and not b:
        return ""
    return f'<table><tr><td>{a}</td><td>{b}</td></tr></table>'


# ── Content Assembly ─────────────────────────────────────────────────────

def build_block(stats: dict[str, Any], days: list[dict[str, Any]] | None) -> str:
    lines: list[str] = []
    dr = date_range(stats)

    # Header + daily chart
    lines.append(f"📊 **Weekly Coding Stats**（{dr}）  ")
    lines.append("")
    act = svg_daily_activity(days or [])
    if act:
        _save_svg("waka-activity.svg", act)
        lines.append(
            f'<img src="https://raw.githubusercontent.com/di-hhh/di-hhh/main/dist/waka-activity.svg" '
            f'width="600" alt="Daily Coding Activity"/>  '
        )
        lines.append("")

    # Summary
    total = stats.get("human_readable_total", "0 secs")
    dai = stats.get("human_readable_daily_average", "0 secs")
    bd = best_day(stats)
    lines.append(f"⏱️ **Total:** {total}  ")
    lines.append(f"📅 **Daily Average:** {dai}  ")
    lines.append(f"⭐ **Best Day:** {bd}  ")
    lines.append("")

    # ── Ring charts: row 1 (AI vs Manual + Editors) ──
    ai_add = stats.get("ai_additions", 0) or 0
    hu_add = stats.get("human_additions", 0) or 0
    r_ai = svg_ring("🤖 AI vs Manual Coding",
                     [("AI Assisted", float(ai_add)), ("Manual", float(hu_add))],
                     "waka-ring-ai.svg", center_label="total lines")

    editors = stats.get("editors", [])
    r_ed = svg_ring("💻 Editors",
                    [(e.get("name", "?"), float(e.get("total_seconds", 0))) for e in editors],
                    "waka-ring-editors.svg")

    pair1 = _ring_pair(r_ai, r_ed)
    if pair1:
        lines.append(pair1)
        lines.append("")

    # ── Ring charts: row 2 (OS + Categories) ──
    os_list = stats.get("operating_systems", [])
    r_os = svg_ring("🖥️ Operating Systems",
                    [(o.get("name", "?"), float(o.get("total_seconds", 0))) for o in os_list],
                    "waka-ring-os.svg")

    cats = stats.get("categories", [])
    r_cat = svg_ring("📂 Categories",
                     [(c.get("name", "?"), float(c.get("total_seconds", 0))) for c in cats],
                     "waka-ring-categories.svg")

    pair2 = _ring_pair(r_os, r_cat)
    if pair2:
        lines.append(pair2)
        lines.append("")

    # ── AI detail text ──
    ai_del = stats.get("ai_deletions", 0) or 0
    hu_del = stats.get("human_deletions", 0) or 0
    tokens_in = stats.get("ai_input_tokens", 0) or 0
    tokens_out = stats.get("ai_output_tokens", 0) or 0
    cost = stats.get("ai_agent_total_cost", 0) or 0
    sessions = stats.get("ai_sessions", 0) or 0
    lines.append(
        f"🤖 **AI Details:** {_fmt_num(ai_add)} lines added / {_fmt_num(ai_del)} deleted  ·  "
        f"Tokens: {_fmt_num(tokens_in)} in / {_fmt_num(tokens_out)} out  ·  "
        f"Sessions: {sessions}  ·  Est. cost: ${cost:.2f}  "
    )
    lines.append("")

    # ── Languages (stacked bar chart) ──
    langs = stats.get("languages", [])
    lang_items = [(l.get("name", "?"), l.get("percent", 0.0), l.get("text", "?")) for l in langs[:LANG_LIMIT]]
    lang_svg = svg_stacked_bar("📝 Languages", lang_items, "waka-langs.svg")
    if lang_svg:
        lines.append(lang_svg)

    return "\n".join(lines)


# ── File I/O ─────────────────────────────────────────────────────────────

def _ensure_dist() -> None:
    os.makedirs(DIST_DIR, exist_ok=True)


def _save_svg(filename: str, content: str) -> None:
    if not content:
        return
    _ensure_dist()
    path = os.path.join(DIST_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Saved {path} ({len(content)} bytes)")


def update_readme(block: str) -> bool:
    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    pattern = re.compile(re.escape(START_TAG) + r"[\s\S]*?" + re.escape(END_TAG))
    if not pattern.search(content):
        print(f"error: {START_TAG} ... {END_TAG} not found")
        return False
    replacement = f"{START_TAG}\n{block}\n{END_TAG}"
    new = pattern.sub(replacement, content)
    if new == content:
        print("No changes to README.md.")
        return False
    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(new)
    print("README.md updated.")
    return True


# ── Entry ────────────────────────────────────────────────────────────────

def main() -> int:
    api_key = os.environ.get("WAKATIME_API_KEY", "")
    if not api_key:
        print("error: WAKATIME_API_KEY not set")
        return 1

    stats = fetch_stats(api_key)
    if stats is None:
        print("stats API failed, aborting.")
        return 1

    days = fetch_summaries(api_key)
    if days is None:
        print("summaries API failed, daily chart will be skipped.")

    block = build_block(stats, days)
    update_readme(block)
    print("---- output ----")
    print(block)
    print("----------------")
    return 0


if __name__ == "__main__":
    sys.exit(main())
