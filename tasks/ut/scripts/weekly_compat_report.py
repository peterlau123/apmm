#!/usr/bin/env python3
"""每周兼容性问题检查报告 (2026-08-06).

用途: 维护 apmm / Minimax-M2.7 辅助验证的日常机制:
- daily 模式 (每日 18:00 cron): 检查昨天 18:00 ~ 今天 18:00 新增的
  reports/incidents, 有新增则输出摘要 (无新增静默)
- weekly 模式 (每周五 17:00 cron): 汇总整周 (上周五 17:00 ~ 本周五 17:00)
  的 reports/incidents + ut_logs.db 入库增量, 生成
  reports/weekly/YYYY-MM-DD-compat-check.md (相对上周增量发现, 精简直击问题)

用法:
  python3 tasks/ut/scripts/weekly_compat_report.py --mode daily|weekly [--dry-run]
"""
import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPORTS_DIR = PROJECT_ROOT / "tasks" / "ut" / "docs" / "reports"
INCIDENTS_DIR = PROJECT_ROOT / "tasks" / "ut" / "docs" / "incidents"
WEEKLY_DIR = REPORTS_DIR / "weekly"
UT_LOGS_DB = Path("/gpfs/gcsp/liuxin/database/ut_logs.db")
TZ = timezone(timedelta(hours=8))  # 本机 +08:00


def window(daily: bool) -> tuple[datetime, datetime]:
    """返回检查窗口 (start, end). daily: 昨天 18:00~今天 18:00; weekly: 上周五 17:00~现在."""
    now = datetime.now(TZ)
    today_18 = now.replace(hour=18, minute=0, second=0, microsecond=0)
    if daily:
        return today_18 - timedelta(days=1), today_18
    # weekly: 最近的周五 17:00
    days_since_fri = (now.weekday() - 4) % 7
    last_fri_17 = (now - timedelta(days=days_since_fri)).replace(
        hour=17, minute=0, second=0, microsecond=0)
    return last_fri_17, now


def git_commit_time(f: Path) -> datetime | None:
    """文件最近一次 git 提交时间 (比 mtime 可靠——git checkout 会刷新 mtime)."""
    r = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "log", "-1", "--format=%cI", str(f)],
        capture_output=True, text=True)
    out = r.stdout.strip()
    if not out:
        return None  # 未提交的新文件
    try:
        return datetime.fromisoformat(out).astimezone(TZ)
    except ValueError:
        return None


def new_files(dirs: list[Path], start: datetime, end: datetime) -> list[tuple[Path, datetime]]:
    """扫描目录中 git 提交时间在窗口内的 .md 文件 (排除 README)."""
    out = []
    for d in dirs:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.md")):
            if f.name in ("README.md",):
                continue
            ct = git_commit_time(f) or datetime.fromtimestamp(f.stat().st_mtime, TZ)
            if start <= ct <= end:
                out.append((f, ct))
    return out


def ut_logs_increment(start: datetime, end: datetime) -> tuple[int, int]:
    """ut_logs.db 窗口内新增 runs / test_cases (indexed_at 为本地时间无时区)."""
    if not UT_LOGS_DB.exists():
        return 0, 0
    start_s = start.strftime("%Y-%m-%dT%H:%M:%S")
    end_s = end.strftime("%Y-%m-%dT%H:%M:%S")
    con = sqlite3.connect(str(UT_LOGS_DB))
    try:
        r = con.execute(
            "SELECT COUNT(*) FROM runs WHERE indexed_at >= ? AND indexed_at <= ?",
            (start_s, end_s)).fetchone()[0]
        # test_cases 无时间列, 通过 run_id JOIN runs 统计窗口内新增
        t = con.execute(
            "SELECT COUNT(*) FROM test_cases tc JOIN runs r ON tc.run_id = r.id "
            "WHERE r.indexed_at >= ? AND r.indexed_at <= ?",
            (start_s, end_s)).fetchone()[0]
        return r, t
    except sqlite3.Error:
        return 0, 0
    finally:
        con.close()


# 提取具体兼容性问题细节的关键词 (错误类型/API/症状)
DETAIL_KEYWORDS = [
    "illegal memory access", "not found", "runtimeerror", "xid", "cuda error",
    "timeout", "超时", "failed to start", "processraisedexception",
    "distnetworkerror", "segfault", "崩溃", "异常", "失败", "不兼容",
    "mismatch", "incompatible", "version conflict", "crash",
]


def extract_issue_details(f: Path) -> list[str]:
    """从报告/incident 提取具体兼容性问题细节 (错误/API/症状行), 最多 2 条.

    只提取含错误关键词且信息量足够的完整行; 无命中返回空 (周报填\"无\")."""
    hits = []
    seen = set()
    for ln in f.read_text(errors="ignore").splitlines():
        t = ln.strip()
        if len(t) < 15 or len(t) > 220:
            continue
        if t.startswith(("#", "|", "```", "---", "*", "-", ">", "`", "（", "(", "E ")):
            continue
        tl = t.lower()
        # 截断行 (以冒号/逗号/连接符结尾) 信息不完整, 跳过; Xid 证据行特判保留
        if t[-1] not in "。！？)）." and "xid" not in tl:
            continue
        if not any(k in tl for k in DETAIL_KEYWORDS):
            continue
        key = t[:80]
        if key in seen:
            continue
        seen.add(key)
        hits.append(t)
        if len(hits) >= 2:
            break
    return hits


