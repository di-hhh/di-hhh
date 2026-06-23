#!/usr/bin/env python3
"""拉取 WakaTime stats + summaries API，格式化多维度编码统计并生成 SVG 图表，
替换 README.md 中 <!--START_SECTION:waka--> … <!--END_SECTION:waka--> 之间的内容。

生成的 SVG 文件保存到 dist/ 目录，与 README.md 在同一 commit 中提交到 main 分支。

零外部依赖，仅使用 Python 标准库。
"""

from __future__ import annotations

import json
import os
import re
import sys
import io
from base64 import b64encode
from datetime import datetime, timezone
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ── 兼容 Windows GBK & CI UTF-8 ──────────────────────────────────────────
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ── 常量 ─────────────────────────────────────────────────────────────────
README_PATH = "README.md"
START_TAG = "<!--START_SECTION:waka-->"
END_TAG = "<!--END_SECTION:waka-->"
DIST_DIR = "dist"

API_BASE = "https://wakatime.com"
STATS_PATH = "/api/v1/users/current/stats/last_7_days"
SUMMARIES_PATH = "/api/v1/users/current/summaries?range=last_7_days"

BAR_WIDTH = 20
GRADIENT = "░▒▓█"
GRADIENT_LEVELS = len(GRADIENT)

LANG_LIMIT = 10
EDITOR_LIMIT = 5
OS_LIMIT = 5
CATEGORY_LIMIT = 5

# ── 工具函数 ─────────────────────────────────────────────────────────────

def render_bar(percent: float, width: int = BAR_WIDTH) -> str:
    """4 级渐变字符进度条：░ → ▒ → ▓ → █。"""
    total_units = width * GRADIENT_LEVELS
    filled = round(percent / 100.0 * total_units)
    filled = max(0, min(total_units, filled))

    chars: list[str] = []
    for i in range(width):
        cell = filled - i * GRADIENT_LEVELS
        if cell <= 0:
            chars.append(GRADIENT[0])
        elif cell >= GRADIENT_LEVELS:
            chars.append(GRADIENT[-1])
        else:
            chars.append(GRADIENT[cell])
    return "".join(chars)


def format_date_range(stats: dict[str, Any]) -> str:
    """从 stats 返回体中提取日期范围。兼容 range 是对象或字符串两种情况。"""
    rng: Any = stats.get("range", {})
    if isinstance(rng, str):
        rng = {}
    start = rng.get("start_date", "") or stats.get("start", "")[:10] or "?"
    end = rng.get("end_date", "") or stats.get("end", "")[:10] or "?"
    return f"{start} ~ {end}"


def format_best_day(stats: dict[str, Any]) -> str:
    """"最佳编码日" → 星期 月 日 — 时长。"""
    best = stats.get("best_day")
    if not best:
        return "N/A"
    date_str = best.get("date", "")
    time_str = best.get("text", "")
    if not date_str or not time_str:
        return "N/A"
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_str = dt.strftime("%a %b %d")
    except (ValueError, TypeError):
        pass
    return f"{date_str} — {time_str}"


def format_section(
    emoji: str, title: str, items: list[dict[str, Any]], limit: int
) -> str:
    """渲染一个分布表格：emoji 标题 + 每条目的进度条（行尾两个空格 = Markdown <br>）。"""
    lines = [f"\n**{emoji} {title}**  "]
    if not items:
        lines.append("_No data_")
        return "\n".join(lines)

    visible = items[:limit]
    max_name = max(len(it.get("name", "?")) for it in visible)

    for item in visible:
        name = item.get("name", "?")
        percent = item.get("percent", 0.0)
        text = item.get("text", "?")
        bar = render_bar(percent)
        lines.append(f"{name:<{max_name}}  {bar}  {percent:5.2f}%  {text}  ")
    return "\n".join(lines)


# ── API ──────────────────────────────────────────────────────────────────

