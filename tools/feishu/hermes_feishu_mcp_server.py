#!/usr/bin/env python3
"""
Hermes Feishu Server - HTTP API 模式

启动方式:
  python hermes_feishu_mcp_server.py --http --port 8080

API 端点:
  POST /send - 发送飞书消息 {"message": "xxx"}
  GET /check - 检查守护进程状态
"""

import json
import subprocess
import requests
import os
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv

# 从 Hermes .env 文件加载配置
load_dotenv('C:/Users/admin/AppData/Local/hermes/.env')

FEISHU_APP_ID = os.getenv('FEISHU_APP_ID')
FEISHU_APP_SECRET = os.getenv('FEISHU_APP_SECRET')
FEISHU_CHAT_ID = os.getenv('FEISHU_CHAT_ID', 'oc_2e75db818ac1792238037a704b4d32d3')


def get_feishu_token():
    url = 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal'
    resp = requests.post(url, json={'app_id': FEISHU_APP_ID, 'app_secret': FEISHU_APP_SECRET}, timeout=10)
    if resp.json().get('code') == 0:
        return resp.json()['tenant_access_token']
    return None


def send_feishu_message(text):
    token = get_feishu_token()
    if not token:
        return {"error": "无法获取 token"}
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    url = 'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id'
    data = {'receive_id': FEISHU_CHAT_ID, 'msg_type': 'text', 'content': json.dumps({'text': text})}
    resp = requests.post(url, headers=headers, json=data, timeout=10)
    result = resp.json()
    if result.get('code') == 0:
        return {"success": True}
    return {"error": result.get('msg')}


def check_agent_status():
    result = subprocess.run(["python", "D:/workspace/apmm/scripts/monitor_agent_daemon.py"], capture_output=True, text=True, timeout=30)
    if result.returncode == 0:
        return {"status": "ok", "message": "所有守护进程正常运行"}
    return {"status": "error", "message": result.stdout}


class FeishuHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/check':
            result = check_agent_status()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        elif self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "healthy"}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/send':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body)
                message = data.get('message', '')
                if not message:
                    result = {"error": "未提供消息内容"}
                else:
                    result = send_feishu_message(message)
            except json.JSONDecodeError:
                result = {"error": "无效的 JSON 格式"}
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        print(f"[Feishu Server] {args[0]}")


def run_http_server(port=8080):
    server = HTTPServer(('127.0.0.1', port), FeishuHandler)
    print(f"Hermes Feishu Server 启动在 http://127.0.0.1:{port}")
    print(f"API 端点:")
    print(f"  POST /send - 发送飞书消息")
    print(f"  GET /check - 检查守护进程状态")
    print(f"  GET /health - 健康检查")
    server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hermes Feishu Server")
    parser.add_argument('--http', action='store_true', help='启动 HTTP API 服务器')
    parser.add_argument('--port', type=int, default=8080, help='HTTP 服务器端口')
    parser.add_argument('command', nargs='?', help='命令: send 或 check')
    parser.add_argument('message', nargs='?', help='要发送的消息')
    
    args = parser.parse_args()
    
    if args.http:
        run_http_server(args.port)
    elif args.command == 'send':
        msg = args.message if args.message else "测试"
        print(json.dumps(send_feishu_message(msg)))
    elif args.command == 'check':
        print(json.dumps(check_agent_status()))
    else:
        print("用法:")
        print("  HTTP 模式: python hermes_feishu_mcp_server.py --http --port 8080")
        print("  命令模式: python hermes_feishu_mcp_server.py send <消息>")
        print("  命令模式: python hermes_feishu_mcp_server.py check")