# hermes-gateway@ systemd 部署指南（3 实例）

> 将 UT Workflow 的 3 个 Kanban Gateway（ut-orchestrator / ut-executor / ut-fixer）作为 systemd 模板实例服务运行 — 认领并派发 `apmm-ut` 看板任务

---

## 1. 概述

Kanban 模式下，UT Workflow 的任务状态存放在 Hermes 看板 `apmm-ut`，由 **Gateway 内嵌的 Kanban 派发器**把就绪任务派发到对应的 worker profile。这里有 **3 个 Gateway**，每个绑定一个 profile，各司其职：

| Profile | 职责 |
|---------|------|
| `ut-orchestrator` | 创建批次任务、协调 workflow 进度（Stage 5 reconcile + Stage 2 select） |
| `ut-executor` | 在 `t_h20` 上执行 pytest 批次 |
| `ut-fixer` | 分析失败、创建 fix / retry 动作 |

本指南把它们封装成 systemd 模板实例服务 `hermes-gateway@.service`，分别实例化为 `hermes-gateway@ut-orchestrator`、`hermes-gateway@ut-executor`、`hermes-gateway@ut-fixer`，实现开机自启、崩溃自动重启、统一日志。

**与 Supervisor 服务的关系**：

| 角色 | systemd unit | 数量 | 职责 |
|------|------|:---:|------|
| **Supervisor** | `hermes-agent@ut-supervisor` | 1 | 订阅飞书、跑状态机、监控进度 |
| **Kanban Gateway** | `hermes-gateway@{ut-orchestrator,ut-executor,ut-fixer}` | 3 | 不订阅飞书，仅认领 / 派发 `apmm-ut` 看板任务（本指南） |

线性模式（`kanban.enabled: false`）只需 Supervisor；Kanban 模式下 **Supervisor 负责监控、3 个 Gateway 负责派发**。Supervisor 服务部署见 [hermes-supervisor-service.md](hermes-supervisor-service.md)。

---

## 2. 前置条件

### 2.1 看板 `apmm-ut` 已存在

Gateway 派发器从看板 `apmm-ut` 拉取就绪任务。启动前该看板须已创建并可切换：

```bash
hermes kanban boards list
hermes kanban boards switch apmm-ut
```

> `skills/ut/terminal-workflow/scripts/start_gateway.py` 在拉起 Gateway 前会先 `hermes kanban boards switch apmm-ut`。systemd 部署下，看板切换是**进程级**状态，建议把 `hermes kanban boards switch apmm-ut` 并入每个实例的 `ExecStartPre`（见 §3），确保每个 Gateway 进程都对准同一看板。

### 2.2 3 个 worker profile 已部署

每个实例对应一个 Hermes profile，须已部署到 Hermes profile 路径（live Hermes 安装下已存在 `ut-orchestrator` / `ut-executor` / `ut-fixer` 三个 profile）：

```bash
hermes profile list   # 应能看到 ut-orchestrator / ut-executor / ut-fixer
```

profile 的具体内容（飞书绑定、skill 加载等落点）参考 [hermes-supervisor-service.md](hermes-supervisor-service.md) §2.1 的 SCHEMA NOTE。Gateway profile **不订阅飞书**，只加载 worker 行为 skill（如 `ut/hermes-workflow` 的 worker SOUL）。

### 2.3 Bastion 凭据/配置可用

`ut-executor` 会在 `t_h20` 上跑 pytest，依赖 Bastion daemon。须先按 [bastion.md](../../../docs/guides/bastion.md) 配好对应 profile 的 `.bastion_creds`，并确认 `workflow.yaml` 的 `bastion` 节指向该 profile。动态 OTP 在运行期通过飞书回复提供（由 Supervisor 通道处理），不预存。

> worker 远程执行必须用 `python tools/agent.py -p t_h20 run ...`，**不得**直接 `ssh` 堡垒机（见 `tasks/ut/docs/kanban/README.md` 的 Remote Execution Rule）。

### 2.4 Hermes 已安装

```bash
hermes version
```

---

## 3. systemd unit 文件

使用 systemd 模板实例形式（`@`）。文件名 `hermes-gateway@.service`，`%i` = profile 名（`ut-orchestrator` / `ut-executor` / `ut-fixer`）。**一个模板文件，3 个实例复用**。

> 推荐以 user service 运行（`systemctl --user`），避免占用 root；如需开机即起（无需登录会话），用 system-level unit 并配 `lingering`。下例为 user service。

放置于 `~/.config/systemd/user/hermes-gateway@.service`：