def _make_auth_header(api_key: str) -> str:
    encoded = b64encode(api_key.encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def _fetch_json(url: str, auth_header: str) -> dict[str, Any] | None:
    """GET JSON from a URL, returning the parsed body or None on failure."""
    try:
        req = Request(url, headers={"Authorization": auth_header})
        with urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        print(f"warn: {url} returned HTTP {e.code}")
        return None
    except URLError as e:
        print(f"warn: {url} — {e.reason}")
        return None
    return body


def fetch_stats(api_key: str) -> dict[str, Any] | None:
    """调用 /stats/last_7_days 返回 data 字段。"""
    body = _fetch_json(API_BASE + STATS_PATH, _make_auth_header(api_key))
    if body is None:
        return None
    if err := body.get("error") or body.get("errors"):
        print(f"warn: stats API error — {err}")
        return None
    return body.get("data")


def fetch_summaries(api_key: str) -> list[dict[str, Any]] | None:
    """调用 /summaries?range=last_7_days 返回 data 数组（每天一条）。"""
    body = _fetch_json(API_BASE + SUMMARIES_PATH, _make_auth_header(api_key))
    if body is None:
        return None
    if err := body.get("error") or body.get("errors"):
        print(f"warn: summaries API error — {err}")
        return None
    data = body.get("data")
    if not isinstance(data, list):
        print(f"warn: summaries data is not a list")
        return None
    return data


# ── SVG 生成 ─────────────────────────────────────────────────────────────

def svg_daily_activity(days: list[dict[str, Any]]) -> str:
    """7 天竖柱图，展示每日编码时长。"""
    if not days or len(days) < 2:
        return ""

    # 从 summaries 中提取每日 total_seconds
    daily: list[tuple[str, float]] = []
    for d in days:
        gt = d.get("grand_total", {})
        total = gt.get("total_seconds", 0.0)
        date = d.get("range", {}).get("date", "")[-5:]  # MM-DD
        daily.append((date, total))

    max_secs = max(v for _, v in daily) or 1

    W, H = 600, 200
    MARGIN_L, MARGIN_R, MARGIN_T, MARGIN_B = 52, 12, 24, 32
    chart_w = W - MARGIN_L - MARGIN_R
    chart_h = H - MARGIN_T - MARGIN_B
    bar_gap = 10
    bar_w = max(8, (chart_w - bar_gap * (len(daily) - 1)) // len(daily))

    # Y 轴刻度（0 到 max_secs，最多 4 条线）
    y_ticks = 4
    step = max_secs / y_ticks if max_secs > 0 else 1

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}" role="img">',
        "<style>",
        "  .bar { fill: #3b82f6; rx: 3; }",
        "  .bar:hover { fill: #2563eb; }",
        "  .grid { stroke: #e5e7eb; stroke-width: 0.5; }",
        "  .tick { fill: #6b7280; font-size: 10px; font-family: -apple-system,BlinkMacSystemFont,sans-serif; }",
        "  .label { fill: #374151; font-size: 11px; font-family: -apple-system,BlinkMacSystemFont,sans-serif; text-anchor: middle; }",
        "  .title { fill: #111827; font-size: 13px; font-weight: 600; font-family: -apple-system,BlinkMacSystemFont,sans-serif; }",
        "  .val { fill: #6b7280; font-size: 10px; font-family: -apple-system,BlinkMacSystemFont,sans-serif; text-anchor: middle; }",
        "</style>",
        f'<text x="{MARGIN_L}" y="18" class="title">📅 每日编码时间</text>',
    ]

    # 网格线与 Y 轴标签
    for i in range(y_ticks + 1):
        y = MARGIN_T + chart_h - (chart_h * i / y_ticks)
        svg_parts.append(
            f'<line x1="{MARGIN_L}" y1="{y:.1f}" '
            f'x2="{W - MARGIN_R}" y2="{y:.1f}" class="grid"/>'
        )
        hours = step * i / 3600
        svg_parts.append(
            f'<text x="{MARGIN_L - 6}" y="{y + 3:.1f}" class="tick" text-anchor="end">'
            f"{hours:.1f}h</text>"
        )

    # 柱状条
    x = MARGIN_L + bar_gap // 2
    for date_str, secs in daily:
        bar_h_val = (secs / max_secs) * chart_h if max_secs > 0 else 0
        bar_h_val = max(0, min(chart_h, bar_h_val))
        bar_y = MARGIN_T + chart_h - bar_h_val
        svg_parts.append(
            f'<rect x="{x:.1f}" y="{bar_y:.1f}" width="{bar_w}" height="{bar_h_val:.1f}" class="bar">'
            f'<title>{date_str}: {secs/3600:.1f}h</title></rect>'
        )
        # 柱顶数值
        if secs > 0:
            val_text = f"{secs/3600:.1f}h" if secs >= 3600 else f"{int(secs/60)}m"
            svg_parts.append(
                f'<text x="{x + bar_w/2:.1f}" y="{bar_y - 4:.1f}" class="val">{val_text}</text>'
            )
        # X 轴标签
        svg_parts.append(
            f'<text x="{x + bar_w/2:.1f}" y="{H - 10}" class="label">{date_str}</text>'
        )
        x += bar_w + bar_gap

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def svg_ai_vs_human(stats: dict[str, Any]) -> str:
    """AI vs 人工编码对比柱状图。"""
    W, H = 460, 160
    MARGIN_L, MARGIN_R, MARGIN_T, MARGIN_B = 64, 24, 24, 40

    ai_add = stats.get("ai_additions", 0) or 0
    ai_del = stats.get("ai_deletions", 0) or 0
    hu_add = stats.get("human_additions", 0) or 0
    hu_del = stats.get("human_deletions", 0) or 0

    chart_w = W - MARGIN_L - MARGIN_R
    chart_h = H - MARGIN_T - MARGIN_B
    max_val = max(ai_add, ai_del, hu_add, hu_del, 1)

    def bar_x(label: str) -> float:
        """每组两个柱：add / del 并排。"""
        group_w = chart_w / 4
        offsets = {"ai_add": 0, "ai_del": 1, "hu_add": 2, "hu_del": 3}
        base = MARGIN_L + offsets[label] * group_w
        return base + 6

    bar_w_val = max(8, chart_w / 4 / 2 - 4)

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}" role="img">',
        "<style>",
        "  .add { fill: #10b981; rx: 3; } .del { fill: #ef4444; rx: 3; }",
        "  .glabel { fill: #374151; font-size: 10px; font-family: -apple-system,BlinkMacSystemFont,sans-serif; text-anchor: middle; }",
        "  .gval { fill: #6b7280; font-size: 10px; font-family: -apple-system,BlinkMacSystemFont,sans-serif; text-anchor: middle; }",
        "  .title { fill: #111827; font-size: 13px; font-weight: 600; font-family: -apple-system,BlinkMacSystemFont,sans-serif; }",
        "  .legend { fill: #374151; font-size: 10px; font-family: -apple-system,BlinkMacSystemFont,sans-serif; }",
        "</style>",
        f'<text x="{MARGIN_L}" y="18" class="title">🤖 AI vs 人工编码（新增/删除行数）</text>',
        # 图例
        f'<rect x="{MARGIN_L}" y="28" width="10" height="10" class="add"/>',
        f'<text x="{MARGIN_L + 14}" y="36" class="legend">新增</text>',
        f'<rect x="{MARGIN_L + 44}" y="28" width="10" height="10" class="del"/>',
        f'<text x="{MARGIN_L + 58}" y="36" class="legend">删除</text>',
    ]

    for label, (val, cls) in {
        "ai_add": (ai_add, "add"),
        "ai_del": (ai_del, "del"),
        "hu_add": (hu_add, "add"),
        "hu_del": (hu_del, "del"),
    }.items():
        x = bar_x(label)
        h = (val / max_val) * chart_h if max_val > 0 else 0
        y = MARGIN_T + chart_h - h
        svg_parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w_val}" height="{h:.1f}" class="{cls}">'
            f'<title>{label}: {int(val)}</title></rect>'
        )
        svg_parts.append(
            f'<text x="{x + bar_w_val/2:.1f}" y="{y - 4:.1f}" class="gval">{int(val)}</text>'
        )

    # 分组标签
    for label, x_pos in [("AI 新增", "ai_add"), ("AI 删除", "ai_del"),
                          ("人工新增", "hu_add"), ("人工删除", "hu_del")]:
        svg_parts.append(
            f'<text x="{bar_x(x_pos) + bar_w_val/2:.1f}" y="{H - 14}" class="glabel">{label}</text>'
        )

    # Token 与费用信息
    tokens_in = stats.get("ai_input_tokens", 0) or 0
    tokens_out = stats.get("ai_output_tokens", 0) or 0
    cost = stats.get("ai_agent_total_cost", 0) or 0
    sessions = stats.get("ai_sessions", 0) or 0

    def _h(n: int) -> str:
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n/1_000:.1f}K"
        return str(n)

    info = f"Tokens: {_h(tokens_in)} in / {_h(tokens_out)} out   ·   AI 会话: {sessions}   ·   预估费用: ${cost:.2f}"
    svg_parts.append(
        f'<text x="{MARGIN_L}" y="{H - 2}" class="legend">{info}</text>'
    )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


