# Hermes Windows 服务部署指南（NSSM）

> Windows 上把 UT Workflow 的 4 个 Hermes 进程封装为开机自启的 Windows Service，对应 Linux 的 `hermes-agent@ut-supervisor` + `hermes-gateway@{ut-orchestrator,ut-executor,ut-fixer}`。
>
> Linux/Mac 部署见：[hermes-supervisor-service.md](hermes-supervisor-service.md) · [hermes-gateway-service.md](hermes-gateway-service.md)

---

## 0. 概述

| 平台 | 服务管理工具 | 本指南覆盖 |
|------|------|:---:|
| Linux | `systemd --user` | ❌（见 supervisor/gateway 两份文档） |
| **Windows** | **NSSM**（Non-Sucking Service Manager） | ✅ |
| macOS | `launchd` (`launchctl`) | 简表见 §7 |

NSSM 把任意 `python.exe foo.py` 包装成 Windows Service，提供：开机自启、崩溃自动重启、日志重定向、`net start` / `services.msc` 标准接口。

**最终落地的 4 个服务**（命名沿用 Linux 风格，便于对照）：

| Service 名 | 进程职责 | 对应 Linux unit |
|------|------|------|
| `hermes-agent@ut-supervisor` | 订阅飞书、状态机、触发 workflow | `hermes-agent@ut-supervisor.service` |
| `hermes-gateway@ut-orchestrator` | Kanban Stage5+Stage2 派发 | `hermes-gateway@ut-orchestrator.service` |
| `hermes-gateway@ut-executor` | Kanban Stage3 远程 pytest 派发 | `hermes-gateway@ut-executor.service` |
| `hermes-gateway@ut-fixer` | Kanban Stage4 修复派发 | `hermes-gateway@ut-fixer.service` |

> Windows 服务名允许 `@` 字符；如想极简可去掉（`hermes-ut-supervisor` 等），但保持与 Linux 一致更易跨平台维护。

线性模式（`kanban.enabled: false`）只需 supervisor 服务；Kanban 模式需要全部 4 个。

---

## 1. 前置条件

### 1.1 安装 NSSM

```powershell
# 选项 A：scoop
scoop install nssm

# 选项 B：chocolatey
choco install nssm

# 选项 C：手动 — 从 https://nssm.cc/ 下载 64-bit，把 nssm.exe 放入 PATH
```

确认：
```powershell
nssm --version
```

### 1.2 仓库 / Hermes / Profile 已就绪

