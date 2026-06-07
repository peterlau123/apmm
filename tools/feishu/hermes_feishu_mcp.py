#!/usr/bin/env python3
"""Hermes Feishu MCP Server for Claude Code"""

import json
import subprocess
import requests
import os
import asyncio
from dotenv import load_dotenv

load_dotenv('C:/Users/admin/AppData/Local/hermes/.env')

FEISHU_APP_ID = os.getenv('FEISHU_APP_ID')
FEISHU_APP_SECRET=os.get...T_ID = 'oc_2e75db818ac1792238037a704b4d32d3'

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
        return {"status": "ok", "message": "All daemons running"}
    return {"status": "error", "message": result.stdout}

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("hermes-feishu")

@server.list_tools()
async def list_tools():
    return [
        Tool(name="send_feishu_message", description="Send message to Feishu group", inputSchema={"type": "object", "properties": {"message": {"type": "string"}}}),
        Tool(name="check_agent_status", description="Check SSH daemon status", inputSchema={"type": "object"})
    ]

@server.call_tool()
async def call_tool(name, arguments):
    if name == "send_feishu_message":
        msg = arguments.get("message", "")
        if not msg:
            return [TextContent(type="text", text="Error: no message")]
        result = send_feishu_message(msg)
        if result.get("success"):
            return [TextContent(type="text", text="Message sent to Feishu")]
        return [TextContent(type="text", text="Failed: " + result.get("error", "unknown"))]
    elif name == "check_agent_status":
        result = check_agent_status()
        return [TextContent(type="text", text=json.dumps(result))]
    return [TextContent(type="text", text="Unknown tool")]

async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
