"""
Supervisor飞书监听脚本
频率: 每60秒执行
功能: 获取飞书消息，解析指令，执行，发送响应
"""

import json
import re
from pathlib import Path
from datetime import datetime
import sys

# 添加scripts目录到路径
sys.path.insert(0, str(Path(__file__).parent))

try:
    from feishu_api import FeishuAPI
except ImportError:
    print("[WARN] feishu_api not available, using mock mode")
    FeishuAPI = None
FeishuAPI = None
# 配置 - 从脚本目录推断路径
_AGENTS_DIR = Path(__file__).parent.parent.parent.parent.parent / ".agents"
AGENTS_DIR = _AGENTS_DIR
FEISHU_CONFIG = AGENTS_DIR / "feishu_config.json"
GLOBAL_STATE_FILE = AGENTS_DIR / "global_state.json"
PROCESSED_IDS_FILE = AGENTS_DIR / "archive" / "processed_feishu_ids.json"

# 指令解析规则（正则匹配）
COMMAND_PATTERNS = {
    "otp_code": [
        r"^otp\s+(\d{6})$",
        r"^验证码\s+(\d{6})$",
        r"^ssh\s*otp\s+(\d{6})$",
        r"^otp码\s*(\d{6})$",
        r"^(\d{6})$",  # 直接发送6位数字
    ],
    "query_status": [
        r"^状态$",
        r"^全局状态$",
        r"^当前状态$",
        r"^系统状态$",
    ],
    "query_progress": [
        r"^进度$",
        r"^测试进度$",
        r"^runner状态$",
        r"^runner$",
        r"^测试状态$",
    ],
    "query_gpu": [
        r"^gpu状态$",
        r"^gpu$",
        r"^环境状态$",
        r"^environment$",
    ],
    "query_bastion": [
        r"^bastion状态$",
        r"^bastion$",
        r"^连接状态$",
        r"^ssh状态$",
    ],
    "pause_runner": [
        r"^暂停\s*runner$",
        r"^暂停测试$",
        r"^stop\s*runner$",
    ],
    "resume_runner": [
        r"^继续\s*runner$",
        r"^继续测试$",
        r"^恢复\s*runner$",
        r"^resume\s*runner$",
    ],
    "stop_runner": [
        r"^停止\s*runner$",
        r"^终止测试$",
    ],
    "download_model": [
        r"^下载模型\s+(.+)$",
        r"^下载\s+(.+)$",
    ],
}

