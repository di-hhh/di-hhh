#!/usr/bin/env python3
"""调用 WakaTime stats API 拉取编码统计，格式化多维度数据并替换 README.md 中的占位符。

展示内容：
  1. 汇总行：总时长、日均、最佳日
  2. 语言分布
  3. 编辑器分布
  4. 操作系统分布

占位符：
    <!--START_SECTION:waka-->
    ... (会被替换的内容)
    <!--END_SECTION:waka-->

零外部依赖，仅使用 Python 标准库。
"""

import json
import os
import re
import sys
import io
from base64 import b64encode
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ── 兼容 Windows GBK & CI UTF-8 ──────────────────────────────────────────────
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ── 常量 ─────────────────────────────────────────────────────────────────────
README_PATH = "README.md"
START_TAG = "<!--START_SECTION:waka-->"
END_TAG = "<!--END_SECTION:waka-->"

API_BASE = "https://wakatime.com"
API_PATH = "/api/v1/users/current/stats/last_7_days"
API_URL = API_BASE + API_PATH

BAR_WIDTH = 20
GRADIENT = "░▒▓█"          # 4 级渐变，从空到满
GRADIENT_LEVELS = len(GRADIENT)  # 4

LANG_LIMIT = 10            # 语言最多展示条数
EDITOR_LIMIT = 5           # 编辑器最多展示条数
OS_LIMIT = 5               # 操作系统最多展示条数


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def render_bar(percent: float, width: int = BAR_WIDTH) -> str:
    """用 4 级渐变字符 ░▒▓█ 渲染百分比进度条。

    总精度 = width × 4 个单位，每个字符最多承载 4 个单位。
    例如 width=20 → 80 个单位 → 每单位 = 1.25%。
    """
    total_units = width * GRADIENT_LEVELS
    filled_units = round(percent / 100.0 * total_units)
    filled_units = max(0, min(total_units, filled_units))

    bar_chars = []
    for i in range(width):
        cell_fill = filled_units - i * GRADIENT_LEVELS
        if cell_fill <= 0:
            bar_chars.append(GRADIENT[0])       # ░
        elif cell_fill >= GRADIENT_LEVELS:
            bar_chars.append(GRADIENT[-1])      # █
        else:
            bar_chars.append(GRADIENT[cell_fill])  # ▒ / ▓
    return "".join(bar_chars)


def format_date_range(stats: dict) -> str:
    """从 API 返回体中提取并格式化日期范围。

    兼容两种返回格式：
      - range 是对象   → 取 range.start_date / range.end_date
      - range 是字符串 → 回退到顶层 start / end（ISO 8601 截取日期部分）
    """
    rng = stats.get("range", {})
    if isinstance(rng, str):
        rng = {}  # 字符串无法 .get()，替换为空字典走回退逻辑

    start = rng.get("start_date", "")
    end = rng.get("end_date", "")

    # 回退：从顶层 ISO 时间戳提取日期
    if not start:
        start_iso = stats.get("start", "")
        start = start_iso[:10] if start_iso else "?"
    if not end:
        end_iso = stats.get("end", "")
        end = end_iso[:10] if end_iso else "?"
    return f"{start} ~ {end}"


def format_best_day(stats: dict) -> str:
    """格式化"最佳编码日"：<星期 月 日> — 时长。"""
    best = stats.get("best_day")
    if not best:
        return "N/A"
    date_str = best.get("date", "?")
    time_str = best.get("text", "?")
    if not date_str or not time_str:
        return "N/A"
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_str = dt.strftime("%a %b %d")
    except (ValueError, TypeError):
        pass
    return f"{date_str} — {time_str}"


def format_section(
    emoji: str,
    title: str,
    items: list,
    limit: int,
) -> str:
    """渲染一个分布表格，包含 emoji 标题和每个条目的进度条。"""
    lines = [f"\n**{emoji} {title}**"]

    if not items:
        lines.append("_No data_")
        return "\n".join(lines)

    items = items[:limit]
    max_name = max(len(it.get("name", "?")) for it in items)

    for item in items:
        name = item.get("name", "?")
        percent = item.get("percent", 0.0)
        text = item.get("text", "?")
        bar = render_bar(percent)
        lines.append(
            f"{name:<{max_name}}  {bar}  {percent:5.2f}%  {text}"
        )
    return "\n".join(lines)


# ── API ──────────────────────────────────────────────────────────────────────

def fetch_stats(api_key: str) -> dict | None:
    """使用 HTTP Basic Auth 调用 WakaTime stats API。"""
    encoded = b64encode(api_key.encode("utf-8")).decode("ascii")
    req = Request(
        API_URL,
        headers={"Authorization": f"Basic {encoded}"},
    )
    try:
        with urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        body_str = e.read().decode("utf-8", errors="replace")
        print(f"error: API returned HTTP {e.code}")
        print(body_str[:500])
        return None
    except URLError as e:
        print(f"error: network or DNS failure — {e.reason}")
        return None

    # WakaTime 有时在 error 字段中返回消息
    if err := (body.get("error") or body.get("errors")):
        print(f"error: API error — {err}")
        return None

    data = body.get("data")
    if not data:
        print(f"error: unexpected API response, keys={list(body.keys())}")
        return None
    return data


# ── 内容生成 ─────────────────────────────────────────────────────────────────

def build_block(stats: dict) -> str:
    """根据 stats 数据构建完整的 markdown 区块。"""
    lines = []

    # ---- 汇总行 ----
    total = stats.get("human_readable_total", "0 secs")
    daily = stats.get("human_readable_daily_average", "0 secs")
    best = format_best_day(stats)
    date_range = format_date_range(stats)

    lines.append(f"📊 **本周编码统计**（{date_range}）")
    lines.append("")
    lines.append(
        f"⏱️ **总时长:** {total}"
        f"  ·  **日均:** {daily}"
        f"  ·  ⭐ **最佳日:** {best}"
    )

    # ---- 语言分布 ----
    lines.append(
        format_section("📝", "语言", stats.get("languages", []), LANG_LIMIT)
    )

    # ---- 编辑器分布 ----
    lines.append(
        format_section("💻", "编辑器", stats.get("editors", []), EDITOR_LIMIT)
    )

    # ---- 操作系统分布 ----
    lines.append(
        format_section("🖥️", "操作系统", stats.get("operating_systems", []), OS_LIMIT)
    )

    return "\n".join(lines)


# ── README 操作 ──────────────────────────────────────────────────────────────

def update_readme(block: str) -> bool:
    """替换 README.md 中占位符之间的内容。返回是否发生变更。"""
    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(
        re.escape(START_TAG) + r"[\s\S]*?" + re.escape(END_TAG)
    )

    if not pattern.search(content):
        print(
            f"error: could not find {START_TAG} ... {END_TAG} "
            f"in {README_PATH}"
        )
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


# ── 入口 ─────────────────────────────────────────────────────────────────────

def main() -> int:
    api_key = os.environ.get("WAKATIME_API_KEY", "")
    if not api_key:
        print("error: WAKATIME_API_KEY environment variable is not set")
        return 1

    stats = fetch_stats(api_key)
    if stats is None:
        print("Falling back — README not modified.")
        return 1

    block = build_block(stats)
    update_readme(block)

    print("---- generated block ----")
    print(block)
    print("-------------------------")
    return 0


if __name__ == "__main__":
    sys.exit(main())