```ini
[Unit]
Description=Hermes Kanban Gateway (%i) — UT Workflow dispatcher
After=network-online.target
Wants=network-online.target

[Service]
Type=simple

# ── 部署相关：按实际环境替换 ───────────────────────────
WorkingDirectory=/path/to/apmm                              # ← 仓库根目录
EnvironmentFile=/path/to/apmm/.agents/hermes-gateway.env    # ← 飞书/Bastion 密钥（勿提交 git）
# ─────────────────────────────────────────────────────

# 看板切换为进程级状态，启动前对准 apmm-ut。
ExecStartPre=/usr/bin/env bash -lc 'hermes kanban boards switch apmm-ut'

# ExecStart：激活 %i profile 后常驻运行 Gateway 内嵌派发器。
# 这是仓库内已验证的 Hermes 长驻命令（见 start_gateway.py：
#   hermes profile use <profile> && hermes gateway run）。
ExecStart=/usr/bin/env bash -lc 'hermes profile use %i && hermes gateway run'

Restart=on-failure
RestartSec=10
TimeoutStopSec=30

# 日志走 journald
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

字段说明：

| 字段 | 说明 |
|------|------|
| `%i` | 实例名 = profile 名（`ut-orchestrator` 等），使同一模板可被 3 个实例复用 |
| `WorkingDirectory` | **部署相关**：apmm 仓库根，使 skill / `.agents/` 相对路径可解析 |
| `EnvironmentFile` | **部署相关**：存飞书 app_secret、Bastion 静态密码等，文件权限 `600`，不入 git |
| `ExecStartPre` | 每进程对准看板 `apmm-ut`（接地于 start_gateway.py 的 `switch_board`） |
| `ExecStart` | 接地于 start_gateway.py：`hermes profile use %i`（line 60）+ `hermes gateway run`（line 73），二者均为仓库已验证命令 |
| `Restart=on-failure` | 进程非零退出自动重启 |

> **ExecStart 接地说明**：`skills/ut/terminal-workflow/scripts/start_gateway.py` 对每个 profile 执行 `hermes profile use <profile>`（`start_profile_gateway`）后以后台进程启动 `hermes gateway run`，并用 `hermes gateway list` 校验是否带 `✓` 在线。本指南直接把这套命令搬进 systemd `ExecStart`，无需臆造 flag。
>
> **`run` vs `start`（DEPLOY-CONFIRM）**：`tasks/ut/docs/kanban/README.md` 指出 `hermes gateway start` 可能提示安装计划任务（scheduled service），故脚本用前台 `hermes gateway run` + 后台分离。systemd 已负责常驻与重启，因此**沿用 `hermes gateway run`**；若部署机的 `hermes gateway run` 不是前台常驻（例如某些版本 `run` 会立即返回），请以部署机 `hermes gateway --help` 为准调整为常驻形式（DEPLOY-CONFIRM）。
>
> **不要混用 daemon**：`hermes kanban daemon` 在 Hermes v0.16 已弃用，且与 Gateway 派发器会争抢任务认领，**不要**与本服务同时运行（见 README）。
>
> **`tools/agent.py` 无关**：它是 Bastion SSH daemon 工具（`serve` / `run` / `ping`），不要用作 ExecStart。

---

## 4. 启用 3 个实例

修改 `.service` 后先 reload，再用 brace expansion 一次启用 3 个实例：

```bash
# 重载 unit 定义
systemctl --user daemon-reload

# 开机自启 + 立即启动 3 个实例（brace expansion）
systemctl --user enable --now hermes-gateway@ut-{orchestrator,executor,fixer}
```

等价于显式写全 3 个：

```bash
systemctl --user enable --now \
  hermes-gateway@ut-orchestrator \
  hermes-gateway@ut-executor \
  hermes-gateway@ut-fixer
```

---

## 5. 与 check_gateways_alive() 的对应

Supervisor 在 Kanban 模式（`kanban.enabled: true`）启动校验时，会调用 `hermes_runner.check_gateways_alive()` 确认这 3 个 Gateway 在线。该函数（`skills/ut/terminal-workflow/scripts/hermes_runner.py`）的机制是：

```python
KANBAN_GATEWAY_PROFILES = ("ut-orchestrator", "ut-executor", "ut-fixer")

def _systemctl_active(unit: str) -> bool:
    # systemctl is-active --quiet <unit>，exit 0 即视为 active
    ...

def check_gateways_alive() -> dict:
    return {
        profile: _systemctl_active(f"hermes-gateway@{profile}")
        for profile in KANBAN_GATEWAY_PROFILES
    }