def read_json(file_path):
    try:
        return json.loads(Path(file_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}

def write_json(file_path, data):
    Path(file_path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

def write_to_inbox(agent_id, message):
    """写入指定Agent的inbox"""
    inbox_file = AGENTS_DIR / agent_id / "inbox.jsonl"
    inbox_file.parent.mkdir(parents=True, exist_ok=True)
    with open(inbox_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(message, ensure_ascii=False) + "\n")

def load_processed_ids():
    """加载已处理的飞书消息ID"""
    data = read_json(PROCESSED_IDS_FILE)
    return data.get("ids", [])

def save_processed_ids(ids):
    """保存已处理的飞书消息ID"""
    write_json(PROCESSED_IDS_FILE, {"ids": ids[-500:]})  # 只保留最近500条

class FeishuCommandParser:
    def __init__(self):
        if FeishuAPI:
            self.feishu = FeishuAPI(str(FEISHU_CONFIG))
        else:
            self.feishu = None
        self.processed_ids = load_processed_ids()
    
    def parse_command(self, text):
        """解析飞书消息指令"""
        text = text.strip().lower()
        
        # 遍历所有模式匹配
        for cmd_type, patterns in COMMAND_PATTERNS.items():
            for pattern in patterns:
                match = re.match(pattern, text, re.IGNORECASE)
                if match:
                    result = {"type": cmd_type}
                    # 提取参数
                    if match.groups():
                        result["param"] = match.group(1)
                    return result
        
        # 无法匹配，标记为unknown
        return {"type": "unknown", "raw": text}
    
    def execute_command(self, cmd):
        """执行解析后的指令"""
        cmd_type = cmd["type"]
        
        handlers = {
            "otp_code": self.handle_otp,
            "query_status": self.handle_query_status,
            "query_progress": self.handle_query_progress,
            "query_gpu": self.handle_query_gpu,
            "query_bastion": self.handle_query_bastion,
            "pause_runner": self.handle_pause_runner,
            "resume_runner": self.handle_resume_runner,
            "stop_runner": self.handle_stop_runner,
            "download_model": self.handle_download_model,
            "unknown": self.handle_unknown,
        }
        
        handler = handlers.get(cmd_type)
        if handler:
            return handler(cmd)
        return {"success": False, "message": "Unknown command"}
    
    def send_card(self, title, content, template="blue"):
        """发送飞书卡片"""
        if self.feishu:
            return self.feishu.send_card({
                "header": {"title": title, "template": template},
                "content": content
            })
        else:
            print(f"[FEISHU MOCK] Card: {title} - {content}")
            return True
    
    def handle_otp(self, cmd):
        """处理OTP验证码"""
        otp_code = cmd.get("param")
        
        # 写入bastion inbox
        write_to_inbox("bastion", {
            "type": "otp_code",
            "code": otp_code,
            "timestamp": datetime.now().isoformat(),
            "from": "user_via_feishu"
        })
        
        # 发飞书确认
        self.send_card(
            "OTP已转发",
            f"验证码 **{otp_code}** 已转发给Bastion Agent\n正在尝试SSH重启...",
            "blue"
        )
        
        print(f"[OTP] Forwarded: {otp_code}")
        return {"success": True, "message": "OTP forwarded"}
    
    def handle_query_status(self, cmd):
        """处理状态查询"""
        global_state = read_json(GLOBAL_STATE_FILE)
        agents = global_state.get("agents", {})
        
        lines = []
        for agent_id, info in agents.items():
            status = info.get("status", "?")
            health = info.get("connection_health", "?")
            task = info.get("current_task", "")
            lines.append(f"**{agent_id}**: {status} ({health})")
            if task:
                lines.append(f"  任务: {task}")
        
        content = "\n".join(lines) if lines else "暂无Agent状态"
        self.send_card("全局状态", content, "blue")
        
        return {"success": True}
    
    def handle_query_progress(self, cmd):
        """处理进度查询"""
        global_state = read_json(GLOBAL_STATE_FILE)
        progress = global_state.get("test_progress", {})
        
        completed = progress.get("completed", 0)
        passed = progress.get("passed", 0)
        failed = progress.get("failed", 0)
        error = progress.get("error", 0)
        
        content = f"""**测试进度**
完成: {completed}
通过: {passed}
失败: {failed}
错误: {error}"""
        
        self.send_card("测试进度", content, "blue")
        return {"success": True}
    
    def handle_query_gpu(self, cmd):
        """处理GPU状态查询"""
        env_status = read_json(AGENTS_DIR / "environment" / "status.json")
        gpu = env_status.get("gpu_status", {})
        
        idle = gpu.get("idle", [])
        occupied = gpu.get("occupied", [])
        
        content = f"""**GPU状态**
空闲: {', '.join(idle) if idle else '无'}
占用: {', '.join(occupied) if occupied else '无'}"""
        
        self.send_card("GPU状态", content, "blue")
        return {"success": True}
    
    def handle_query_bastion(self, cmd):
        """处理Bastion状态查询"""
        bastion_status = read_json(AGENTS_DIR / "bastion" / "status.json")
        bs = bastion_status.get("bastion_status", {})
        
        t_h20 = bs.get("t_h20", "unknown")
        t_ascend = bs.get("t_ascend", "unknown")
        waiting_otp = bastion_status.get("waiting_for_otp", False)
        
        content = f"""**Bastion连接状态**
t_h20: {t_h20}
t_ascend: {t_ascend}
等待OTP: {'是' if waiting_otp else '否'}"""
        
        template = "blue" if t_h20 == "connected" else "yellow"
        self.send_card("Bastion状态", content, template)
        return {"success": True}
    
    def handle_pause_runner(self, cmd):
        """处理暂停Runner指令"""
        write_to_inbox("runner", {
            "type": "command",
            "action": "pause",
            "timestamp": datetime.now().isoformat(),
            "from": "user_via_feishu"
        })
        
        self.send_card("指令已转发", "暂停指令已转发给Runner Agent", "blue")
        print(f"[CMD] Pause Runner")
        return {"success": True}
    
    def handle_resume_runner(self, cmd):
        """处理继续Runner指令"""
        write_to_inbox("runner", {
            "type": "command",
            "action": "resume",
            "timestamp": datetime.now().isoformat(),
            "from": "user_via_feishu"
        })
        
        self.send_card("指令已转发", "继续指令已转发给Runner Agent", "blue")
        print(f"[CMD] Resume Runner")
        return {"success": True}
    
    def handle_stop_runner(self, cmd):
        """处理停止Runner指令"""
        write_to_inbox("runner", {
            "type": "command",
            "action": "stop",
            "timestamp": datetime.now().isoformat(),
            "from": "user_via_feishu"
        })
        
        self.send_card("指令已转发", "停止指令已转发给Runner Agent", "blue")
        print(f"[CMD] Stop Runner")
        return {"success": True}
    
    def handle_download_model(self, cmd):
        """处理下载模型指令"""
        model_name = cmd.get("param")
        
        write_to_inbox("environment", {
            "type": "request",
            "action": "download_model",
            "model": model_name,
            "timestamp": datetime.now().isoformat(),
            "from": "user_via_feishu"
        })
        
        self.send_card("下载请求已转发", f"模型 **{model_name}** 下载请求已转发给Environment Agent", "blue")
        print(f"[CMD] Download model: {model_name}")
        return {"success": True}
    
    def handle_unknown(self, cmd):
        """处理无法识别的指令"""
        raw = cmd.get("raw", "")
        self.send_card(
            "指令无法识别",
            f"无法理解: `{raw}`\n\n**支持的指令**:\n- 状态、进度、GPU状态\n- OTP 123456\n- 暂停Runner、继续Runner\n- 下载模型 xxx",
            "yellow"
        )
        return {"success": False, "message": "Unknown command"}

def main():
    parser = FeishuCommandParser()
    
    # 1. 获取飞书群最新消息
    if parser.feishu:
        messages = parser.feishu.get_group_messages(limit=10)
    else:
        # Mock模式：检查是否有测试消息文件
        test_file = AGENTS_DIR / "test_feishu_messages.json"
        if test_file.exists():
            messages = read_json(test_file).get("messages", [])
        else:
            messages = []
            print("[MOCK] No test messages")
    
    if not messages:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] No new Feishu messages")
        save_processed_ids(parser.processed_ids)
        return
    
    # 2. 过滤已处理消息
    new_messages = [
        m for m in messages 
        if m.get("message_id") not in parser.processed_ids
    ]
    
    if not new_messages:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] All messages already processed")
        save_processed_ids(parser.processed_ids)
        return
    
    # 3. 处理每条消息
    for msg in new_messages:
        text = msg.get("content", "").strip()
        if not text:
            continue
        
        print(f"[FEISHU] Received: {text[:50]}...")
        cmd = parser.parse_command(text)
        result = parser.execute_command(cmd)
        
        # 记录已处理
        parser.processed_ids.append(msg.get("message_id", "unknown"))
    
    # 4. 保存已处理ID
    save_processed_ids(parser.processed_ids)
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Processed {len(new_messages)} Feishu messages")

if __name__ == "__main__":
    main()