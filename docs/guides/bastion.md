# Bastion 堡垒机连接方案

## 架构

```
本机 (Windows + VPN)
    │
    │  Paramiko SSH (keyboard-interactive 密码 + 动态 OTP)
    ▼
堡垒机 10.10.192.55:22  (齐治 Shterm v3.3.13)
  用户名: zhaokaihang/<target_ip>/<target_user>  ← 路由到目标
    │
    ▼
目标服务器 10.102.234.45 (infra@Ubuntu 22.04)
```

`agent.py` 以 **daemon 模式**运行：每个 profile 对应一台目标服务器和一个本地 daemon 端口。
`serve <profile>` 认证一次（静态密码 + 动态 OTP）后，针对该 profile 的命令会复用同一条 SSH transport，不再触发 OTP。

---

## 前置条件

- Python 3.x
- `pip install paramiko`
- VPN 已连接（能访问 10.10.192.55）

---

## 快速开始

### 第 0 步：配置并保存凭据（只做一次）

```powershell
python agent.py setcreds app1
```

交互示例：

```
Configure bastion connection (press Enter to keep shown default):

Bastion host/IP [10.10.192.55]: 
Bastion port [22]: 
                                        
Username format: <local_user>/<target_ip>/<target_user>
  e.g. zhaokaihang/10.102.234.45/infra
Bastion username [zhaokaihang/10.102.234.45/infra]: 
Local daemon port [19922]:
Static password (saved): ****

[OK] Saved to .bastion_creds
     profile=app1  host=10.10.192.55  port=22  user=zhaokaihang/10.102.234.45/infra  daemon_port=19922
```

所有字段均有默认值，直接回车跳过即保留当前值。配置写入 `.bastion_creds`（勿提交 git）。
如果需要连接多台后端服务器，为每台服务器创建一个 profile，并分配不同的本地 daemon 端口：

```powershell
python agent.py setcreds app1   # daemon_port 19922
python agent.py setcreds app2   # daemon_port 19923
python agent.py profiles
```

动态 OTP **不保存**，每次 `serve` 时手动输入。

### 第 1 步：启动 daemon（每次 VPN 重连后执行）

```powershell
python agent.py serve app1
```

依次提示：
1. 静态密码（自动从 `.bastion_creds` 读取，也可现场输入）
2. 动态 OTP（每次手动输入）

认证成功后 daemon 在后台监听该 profile 配置的本地端口，**保持此窗口打开**。
如果要同时连接多台后端服务器，在不同终端分别启动：

```powershell
python agent.py serve app1
python agent.py serve app2
```

### 第 2 步：在任意其他终端使用

```powershell
# 检查 daemon 是否存活
python agent.py --profile app1 ping

# 执行远端命令（结果直接输出）
python agent.py --profile app1 run "uname -a"
python agent.py --profile app1 run "df -h"
python agent.py --profile app1 run --timeout 300 "apt install -y vim"  # 自定义超时

# 命令卡住时（等待交互输入）
python agent.py --profile app1 send "y"      # 发送输入解锁
python agent.py --profile app1 cancel        # 发送 Ctrl+C 中断并恢复

# 打开交互式 shell（Ctrl+C 转发给远端，不终止本地连接）
python agent.py --profile app1 shell

# 上传文件（本地 → 远端）
python agent.py --profile app1 upload C:\scripts\deploy.sh /tmp/deploy.sh

# 下载文件（远端 → 本地）
python agent.py --profile app1 download /var/log/app.log C:\logs\app.log

# 停止 daemon
python agent.py --profile app1 stop
```

---

## 命令阻塞处理

`run` 遇到需要交互输入的命令（如 `apt install`、`sudo` 需确认等）时，超时后**不会自动中断**，而是打印提示让用户或 agent 决策：

```
[BLOCKED] Command did not finish within 120s.
It may be waiting for interactive input.
Last output:
  Do you want to continue? [Y/n]

Options:
  python agent.py send "y"        -- 供给期望的输入
  python agent.py cancel          -- 发送 Ctrl+C 并恢复
  python agent.py run --timeout N -- 延长超时重试
```

---

## 认证流程说明

| 步骤 | 说明 |
|------|------|
| 静态密码 (p1) | SSH keyboard-interactive，每个 session 一次 |
| 动态 OTP (p2) | 堡垒机 in-band `2nd Password:` 提示，每次 `serve` 输入一次 |
| 后续命令 | 复用同一 SSH transport，不再触发 OTP |

> **注意**：OTP 是一次性的，无法保存。只有 `serve` 需要输入。

---

## 文件清单

| 文件 | 用途 |
|------|------|
| `agent.py` | 核心脚本，包含 daemon 和所有客户端命令 |
| `.bastion_creds` | 堡垒机连接配置 + 静态密码缓存（JSON，自动生成，勿提交 git） |
