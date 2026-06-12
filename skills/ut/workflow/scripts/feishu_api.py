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
                "receive_id_type": "chat_id",
                "receive_id": self.chat_id,
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