```

也就是说它逐一执行：

```bash
systemctl is-active --quiet hermes-gateway@ut-orchestrator
systemctl is-active --quiet hermes-gateway@ut-executor
systemctl is-active --quiet hermes-gateway@ut-fixer
```

**因此本指南的 unit 命名 `hermes-gateway@<profile>` 必须与 `check_gateways_alive()` 检查的字符串逐字一致** —— 即 `hermes-gateway@ut-orchestrator` / `hermes-gateway@ut-executor` / `hermes-gateway@ut-fixer`。改名会导致 Supervisor 启动校验误报某 Gateway 未 active。

> 注意：`check_gateways_alive()` 用的是**非 `--user`** 的 `systemctl is-active`，即默认查 system-level 实例。若本服务以 `systemctl --user` 部署，请在部署时与 `check_gateways_alive()` 的查询级别对齐（DEPLOY-CONFIRM）：要么把校验改为 user-level，要么把服务部署为 system-level unit（放 `/etc/systemd/system/`、命令去掉 `--user`、unit 内设 `User=`）。否则 unit 名一致但 systemctl 查不到对应实例。

---

## 6. 运维操作

```bash
# 查看单个实例状态
systemctl --user status hermes-gateway@ut-orchestrator

# 一次查 3 个实例
systemctl --user status hermes-gateway@ut-{orchestrator,executor,fixer} --no-pager

# 实时日志（按实例）
journalctl --user -u hermes-gateway@ut-executor -f

# 重启 / 停止单个实例
systemctl --user restart hermes-gateway@ut-fixer
systemctl --user stop    hermes-gateway@ut-fixer

# 关闭某实例自启
systemctl --user disable hermes-gateway@ut-orchestrator
```

> 若需用户登出后仍运行：`loginctl enable-linger $USER`。
> 若用 system-level（非 `--user`）unit：放 `/etc/systemd/system/`，命令去掉 `--user`，并在 unit 内设 `User=`。

---

## 7. 验证与排错

### 7.1 确认 3 个 Gateway 都 active

```bash
# 逐一返回 active（与 check_gateways_alive() 同款查询）
for p in ut-orchestrator ut-executor ut-fixer; do
  echo -n "$p: "; systemctl --user is-active hermes-gateway@$p
done
```

也可用 Hermes 自带视图交叉验证（start_gateway.py 用的就是它）：

```bash
hermes gateway list     # 对应 profile 行应带 ✓
hermes gateway status
```

### 7.2 常见问题

| 现象 | 排查 |
|------|------|
| 某实例起不来 / 反复重启 | `journalctl --user -u hermes-gateway@<profile> -e`；多为 `ExecStart` 子命令、`WorkingDirectory` 或 profile 不存在 → 核对 §2.2、§3 |
| Supervisor 报某 Gateway 未 active（红色错误卡片） | 该 unit 未起，或 user/system 查询级别不匹配 → 见 §5 的 DEPLOY-CONFIRM；用 §7.1 复核 |
| 3 个都 active 但任务不流转 | 看板未对准 → 确认 `ExecStartPre` 的 `hermes kanban boards switch apmm-ut` 生效（§2.1）；`hermes kanban diagnostics` 查看阻塞 |
| 任务被重复认领 / 争抢 | 是否同时跑了 `hermes kanban daemon` → 停掉，只保留 Gateway（§3） |
| executor 远程执行失败 | `python tools/agent.py -p t_h20 ping`；见 [bastion.md](../../../docs/guides/bastion.md) 与 `tasks/ut/docs/guides/hermes-runner.md` |

---

## 8. 相关文档

| 文档 | 说明 |
|------|------|
| [hermes-supervisor-service.md](hermes-supervisor-service.md) | Supervisor（1 个长驻 Agent）的 systemd 部署指南 |
| `tasks/ut/docs/kanban/README.md` | Kanban 集成、3 worker profile、`start_gateway.py` 包装器、远程执行规则 |
| `skills/ut/terminal-workflow/scripts/start_gateway.py` | Gateway 启动包装器（本指南 ExecStart 的接地来源） |
| `skills/ut/terminal-workflow/scripts/hermes_runner.py` | `check_gateways_alive()`（§5 的 unit 命名来源） |
| `skills/ut/hermes-workflow/ut-orchestrator-SOUL.md` | orchestrator worker 行为（Stage 5 reconcile + Stage 2 select） |
| [bastion.md](../../../docs/guides/bastion.md) | Bastion 堡垒机连接与凭据配置 |
| `tasks/ut/docs/guides/hermes-runner.md` | Runner 双模式运行、OTP 交互、排错 |

---

*创建日期: 2026-06-20*
