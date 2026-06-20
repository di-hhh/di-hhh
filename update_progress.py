#!/usr/bin/env python3
"""计算当前年份已过去百分比，生成进度条并替换 README.md 中的占位符。

占位符：
    <!-- YEAR_PROGRESS_START -->
    ... (会被替换的内容)
    <!-- YEAR_PROGRESS_END -->
"""

from datetime import datetime, timezone
import io
import re
import sys

# 确保 stdout 使用 UTF-8，避免在 Windows (GBK) 上打印 emoji / 方块字符时崩溃。
# CI (Ubuntu) 默认即 UTF-8，此行在该处为无操作。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

README_PATH = "README.md"
START_TAG = "<!-- YEAR_PROGRESS_START -->"
END_TAG = "<!-- YEAR_PROGRESS_END -->"

# 进度条总格数
BAR_LEN = 20
# 填充块与空白块字符
FILL = "█"
EMPTY = "░"


def compute_year_progress(now: datetime) -> float:
    """返回当前年份已过去的百分比 (0-100)。"""
    year = now.year
    start = datetime(year, 1, 1, tzinfo=now.tzinfo)
    end = datetime(year + 1, 1, 1, tzinfo=now.tzinfo)
    elapsed = now - start
    total = end - start
    return (elapsed.total_seconds() / total.total_seconds()) * 100.0


def render_bar(percent: float) -> str:
    """根据百分比生成形如 ████████░░░░░░░░░░ 的进度条字符串。"""
    filled = round(percent / 100.0 * BAR_LEN)
    # 防止四舍五入后越界
    filled = max(0, min(BAR_LEN, filled))
    return FILL * filled + EMPTY * (BAR_LEN - filled)


def build_block(now: datetime) -> str:
    """生成要写入占位符之间的完整文本块。"""
    percent = compute_year_progress(now)
    bar = render_bar(percent)
    progress_line = f"⏳ Year Progress [{bar}] {percent:.2f} %"
    # RFC 2822 风格时间，使用 UTC
    updated_line = now.strftime("⏰ Updated on %a, %d %b %Y %H:%M:%S UTC")
    return f"{progress_line}\n{updated_line}"


def update_readme(block: str) -> bool:
    """替换 README.md 中占位符之间的内容。返回是否发生改动。"""
    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(
        re.escape(START_TAG) + r"[\s\S]*?" + re.escape(END_TAG)
    )

    if not pattern.search(content):
        print(f"error: could not find placeholders {START_TAG} ... {END_TAG} in {README_PATH}")
        return False

    replacement = f"{START_TAG}\n{block}\n{END_TAG}"
    new_content = pattern.sub(replacement, content)

    if new_content == content:
        print("No changes detected in README.md.")
        return False

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("README.md updated with new year progress.")
    return True


def main() -> int:
    now = datetime.now(timezone.utc)
    block = build_block(now)
    changed = update_readme(block)
    # 始终打印最终内容，方便 CI 日志查看
    print("---- generated block ----")
    print(block)
    print("-------------------------")
    return 0 if changed is not None else 1


if __name__ == "__main__":
    sys.exit(main())
