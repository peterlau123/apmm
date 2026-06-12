#!/usr/bin/env python3
"""
Agent Daemon - 进程守护管理器（apmm版本）
功能：
1. 自动启动Agent进程
2. 健康监控（心跳检测）
3. 自动重启（进程崩溃/无响应）
4. 日志记录
"""

import os
import sys
import json
import time
import signal
import subprocess
import psutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional, List
import logging
import threading

# apmm项目路径
PROJECT_DIR = Path("D:/workspace/apmm")
AGENTS_DIR = PROJECT_DIR / ".agents"
CONFIG_FILE = AGENTS_DIR / "config.json"
DAEMON_DIR = AGENTS_DIR / "daemon"

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(str(DAEMON_DIR / 'daemon.log')),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class AgentDaemon:
    """Agent进程守护管理器"""
    
    def __init__(self, config_path: str = str(CONFIG_FILE)):
        self.config_path = Path(config_path)
        self.agents_dir = AGENTS_DIR
        self.processes: Dict[str, subprocess.Popen] = {}
        self.stop_event = threading.Event()
        self.config = self._load_config()
        
        # 监控参数
        self.health_check_interval = 10  # 每10秒检查健康
        self.heartbeat_timeout = 60  # 心跳超时60秒
        self.restart_delay = 5  # 重启延迟5秒
        self.max_restart_attempts = 3  # 最大重启次数
        self.restart_attempts: Dict[str, int] = {}
        
    def _load_config(self) -> dict:
        """加载Agent配置"""
        if not self.config_path.exists():
            logger.error(f"Config file not found: {self.config_path}")
            return {}
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _get_agent_command(self, agent_id: str) -> Optional[List[str]]:
        """获取Agent启动命令"""
        agents = self.config.get('agents', {})
        agent_config = agents.get(agent_id, {})
        
        # 启动命令优先级：start_command > skill_file推导
        if 'start_command' in agent_config:
            return agent_config['start_command']
        
        # 从skill_file推导（apmm的skill路径）
        skill_file = agent_config.get('skill_file', '')
        
        # apmm的supervisor和runner脚本位置
        if agent_id == 'supervisor':
            return ['python', str(PROJECT_DIR / 'skills/ut/workflow/scripts/supervisor_loop.py')]
        elif agent_id == 'unit-test-executor':
            return ['python', str(PROJECT_DIR / 'skills/ut/unit-test-executor/scripts/start_loop.py')]
        
        return None
    
    def start_agent(self, agent_id: str) -> bool:
        """启动单个Agent"""
        if agent_id in self.processes and self.processes[agent_id].poll() is None:
            logger.warning(f"Agent {agent_id} already running")
            return True
        
        command = self._get_agent_command(agent_id)
        if not command:
            logger.error(f"No start command for agent: {agent_id}")
            return False
        
        try:
            # 启动进程
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0
            )
            
            self.processes[agent_id] = process
            self.restart_attempts[agent_id] = 0
            logger.info(f"Started agent {agent_id} (PID: {process.pid})")
            
            # 更新status.json
            self._update_agent_status(agent_id, 'running')
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start agent {agent_id}: {e}")
            return False
    
    def stop_agent(self, agent_id: str, timeout: int = 10) -> bool:
        """停止Agent"""
        if agent_id not in self.processes:
            return True
        
        process = self.processes[agent_id]
        
        try:
            # 发送终止信号
            process.terminate()
            
            # 等待进程退出
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # 强制杀死
                process.kill()
                process.wait(timeout=5)
            
            del self.processes[agent_id]
            logger.info(f"Stopped agent {agent_id}")
            
            # 更新status.json
            self._update_agent_status(agent_id, 'stopped')
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to stop agent {agent_id}: {e}")
            return False
    
    def check_agent_health(self, agent_id: str) -> bool:
        """检查Agent健康状态"""
        # 1. 检查进程是否存活
        if agent_id not in self.processes:
            return False
        
        process = self.processes[agent_id]
        if process.poll() is not None:
            logger.warning(f"Agent {agent_id} process died (exit code: {process.returncode})")
            return False
        
        # 2. 检查心跳文件
        agent_dir = self.agents_dir / agent_id
        heartbeat_file = agent_dir / 'heartbeat.json'
        
        if heartbeat_file.exists():
            try:
                with open(heartbeat_file, 'r', encoding='utf-8') as f:
                    heartbeat = json.load(f)
                
                last_beat = datetime.fromisoformat(heartbeat.get('timestamp', '').replace('Z', '+00:00'))
                if datetime.now(timezone.utc) - last_beat > timedelta(seconds=self.heartbeat_timeout):
                    logger.warning(f"Agent {agent_id} heartbeat timeout")
                    return False
                    
            except Exception as e:
                logger.warning(f"Failed to read heartbeat for {agent_id}: {e}")
        
        return True
    
    def _update_agent_status(self, agent_id: str, status: str):
        """更新Agent状态文件"""
        agent_dir = self.agents_dir / agent_id
        status_file = agent_dir / 'status.json'
        
        if not status_file.exists():
            return
        
        try:
            with open(status_file, 'r+', encoding='utf-8') as f:
                data = json.load(f)
                data['status'] = status
                data['last_update'] = datetime.now(timezone.utc).isoformat()
                f.seek(0)
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.truncate()
        except Exception as e:
            logger.error(f"Failed to update status for {agent_id}: {e}")
    
    def restart_agent(self, agent_id: str) -> bool:
        """重启Agent"""
        logger.info(f"Restarting agent {agent_id}...")
        
        # 检查重启次数
        attempts = self.restart_attempts.get(agent_id, 0)
        if attempts >= self.max_restart_attempts:
            logger.error(f"Max restart attempts reached for {agent_id}")
            # 发送飞书告警
            self._send_alert(agent_id, "max_restart_reached")
            return False
        
        # 停止
        self.stop_agent(agent_id)
        
        # 延迟
        time.sleep(self.restart_delay)
        
        # 启动
        success = self.start_agent(agent_id)
        
        if success:
            self.restart_attempts[agent_id] = attempts + 1
            logger.info(f"Restarted agent {agent_id} (attempt {attempts + 1})")
        else:
            logger.error(f"Failed to restart agent {agent_id}")
        
        return success
    
    def _send_alert(self, agent_id: str, alert_type: str):
        """发送飞书告警"""
        try:
            from skills.ut.supervisor.scripts.feishu_api import FeishuAPI
            feishu = FeishuAPI()
            feishu.send_message(
                chat_id="oc_2e75db818ac1792238037a704b4d32d3",
                msg_type="text",
                content={
                    "text": f"⚠️ Agent {agent_id} 告警\n类型: {alert_type}\n时间: {datetime.now().isoformat()}"
                }
            )
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
    
    def health_check_loop(self):
        """健康检查循环"""
        logger.info("Starting health check loop...")
        
        while not self.stop_event.is_set():
            try:
                # 检查所有Agent（从config.json的agents列表）
                for agent_id in self.config.get('agents', {}).keys():
                    if agent_id == 'supervisor':
                        continue  # Supervisor由自己监控
                    
                    # 跳过disabled的Agent
                    agent_config = self.config['agents'][agent_id]
                    if agent_config.get('enabled') is False:
                        continue
                    
                    if not self.check_agent_health(agent_id):
                        logger.warning(f"Agent {agent_id} unhealthy, restarting...")
                        self.restart_agent(agent_id)
                
                # 等待下一次检查
                self.stop_event.wait(self.health_check_interval)
                
            except Exception as e:
                logger.error(f"Health check error: {e}")
                time.sleep(5)
    
    def start_all(self):
        """启动所有Agent"""
        logger.info("Starting all agents...")
        
        for agent_id in self.config.get('agents', {}).keys():
            # 跳过disabled的Agent
            agent_config = self.config['agents'][agent_id]
            if agent_config.get('enabled') is False:
                logger.info(f"Skipping disabled agent: {agent_id}")
                continue
            
            self.start_agent(agent_id)
            time.sleep(2)  # 错开启动时间
        
        # 启动健康检查线程
        health_thread = threading.Thread(target=self.health_check_loop, daemon=True)
        health_thread.start()
        
        logger.info("All agents started, health check running")
    
    def stop_all(self):
        """停止所有Agent"""
        logger.info("Stopping all agents...")
        
        self.stop_event.set()
        
        for agent_id in list(self.processes.keys()):
            self.stop_agent(agent_id)
        
        logger.info("All agents stopped")
    
    def run(self):
        """运行守护进程"""
        logger.info("=" * 50)
        logger.info("Agent Daemon Started (apmm)")
        logger.info("=" * 50)
        
        # 注册信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # 启动所有Agent
        self.start_all()
        
        # 主循环（等待退出信号）
        try:
            while not self.stop_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        
        # 停止所有Agent
        self.stop_all()
        
        logger.info("Agent Daemon exited")
    
    def _signal_handler(self, signum, frame):
        """信号处理"""
        logger.info(f"Received signal {signum}")
        self.stop_event.set()


def main():
    """主入口"""
    daemon = AgentDaemon()
    daemon.run()


if __name__ == '__main__':
    main()