# ── 内容生成 ─────────────────────────────────────────────────────────────

def build_block(stats: dict[str, Any], days: list[dict[str, Any]] | None) -> str:
    """构建完整的 markdown 区块（包含 SVG 引用 + 文字统计）。"""
    lines: list[str] = []

    date_range = format_date_range(stats)

    # ── 标题 + 每日图表 ──
    lines.append(f"📊 **本周编码统计**（{date_range}）  ")
    lines.append("")

    daily_svg = svg_daily_activity(days) if days else ""
    if daily_svg:
        _write_svg("waka-activity.svg", daily_svg)
        lines.append(
            f'<img src="https://raw.githubusercontent.com/di-hhh/di-hhh/main/dist/waka-activity.svg" '
            f'width="600" alt="每日编码时间" />  '
        )
        lines.append("")

    # ── 汇总 ──
    total = stats.get("human_readable_total", "0 secs")
    daily = stats.get("human_readable_daily_average", "0 secs")
    best = format_best_day(stats)

    lines.append(f"⏱️ **总时长:** {total}  ")
    lines.append(f"📅 **日均:** {daily}  ")
    lines.append(f"⭐ **最佳日:** {best}  ")
    lines.append("")

    # ── AI vs 人工图表 ──
    ai_svg = svg_ai_vs_human(stats)
    _write_svg("waka-ai-vs-human.svg", ai_svg)
    lines.append(
        f'<img src="https://raw.githubusercontent.com/di-hhh/di-hhh/main/dist/waka-ai-vs-human.svg" '
        f'width="460" alt="AI vs 人工编码" />  '
    )
    lines.append("")

    # ── 语言 ──
    lines.append(format_section("📝", "语言", stats.get("languages", []), LANG_LIMIT))
    lines.append("")

    # ── 编辑器 ──
    lines.append(format_section("💻", "编辑器", stats.get("editors", []), EDITOR_LIMIT))
    lines.append("")

    # ── 操作系统 ──
    lines.append(format_section("🖥️", "操作系统", stats.get("operating_systems", []), OS_LIMIT))
    lines.append("")

    # ── 活动类别 ──
    lines.append(format_section("📂", "活动类别", stats.get("categories", []), CATEGORY_LIMIT))

    return "\n".join(lines)