- apmm 仓库已 clone（本指南用 `D:\workspace\apmm` 占位）。
- `hermes version` 可在 PowerShell 跑通。
- 4 个 profile（`ut-supervisor` / `ut-orchestrator` / `ut-executor` / `ut-fixer`）已部署到 Hermes profile 目录（一般是 `%LOCALAPPDATA%\hermes\profiles\`）。
- `ut-supervisor` 已按 [hermes-supervisor-service.md §2.1](hermes-supervisor-service.md#21-ut-supervisor-profile-已部署) 完成飞书 chat 绑定 + skill 绑定。

### 1.3 Bastion 凭据已配置

按 [bastion.md](../../../docs/guides/bastion.md) 把 `t_h20` 的静态密码写入 `.bastion_creds`；OTP 在 supervisor 运行期通过飞书提供，不预存。

### 1.4 Python venv（推荐）

避免装到系统 Python：
```powershell
cd D:\workspace\apmm
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .  # 或按项目依赖文件
```
后续 NSSM 服务的 `Application` 字段指向 `.venv\Scripts\python.exe`。

---

## 2. 注册 4 个服务

> 下面命令以**管理员 PowerShell** 执行（NSSM 注册服务需要 admin）。
> 仓库路径用 `$REPO` 占位；按你的机器替换。

```powershell
$REPO = "D:\workspace\apmm"
$PY   = "$REPO\.venv\Scripts\python.exe"          # 或系统 python.exe
$HERMES = (Get-Command hermes).Source              # hermes 可执行路径
$LOG  = "$REPO\.agents\logs"
New-Item -ItemType Directory -Force -Path $LOG | Out-Null
```

### 2.1 supervisor 服务

```powershell
# 注册
nssm install hermes-agent@ut-supervisor $HERMES
nssm set    hermes-agent@ut-supervisor AppParameters "agent run"
nssm set    hermes-agent@ut-supervisor AppDirectory $REPO
nssm set    hermes-agent@ut-supervisor AppEnvironmentExtra "HERMES_PROFILE=ut-supervisor"
nssm set    hermes-agent@ut-supervisor AppStdout "$LOG\supervisor_ut-supervisor.out.log"
nssm set    hermes-agent@ut-supervisor AppStderr "$LOG\supervisor_ut-supervisor.err.log"
nssm set    hermes-agent@ut-supervisor AppRotateFiles 1
nssm set    hermes-agent@ut-supervisor AppRotateBytes 10485760     # 10 MB rotate
nssm set    hermes-agent@ut-supervisor Start SERVICE_AUTO_START    # 开机自启
nssm set    hermes-agent@ut-supervisor AppRestartDelay 10000       # 崩溃后 10s 重启
```

> **关于 `AppParameters` 的 `agent run`**：与 Linux unit 同样的 DEPLOY-CONFIRM 项 —— 仓库中已验证的长驻子命令是 `hermes gateway run`（gateway 服务用），Agent 订阅模式的子命令以部署机 `hermes --help` 为准，必要时替换。

### 2.2 三个 gateway 服务

```powershell
foreach ($p in @("ut-orchestrator", "ut-executor", "ut-fixer")) {
    $svc = "hermes-gateway@$p"
    nssm install $svc $HERMES
    nssm set    $svc AppParameters "gateway run"
    nssm set    $svc AppDirectory $REPO
    nssm set    $svc AppEnvironmentExtra "HERMES_PROFILE=$p"
    nssm set    $svc AppStdout "$LOG\gateway_$p.out.log"
    nssm set    $svc AppStderr "$LOG\gateway_$p.err.log"
    nssm set    $svc AppRotateFiles 1
    nssm set    $svc AppRotateBytes 10485760
    nssm set    $svc Start SERVICE_AUTO_START
    nssm set    $svc AppRestartDelay 10000
}
```

> 如果 hermes CLI 需要先 `hermes profile use <p>` 而不是读环境变量，把 `AppParameters` 改成包装脚本（PowerShell `.ps1` 或 `.bat`）：先 `hermes profile use $p` 再 `hermes gateway run`，然后让 NSSM 启动该 wrapper。

### 2.3 启动服务

```powershell
Start-Service hermes-agent@ut-supervisor
Start-Service hermes-gateway@ut-orchestrator
Start-Service hermes-gateway@ut-executor
Start-Service hermes-gateway@ut-fixer

# 或一行：
Get-Service hermes-* | Start-Service
```

---

## 3. 验证

```powershell
# 状态
Get-Service hermes-*

# 进程 PID（NSSM 包装下 hermes.exe 是子进程）
Get-Process hermes -ErrorAction SilentlyContinue | Select Id, ProcessName, StartTime

# 实时日志（手动 tail）
Get-Content "$LOG\supervisor_ut-supervisor.out.log" -Wait -Tail 30
```

功能性验证（端到端）：
1. 在飞书 `apmm-ut` 群发 `跑 ut workflow`。
2. 应收到机器人发的【参数确认卡片】（蓝色，5 字段）。
3. 回 `确认` → 进入触发流程；首次会要 OTP，回 6 位动态码即可。

---

## 4. 运维操作

| 操作 | 命令 |
|---|---|
| 启动单个 | `Start-Service <name>` |
| 停止单个 | `Stop-Service <name>` |
| 重启单个 | `Restart-Service <name>` |
| 一键全停 | `Get-Service hermes-* \| Stop-Service` |
| 一键全启 | `Get-Service hermes-* \| Start-Service` |
| 卸载服务 | `nssm remove <name> confirm` |
| 查看配置 | `nssm get <name> AppParameters` |
| 改配置 | `nssm set <name> AppParameters "..."`（改完需要 `Restart-Service`） |
| 服务面板 | `services.msc` |

> 改了 `skills/ut/hermes-workflow/SKILL.md` 或任何 Python（`ut_runner.py` 等）→ 至少 **重启 supervisor**；worker SKILL 改动也要重启对应 gateway。详见 [`ut-channels-overview.md`](ut-channels-overview.md) 关于 Hermes 不自动热升级的说明。

---

## 5. L4 调试场景：跳过服务，直接跑脚本

机器装服务前 / 临时调试时，**不走 NSSM**，仍然用 [`tasks/ut/scripts/start_hermes_ut_runtime.py`](../../scripts/start_hermes_ut_runtime.py)：

```powershell
cd D:\workspace\apmm

