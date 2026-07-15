"""
飞书API封装
提供消息获取、卡片发送等功能
"""

import json
import requests
import time
from pathlib import Path
from datetime import datetime

BASE_URL = "https://open.feishu.cn/open-apis"

class FeishuAPI:
    def __init__(self, config_path):
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        self.app_id = config["app_id"]
        self.app_secret = config["app_secret"]
        self.chat_id = config["chat_id"]
        self._token = None
        self._token_expire_time = 0
    
    def get_token(self):
        """获取tenant_access_token，带缓存"""
        if self._token and time.time() < self._token_expire_time:
            return self._token
        
        response = requests.post(
            f"{BASE_URL}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=10
        )
        data = response.json()
        
        if data.get("code") != 0:
            raise Exception(f"Failed to get token: {data}")
        
        self._token = data["tenant_access_token"]
        self._token_expire_time = time.time() + data["expire"] - 60
        
        return self._token
    
    def get_group_messages(self, limit=20):
        """获取群消息列表"""
        token = self.get_token()
        
        response = requests.get(
            f"{BASE_URL}/im/v1/messages",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "container_id_type": "chat",
                "container_id": self.chat_id,
                "page_size": limit
            },
            timeout=10
        )
        data = response.json()
        
        if data.get("code") != 0:
            print(f"[WARN] Failed to get messages: {data}")
            return []
        
        items = data.get("data", {}).get("items", [])
        
        # 解析消息内容
        messages = []
        for item in items:
            msg_type = item.get("msg_type")
            if msg_type == "text":
                content = json.loads(item.get("content", "{}"))
                text = content.get("text", "")
            else:
                text = ""
            
            messages.append({
                "message_id": item["message_id"],
                "create_time": item["create_time"],
                "sender_id": item.get("sender", {}).get("id"),
                "content": text,
                "msg_type": msg_type
            })
        
        return messages
    
    def send_message(self, text):
        """发送文本消息"""
        token = self.get_token()
        
        response = requests.post(
            f"{BASE_URL}/im/v1/messages?receive_id_type=chat_id",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": self.chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": text})
            },
            timeout=10
        )
        
        return response.json().get("code") == 0
    
    def send_card(self, card_data):
        """发送交互卡片"""
        token = self.get_token()

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": card_data.get("header", {}).get("title", "")},
                "template": card_data.get("header", {}).get("template", "blue")
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": card_data.get("content", "")}},
                {"tag": "hr"},
                {"tag": "note", "elements": [
                    {"tag": "plain_text", "content": "Supervisor Agent"},
                    {"tag": "plain_text", "content": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                ]}
            ]
        }

        response = requests.post(
            f"{BASE_URL}/im/v1/messages?receive_id_type=chat_id",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": self.chat_id,
                "msg_type": "interactive",
                "content": json.dumps(card)
            },
            timeout=10
        )

        result = response.json()
        if result.get("code") != 0:
            print(f"[WARN] Failed to send card: {result}")
            return False
        return True
    
    def send_alert_card(self, alert_type, agent_id, details):
        """发送告警卡片"""
        templates = {
            "disconnect": {
                "title": "Agent失联告警",
                "template": "red",
                "prefix": "失联Agent"
            },
            "gpu_intrusion": {
                "title": "GPU被抢占告警",
                "template": "red",
                "prefix": "GPU被占用"
            },
            "otp_required": {
                "title": "SSH需要OTP验证",
                "template": "red",
                "prefix": "请在飞书回复: OTP 123456"
            },
            "otp_expired": {
                "title": "OTP已过期",
                "template": "yellow",
                "prefix": "请提供新验证码"
            },
            "dependency_failed": {
                "title": "依赖下载失败",
                "template": "red",
                "prefix": "需人工介入"
            },
            "warning": {
                "title": "警告",
                "template": "yellow",
                "prefix": ""
            },
            "success": {
                "title": "完成",
                "template": "green",
                "prefix": ""
            }
        }

        tmpl = templates.get(alert_type, templates["warning"])

        return self.send_card({
            "header": {"title": tmpl["title"], "template": tmpl["template"]},
            "content": f"{tmpl['prefix']}: {agent_id}\n{details}"
        })

    def send_confirmation_card(self, intent, yaml_path, test_list_path=None,
                                manifest_source=None, mode=None, eta=None,
                                timeout_seconds=10):
        """发送启动意图确认卡片 (Spec §4.5 — Agent intent confirmation gate).

        Display-only card; user replies with text "确认" / "取消" (matches the
        existing 参数确认卡 reply pattern in hermes-workflow SKILL §3 step 4).
        Real interactive buttons would require a card-action webhook + an
        action_id→state map — deferred per surgical-changes guideline.

        Parameters
        ----------
        intent: str
            One of "start_l1" / "start_l2" / "start_l3" / "start_l4" /
            "start_production". Used to pick the tier label.
        yaml_path: str
            The frozen workflow yaml path that will be used after confirmation.
        test_list_path: str or None
            The test_list_path that will be loaded (optional,
            mutually exclusive with manifest_source).
        manifest_source: str or None
            The manifest.json source path (optional,
            mutually exclusive with test_list_path).
        mode: str
            "linear" or "kanban" — derived from ``kanban.enabled`` of the yaml.
        eta: str
            Free-text estimated duration shown to the user (e.g. "~60 分钟",
            "hours–days"). Lets the caller bake in the expected magnitude
            difference between tiers and production.
        timeout_seconds: int
            Auto-cancel window. Displayed for transparency; the actual timer
            is enforced by the caller, not this method.
        """
        tier_labels = {
            "start_l1": "L1 烟囱测试",
            "start_l2": "L2 mini 测试",
            "start_l3": "L3 fast subset 测试",
            "start_l4": "L4 Kanban distributed 测试",
            "start_production": "生产 全量 UT 测试",
        }
        tier_label = tier_labels.get(intent, intent)

        # Production runs get an extra warning since wrong-trigger blast radius
        # is hours of GPU time vs tier runs' minutes.
        emphasis = "⚠️ **这是生产全量运行** — " if intent == "start_production" else ""

        content_lines = [
            f"🤖 {emphasis}我理解你想触发 **{tier_label}**。要开始吗？",
            "",
            f"配置: `{yaml_path}`",
            (f"test_list_path: `{test_list_path}`" if not manifest_source
             else f"manifest_source: `{manifest_source}`"),
            f"模式: **{mode}**",
            f"预计耗时: **{eta}**",
            "",
            f"请回复 **确认** 启动，或 **取消** 放弃。",
            f"({timeout_seconds}s 内无回复将自动取消)",
        ]

        template = "orange" if intent == "start_production" else "blue"

        return self.send_card({
            "header": {"title": f"启动意图确认 — {tier_label}", "template": template},
            "content": "\n".join(content_lines),
        })

    def send_tier_completion_card(self, verdict, tier, run_dir):
        """发送 tier (L1-L4) 完成卡片 (Spec §5 P5b).

        Renders the verdict from ``check_expected.py`` as a green PASS / red
        FAIL card with the assertion summary. Distinct from the regular
        ``send_feishu_card("complete", ...)`` which only shows progress stats
        and is kept for production runs.

        Parameters
        ----------
        verdict: dict
            The JSON dict written by ``check_expected.py``:
              {"overall": "PASS"|"FAIL",
               "assertions": [{"id", "result", "severity", "detail"?}, ...],
               "summary": "..."}
        tier: str
            "L1" / "L2" / "L3" / "L4".
        run_dir: str
            Run directory path for traceability in the card body.
        """
        overall = verdict.get("overall", "FAIL")
        is_pass = overall == "PASS"
        template = "green" if is_pass else "red"
        emoji = "✅" if is_pass else "❌"
        title = f"{tier} {overall}"

        assertions = verdict.get("assertions") or []
        failed_hard = [a for a in assertions
                       if a.get("result") == "FAIL" and a.get("severity") == "hard"]
        passed = sum(1 for a in assertions if a.get("result") == "PASS")
        skipped = sum(1 for a in assertions if a.get("result") == "SKIP")
        failed = sum(1 for a in assertions if a.get("result") == "FAIL")
        summary = verdict.get("summary") or (
            f"{passed} PASS / {failed} FAIL / {skipped} SKIP")

        lines = [
            f"{emoji} **{tier} 测试 {overall}**",
            "",
            f"Run: `{run_dir}`",
            f"断言摘要: {summary}",
        ]
        if failed_hard:
            lines.append("")
            lines.append("**失败 hard 断言**:")
            # Cap at 8 lines to keep the card readable; check_expected.py JSON
            # has the full list for forensic follow-up.
            for a in failed_hard[:8]:
                detail = a.get("detail") or ""
                lines.append(f"- `{a.get('id', '?')}` — {detail}".rstrip(" —"))
            if len(failed_hard) > 8:
                lines.append(f"… and {len(failed_hard) - 8} more (see check_result.json)")

        return self.send_card({
            "header": {"title": title, "template": template},
            "content": "\n".join(lines),
        })


def test_connection():
    """测试飞书连接"""
    config_path = Path(__file__).parent.parent / ".agents" / "feishu_config.json"
    
    print("Testing Feishu API...")
    api = FeishuAPI(str(config_path))
    
    print(f"Token obtained: {api.get_token()[:20]}...")
    
    # 发送测试卡片
    result = api.send_card({
        "header": {"title": "Supervisor启动测试", "template": "blue"},
        "content": "Supervisor Agent Cron Job已启动\n这是测试消息"
    })
    
    print(f"Card sent: {result}")
    return result


if __name__ == "__main__":
    test_connection()