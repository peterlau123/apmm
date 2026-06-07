#!/usr/bin/env python3
"""Hermes Feishu HTTP Server"""

import json
import subprocess
import requests
import os
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv

load_dotenv('C:/Users/admin/AppData/Local/hermes/.env')

FEISHU_APP_ID = os.getenv('FEISHU_APP_ID')
FEISHU_APP_SECRET = os.getenv('FEISHU_APP_SECRET')
FEISHU_CHAT_ID = 'oc_2e75db818ac1792238037a704b4d32d3'

def get_feishu_token():
    url = 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal'
    resp = requests.post(url, json={'app_id': FEISHU_APP_ID, 'app_secret': FEISHU_APP_SECRET}, timeout=10)
    if resp.json().get('code') == 0:
        return resp.json()['tenant_access_token']
    return None

def send_feishu_message(text):
    token = get_feishu_token()
    if not token:
        return {"error": "no token"}
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    url = 'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id'
    data = {'receive_id': FEISHU_CHAT_ID, 'msg_type': 'text', 'content': json.dumps({'text': text})}
    resp = requests.post(url, headers=headers, json=data, timeout=10)
    if resp.json().get('code') == 0:
        return {"success": True}
    return {"error": resp.json().get('msg')}

def check_agent_status():
    result = subprocess.run(["python", "D:/workspace/apmm/scripts/monitor_agent_daemon.py"], capture_output=True, text=True, timeout=30)
    if result.returncode == 0:
        return {"status": "ok"}
    return {"status": "error", "message": result.stdout}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/check':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(check_agent_status()).encode())
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
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
                msg = data.get('message', '')
                if msg:
                    result = send_feishu_message(msg)
                else:
                    result = {"error": "no message"}
            except:
                result = {"error": "invalid json"}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):
        print('[Server]', args[0] if args else '')

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--http', action='store_true')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    
    if args.http:
        print(f"Starting Hermes Feishu Server on port {args.port}")
        print("Endpoints: POST /send, GET /check, GET /health")
        HTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
    else:
        print("Usage: python hermes_feishu_server.py --http --port 8080")