# 启动 bastion daemon（要 OTP）
python tools\agent.py serve t_h20

# 另一窗口：拉起 4 个 gateway/supervisor（前台日志）
python tasks\ut\scripts\start_hermes_ut_runtime.py

# 检查
python tasks\ut\scripts\start_hermes_ut_runtime.py --status

# 停止
python tasks\ut\scripts\start_hermes_ut_runtime.py --stop
```

NSSM 服务 vs `start_hermes_ut_runtime.py` 是**互斥的两条路径**：装了服务后不要再跑脚本，反之亦然，否则会有重复进程争同一 profile。

---

## 6. 常见问题

| 现象 | 排查 |
|------|------|
| `nssm install` 报权限 | 必须在**管理员** PowerShell 跑 |
| 服务起来又秒退 | 看 `AppStderr` 日志；通常是 `AppDirectory` 错、Python venv 路径错、profile 没绑 skill |
| `hermes` 命令找不到 | NSSM 不读 PATH 修改；用 `(Get-Command hermes).Source` 取出绝对路径填 `Application` |
| 飞书无响应 | profile `channel_directory.json` 的 chat_id / `config.yaml` 的 `channel_skill_bindings` 未配 → 见 [hermes-supervisor-service.md §2.1](hermes-supervisor-service.md) |
| 改了 SKILL 不生效 | NSSM 不会自动重启 — 手动 `Restart-Service hermes-agent@ut-supervisor`（worker SKILL 改动重启对应 gateway 服务） |
| Bastion daemon 谁起 | NSSM 服务**不管 bastion daemon**；首次飞书触发时 supervisor 会拉起，OTP 由飞书提供（与 Linux 行为一致） |
| 日志太大 | `AppRotateBytes` 默认 10MB（本文档 §2 已设）；按需调大或加 `AppRotateSeconds` |

---

## 7. macOS：launchd 简表

macOS 等价做法，每个服务一个 `~/Library/LaunchAgents/com.apmm.hermes.<role>.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.apmm.hermes.ut-supervisor</string>
  <key>WorkingDirectory</key><string>/path/to/apmm</string>
  <key>EnvironmentVariables</key><dict>
    <key>HERMES_PROFILE</key><string>ut-supervisor</string>
  </dict>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/hermes</string>
    <string>agent</string>
    <string>run</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/path/to/apmm/.agents/logs/supervisor.out.log</string>
  <key>StandardErrorPath</key><string>/path/to/apmm/.agents/logs/supervisor.err.log</string>
</dict>
</plist>
```

```bash
launchctl load   ~/Library/LaunchAgents/com.apmm.hermes.ut-supervisor.plist
launchctl unload ~/Library/LaunchAgents/com.apmm.hermes.ut-supervisor.plist
launchctl list | grep com.apmm.hermes
```

照此为 3 个 gateway 各写一份 plist。

---

## 8. 相关文档

| 文档 | 说明 |
|------|------|
| [hermes-supervisor-service.md](hermes-supervisor-service.md) | Linux systemd supervisor 部署（本指南姊妹篇） |
| [hermes-gateway-service.md](hermes-gateway-service.md) | Linux systemd 3 个 Kanban Gateway 部署 |
| [ut-channels-overview.md](ut-channels-overview.md) | 两个通道总览（含 mermaid 图 + skill 加载机制说明） |
| [bastion.md](../../../docs/guides/bastion.md) | Bastion 堡垒机连接与凭据配置 |
| [`tasks/ut/scripts/start_hermes_ut_runtime.py`](../../scripts/start_hermes_ut_runtime.py) | L4 调试 / 无服务管理时的 bootstrap 脚本 |

---

*创建日期: 2026-06-22*