# ── 文件操作 ─────────────────────────────────────────────────────────────

def _ensure_dist() -> None:
    os.makedirs(DIST_DIR, exist_ok=True)


def _write_svg(filename: str, content: str) -> None:
    if not content:
        return
    _ensure_dist()
    path = os.path.join(DIST_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Saved {path} ({len(content)} bytes)")


def update_readme(block: str) -> bool:
    """替换 README.md 中占位符之间的内容。返回是否发生变更。"""
    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(re.escape(START_TAG) + r"[\s\S]*?" + re.escape(END_TAG))
    if not pattern.search(content):
        print(f"error: could not find {START_TAG} ... {END_TAG} in {README_PATH}")
        return False

    replacement = f"{START_TAG}\n{block}\n{END_TAG}"
    new_content = pattern.sub(replacement, content)
    if new_content == content:
        print("No changes detected in README.md.")
        return False

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("README.md updated with WakaTime stats.")
    return True


# ── 入口 ─────────────────────────────────────────────────────────────────

def main() -> int:
    api_key = os.environ.get("WAKATIME_API_KEY", "")
    if not api_key:
        print("error: WAKATIME_API_KEY env not set")
        return 1

    # 并行拉取两个 API
    stats = fetch_stats(api_key)
    if stats is None:
        print("stats API failed — aborting.")
        return 1

    days = fetch_summaries(api_key)
    if days is None:
        print("summaries API failed — will skip daily chart.")

    block = build_block(stats, days)
    update_readme(block)

    print("---- generated block ----")
    print(block)
    print("-------------------------")
    return 0


if __name__ == "__main__":
    sys.exit(main())