def compat_issue_lines(files: list[tuple[Path, datetime]]) -> list[str]:
    """从本周报告/incident 文件提取兼容性问题要点 (标题行)."""
    lines = []
    for f, mt in files:
        title = ""
        for line in f.read_text(errors="ignore").splitlines():
            if line.startswith("# ") and title == "":
                title = line.lstrip("# ").strip()
                break
        kind = "incident" if "incidents" in str(f) else "report"
        lines.append(f"- **[{f.stem}]({f})** ({kind}) — {title}")
    return lines


def build_weekly_md(files, runs_inc, tc_inc, start, end) -> str:
    """生成周报 (精简, 直击问题, 开头说明相对上周增量)."""
    now = datetime.now(TZ)
    lines = [
        f"# 单元测试兼容性问题检查报告（vLLM 0.13.0 + torch 2.5.1）",
        f"\n> 窗口：{start:%Y-%m-%d %H:%M} ~ {end:%Y-%m-%d %H:%M}｜生成：{now:%Y-%m-%d %H:%M}",
        f"> **相对上周增量**：新增报告/incident **{len(files)}** 个，ut_logs 新增入库 runs **+{runs_inc}** / test_cases **+{tc_inc}**",
        "",
        "## 目录",
        "1. 本周增量发现",
        "2. 新增报告 / incidents",
        "3. ut_logs 入库增量",
        "4. 兼容性问题清单",
        "5. 结论与下周关注点",
        "",
        "## 1. 本周增量发现（相对上周）",
    ]
    # 从本周报告/incident 提取具体兼容性问题细节 (API/错误/症状), 无则填"无"
    detail_lines = []
    for f, mt in files:
        for d in extract_issue_details(f):
            rel = f.relative_to(PROJECT_ROOT)
            detail_lines.append(f"- **[{f.stem}]({rel})**: {d}")
    if detail_lines:
        lines += detail_lines
    else:
        lines.append("- 本周无新增具体兼容性问题细节（无新 API/错误类型报告）")
    lines += [
        "",
        "## 2. 新增报告 / incidents",
    ]
    if files:
        lines += [f"| 文件 | 类型 | 时间 |",
                  f"|---|---|---|"]
        lines += [f"| [{f.name}]({f.relative_to(PROJECT_ROOT)}) | "
                  f"{'incident' if 'incidents' in str(f) else 'report'} | {mt:%m-%d %H:%M} |"
                  for f, mt in files]
    else:
        lines.append("（无）")
    lines += [
        "",
        "## 3. ut_logs 入库增量",
        f"| 指标 | 本周新增 |",
        f"|---|---|",
        f"| runs | +{runs_inc} |",
        f"| test_cases | +{tc_inc} |",
        "",
        "## 4. 兼容性问题清单",
        "完整清单见 [2026-08-05-vllm-0.13.0-torch2.5.1-compat-issues.md]"
        "(../2026-08-05-vllm-0.13.0-torch2.5.1-compat-issues.md)。"
        "本周新增问题见 §2 列出的报告/incident。",
        "",
        "## 5. 结论与下周关注点",
        "- 待办：GPU 1 卡硬件维修（上报管理员）、慢测试 rendezvous timeout 优化",
        "",
        "*更新时间: 2026-08-06*",
        "",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["daily", "weekly"], required=True)
    ap.add_argument("--dry-run", action="store_true", help="只打印不写文件")
    args = ap.parse_args()

    start, end = window(args.mode == "daily")
    files = new_files([REPORTS_DIR, INCIDENTS_DIR, WEEKLY_DIR], start, end)
    runs_inc, tc_inc = ut_logs_increment(start, end)

    if args.mode == "daily":
        if not files:
            return  # 无新增 → 静默
        print(f"[compat-check {datetime.now(TZ):%m-%d %H:%M}] 昨日 18:00 后新增 "
              f"{len(files)} 个报告/incident:")
        for f, mt in files:
            print(f"  {mt:%m-%d %H:%M} {f.name}")
        return

    # weekly: 生成周报
    md = build_weekly_md(files, runs_inc, tc_inc, start, end)
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    out = WEEKLY_DIR / f"{datetime.now(TZ):%Y-%m-%d}-compat-check.md"
    if not args.dry_run:
        out.write_text(md, encoding="utf-8")
        # git 提交推送
        subprocess.run(["git", "-C", str(PROJECT_ROOT), "add", str(out)],
                       capture_output=True)
        subprocess.run(["git", "-C", str(PROJECT_ROOT), "commit", "-m",
                        f"docs(ut): 每周兼容性检查报告 {datetime.now(TZ):%Y-%m-%d}"],
                       capture_output=True)
        subprocess.run(["git", "-C", str(PROJECT_ROOT), "push",
                        "origin", "develop"], capture_output=True, timeout=60)
    print(md)


if __name__ == "__main__":
    main()
