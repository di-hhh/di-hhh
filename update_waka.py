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

BAR_WIDTH = 20
GRADIENT = "░▒▓█"
GRADIENT_N = len(GRADIENT)

# Color palette for ring charts
PALETTE = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6",
           "#06b6d4", "#f97316", "#84cc16", "#ec4899", "#6366f1"]

LANG_LIMIT = 10
CATEGORY_LIMIT = 5

# ── Helpers ──────────────────────────────────────────────────────────────

def render_bar(percent: float) -> str:
    """4-level gradient bar: ░ → ▒ → ▓ → █."""
    total = BAR_WIDTH * GRADIENT_N
    filled = round(percent / 100.0 * total)
    filled = max(0, min(total, filled))
    chars = []
    for i in range(BAR_WIDTH):
        c = filled - i * GRADIENT_N
        if c <= 0:      chars.append(GRADIENT[0])
        elif c >= GRADIENT_N: chars.append(GRADIENT[-1])
        else:           chars.append(GRADIENT[c])
    return "".join(chars)


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


def text_section(emoji: str, title: str, items: list[dict[str, Any]], limit: int) -> str:
    """Text bar section. Two trailing spaces on each line = markdown <br>."""
    lines = [f"\n**{emoji} {title}**  "]
    if not items:
        lines.append("_No data_")
        return "\n".join(lines)
    visible = items[:limit]
    w = max(len(it.get("name", "?")) for it in visible)
    for it in visible:
        name = it.get("name", "?")
        pct = it.get("percent", 0.0)
        txt = it.get("text", "?")
        bar = render_bar(pct)
        lines.append(f"{name:<{w}}  {bar}  {pct:5.2f}%  {txt}  ")
    return "\n".join(lines)


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
    """7-day vertical bar chart."""
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
    ML, MR, MT, MB = 50, 12, 24, 32
    cw, ch = W - ML - MR, H - MT - MB
    gap = 10
    bw = max(8, (cw - gap * (len(daily) - 1)) // len(daily))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img">',
        '<style>.b{fill:#3b82f6;rx:3}.b:hover{fill:#2563eb}.grid{stroke:#e5e7eb;stroke-width:.5}',
        '.tick{fill:#6b7280;font-size:10px;font-family:system-ui,sans-serif}',
        '.lab{fill:#374151;font-size:10px;font-family:system-ui,sans-serif;text-anchor:middle}',
        '.val{fill:#6b7280;font-size:9px;font-family:system-ui,sans-serif;text-anchor:middle}',
        '.tit{fill:#111827;font-size:13px;font-weight:600;font-family:system-ui,sans-serif}</style>',
        f'<text x="{ML}" y="18" class="tit">📅 Daily Coding Activity</text>',
    ]

    ticks = 4
    step = max_s / ticks if max_s else 1
    for i in range(ticks + 1):
        y = MT + ch - (ch * i / ticks)
        parts.append(f'<line x1="{ML}" y1="{y:.1f}" x2="{W-MR}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{ML-4}" y="{y+3:.1f}" class="tick" text-anchor="end">{step*i/3600:.1f}h</text>')

    x = ML + gap // 2
    for ds, secs in daily:
        bh = (secs / max_s) * ch if max_s else 0
        bh = max(0, min(ch, bh))
        by = MT + ch - bh
        parts.append(f'<rect x="{x:.1f}" y="{by:.1f}" width="{bw}" height="{bh:.1f}" class="b"><title>{ds}: {secs/3600:.1f}h</title></rect>')
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
    """Generate a donut chart SVG.

    items: [(label, value), ...] — percentages computed from values.
    center_label: subtitle shown below the center number. Omit for no center text.
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

    # Assign colors
    colored = [(name, val, PALETTE[i % len(PALETTE)]) for i, (name, val) in enumerate(items)]

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img">',
        '<style>',
        '.tl{fill:#111827;font-size:11px;font-weight:600;font-family:system-ui,sans-serif;text-anchor:middle}',
        '.lg{fill:#374151;font-size:10px;font-family:system-ui,sans-serif}',
        '.lp{fill:#6b7280;font-size:9px;font-family:system-ui,sans-serif}',
        '.ct{fill:#111827;font-size:15px;font-weight:700;font-family:system-ui,sans-serif;text-anchor:middle}',
        '.cu{fill:#6b7280;font-size:10px;font-family:system-ui,sans-serif;text-anchor:middle}',
        '</style>',
        f'<text x="{cx}" y="16" class="tl">{title}</text>',
    ]

    # Ring segments using stroke-dasharray
    cumulative = 0.0
    for name, val, color in colored:
        pct = val / total
        dash_len = pct * circumference
        # SVG circles start at 3 o'clock; offset by 1/4 circumference to start at 12 o'clock
        offset = circumference * 0.25 - cumulative
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{mid_r:.1f}" '
            f'fill="none" stroke="{color}" stroke-width="{sw}" '
            f'stroke-dasharray="{dash_len:.4f} {circumference - dash_len:.4f}" '
            f'stroke-dashoffset="{offset:.4f}" stroke-linecap="butt">'
            f'<title>{name}: {pct*100:.1f}%</title></circle>'
        )
        cumulative += dash_len

    # Center text — only if a label is requested
    if center_label:
        parts.append(f'<text x="{cx:.1f}" y="{cy-4:.1f}" class="ct">{_fmt_num(int(total))}</text>')
        parts.append(f'<text x="{cx:.1f}" y="{cy+12:.1f}" class="cu">{center_label}</text>')

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
        parts.append(f'<rect x="{lx}" y="{y-5}" width="8" height="8" rx="2" fill="{color}"/>')
        pct = val / total * 100
        parts.append(f'<text x="{lx+12}" y="{y+2}" class="lg">{name}</text>')
        parts.append(f'<text x="{lx+12+85}" y="{y+2}" class="lp">{pct:.1f}%</text>')

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

    # ── Languages (text bars) ──
    lines.append(text_section("📝", "Languages", stats.get("languages", []), LANG_LIMIT))

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
