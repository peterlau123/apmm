"""
发送飞书通知卡片
从 manifest.json 读取累计 statistics，按事件类型推送不同样式的卡片。

事件类型 (--event):
  progress   - 常规进度卡片（蓝色，每个 batch 完成后）
  complete   - workflow 完成汇总（绿色，pending == 0）
  alert      - 错误率/失败率超阈值告警（红色）
  paused     - workflow 暂停通知（黄色）
  resumed    - workflow 恢复通知（蓝色）

用法:
  python send_progress_card.py \
      --manifest-path MANIFEST.json \
      --feishu-config CONFIG.json \
      --event progress \
      --batch-id batch_003 \
      --iteration 128 \
      [--reason "..."]
"""

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from feishu_api import FeishuAPI


# 事件配置: (title_prefix, template_color, emoji)
EVENT_CONFIG = {
    "progress": ("UT Progress", "blue", "📊"),
    "complete": ("UT Workflow 完成", "green", "🏆"),
    "alert":    ("UT Workflow 告警", "red", "⚠️"),
    "paused":   ("UT Workflow 暂停", "yellow", "⏸️"),
    "resumed":  ("UT Workflow 恢复", "blue", "▶️"),
}


def build_progress_bar(percent: float, width: int = 20) -> str:
    filled = int(width * percent / 100)
    empty = width - filled
    bar = "█" * filled + "░" * empty
    return f"{bar} {percent:.1f}%"


def compute_stats(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    stats = manifest.get("statistics", {})

    total = stats.get("total", 0)
    passed = stats.get("passed", 0)
    failed = stats.get("failed", 0)
    error = stats.get("error", 0)
    ignored = stats.get("ignored", 0)
    pending = stats.get("pending", 0)
    executed = stats.get("executed", passed + failed + error + ignored)
    progress = stats.get("progress", (executed / total * 100) if total else 0)
    pass_rate = (passed / executed * 100) if executed > 0 else 0.0
    error_rate = (error / executed * 100) if executed else 0
    failure_rate = (failed / executed * 100) if executed else 0

    return {
        "total": total, "passed": passed, "failed": failed, "error": error,
        "ignored": ignored, "pending": pending, "executed": executed,
        "progress": progress, "pass_rate": pass_rate,
        "error_rate": error_rate, "failure_rate": failure_rate,
    }


def build_stats_block(s: dict) -> list:
    """构建统计信息块（各事件共用）"""
    progress_bar = build_progress_bar(s["progress"])
    return [
        f"**进度**: {progress_bar}",
        f"**已执行**: {s['executed']} / {s['total']}",
        "",
        f"✅ Passed: **{s['passed']}**",
        f"❌ Failed: **{s['failed']}**  ({s['failure_rate']:.1f}%)",
        f"⚠️ Error: **{s['error']}**  ({s['error_rate']:.1f}%)",
        f"⏭️ Ignored: **{s['ignored']}**",
        f"📋 Pending: **{s['pending']}**",
        "",
        f"**通过率**: {s['pass_rate']:.1f}%",
    ]


def build_card(
    event: str,
    manifest_path: Path,
    batch_id: str = None,
    iteration: int = None,
    reason: str = None,
) -> dict:
    s = compute_stats(manifest_path)
    title_prefix, template, emoji = EVENT_CONFIG.get(event, EVENT_CONFIG["progress"])

    lines = []

    # 事件特定的头部信息
    if event == "progress":
        lines.append(f"**Batch**: {batch_id or 'N/A'}  |  **Iteration**: {iteration or 'N/A'}")
    elif event == "complete":
        lines.append(f"{emoji} **所有测试已执行完成**  |  Iteration: {iteration or 'N/A'}")
    elif event == "alert":
        lines.append(f"{emoji} **触发告警**: {reason or '错误率/失败率超阈值'}")
        if batch_id:
            lines.append(f"**当前 Batch**: {batch_id}  |  **Iteration**: {iteration or 'N/A'}")
    elif event == "paused":
        lines.append(f"{emoji} **暂停原因**: {reason or '未知'}")
        if batch_id:
            lines.append(f"**当前 Batch**: {batch_id}  |  **Iteration**: {iteration or 'N/A'}")
    elif event == "resumed":
        lines.append(f"{emoji} **Workflow 已恢复执行**  |  Iteration: {iteration or 'N/A'}")

    # 通用统计块
    lines.extend(build_stats_block(s))

    # 标题
    if event == "progress":
        title = f"{title_prefix} {s['progress']:.1f}%"
    else:
        title = title_prefix

    return {
        "header": {"title": title, "template": template},
        "content": "\n".join(lines),
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Send Feishu notification card")
    parser.add_argument("--manifest-path", required=True, help="manifest.json path")
    parser.add_argument("--feishu-config", required=True, help="feishu_config.json path")
    parser.add_argument("--event", default="progress",
                        choices=list(EVENT_CONFIG.keys()),
                        help="Event type (default: progress)")
    parser.add_argument("--batch-id", default=None, help="Current batch ID")
    parser.add_argument("--iteration", type=int, default=None, help="Current iteration")
    parser.add_argument("--reason", default=None, help="Reason for alert/paused event")
    args = parser.parse_args()

    manifest_path = Path(args.manifest_path)
    feishu_config = Path(args.feishu_config)

    if not manifest_path.exists():
        print(f"[ERROR] manifest not found: {manifest_path}")
        sys.exit(1)

    if not feishu_config.exists():
        print(f"[ERROR] feishu config not found: {feishu_config}")
        sys.exit(1)

    card = build_card(
        event=args.event,
        manifest_path=manifest_path,
        batch_id=args.batch_id,
        iteration=args.iteration,
        reason=args.reason,
    )

    try:
        api = FeishuAPI(str(feishu_config))
        ok = api.send_card(card)
        if ok:
            print(f"[OK] [{args.event}] Card sent: {card['header']['title']}")
        else:
            print("[WARN] Failed to send card")
            sys.exit(1)
    except Exception as e:
        print(f"[WARN] Feishu send failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
