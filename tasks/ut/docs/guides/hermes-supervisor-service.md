# hermes-agent@ut-supervisor systemd 部署指南

> 将 UT Workflow 的 ut-supervisor Hermes Agent 作为长期 systemd 服务运行 — 订阅飞书、驱动 workflow 主循环

---

## 1. 概述

`ut-supervisor` 是 UT Workflow 的**生产运行主体**：一个长期运行的 Hermes **Agent**，订阅飞书 `apmm-ut` 群，识别触发关键词后加载 `ut/hermes-workflow` skill，驱动整个 workflow 状态机（running / paused / waiting_otp / completed / stopped / failed），并通过飞书 OTP 自动恢复 Bastion 连接。

本指南将其封装为 systemd 模板实例服务 `hermes-agent@ut-supervisor.service`，实现开机自启、崩溃自动重启、统一日志。

**与 3 个 Gateway 服务的关系**：

| 角色 | systemd unit | 数量 | 职责 |
|------|------|:---:|------|
| **Supervisor** | `hermes-agent@ut-supervisor` | 1 | 订阅飞书、跑状态机、监控进度（本指南） |
| **Kanban Gateway** | `hermes-gateway@{ut-orchestrator,ut-executor,ut-fixer}` | 3 | 不订阅飞书，仅派发 Kanban worker subprocess |

线性模式（`kanban.enabled: false`）只需 Supervisor；Kanban 模式下 Supervisor 监控，3 个 Gateway 负责派发。Gateway 服务部署见 [hermes-gateway-service.md](hermes-gateway-service.md)。

---

## 2. 前置条件

### 2.1 ut-supervisor profile 已部署

将 profile 目录部署到 Hermes profile 路径（如 `~/.local/share/hermes/profiles/ut-supervisor/` 或对应平台路径）：

- `profile.yaml` — 参考仓库 `skills/ut/hermes-workflow/profile.yaml`。

> **重要（见 profile.yaml 的 SCHEMA NOTE）**：真实 Hermes `profile.yaml` 只含 `description` / `description_auto` 两个键。飞书绑定与 skill 加载**不在** `profile.yaml`，而在 profile 目录的其他文件中按部署时配置：
>
> | 配置项 | 落点 |
> |------|------|
> | 飞书 chat 绑定 | `channel_directory.json` → `platforms.feishu[].id` |
> | 飞书 skill 绑定 | `config.yaml` → `platforms.feishu.channel_skill_bindings` |
> | skill 加载 | `config.yaml` → `skills.*`（+ profile `skills/` 目录） |
>
> 部署时务必把 `<feishu_chat_id>` 占位符替换为真实群 chat_id，并绑定 `ut/hermes-workflow` 等 skill。

### 2.2 Bastion 凭据/配置可用

Supervisor 启动时会拉起一条 Bastion daemon 连接（OTP 自动恢复）。需先按 [bastion.md](../../../docs/guides/bastion.md) 配置好对应 profile（如 `t_h20`）的 `.bastion_creds`，并确认 `workflow.yaml` 的 `bastion` 节指向该 profile。动态 OTP 在运行期通过飞书回复提供，不预存。

### 2.3 飞书 chat_id 已设置

`apmm-ut` 群的 chat_id（形如 `oc_xxxxxxxx...`）须在 §2.1 的 `channel_directory.json` 中绑定，且机器人已加入该群、具备 `im:message` / `im:message:read` 权限（参考 hermes-runner.md §2.2）。

### 2.4 Hermes 已安装

```bash
hermes version
```

---

## 3. systemd unit 文件

使用 systemd 模板实例形式（`@`）。文件名 `hermes-agent@.service`，实例化为 `hermes-agent@ut-supervisor`，其中 `%i` = `ut-supervisor`。

> 推荐以 user service 运行（`systemctl --user`），避免占用 root；如需开机即起（无需登录会话），用 system-level unit 并配 `lingering`。下例为 user service。

放置于 `~/.config/systemd/user/hermes-agent@.service`：

```ini
[Unit]
Description=Hermes Agent (%i) — UT Workflow supervisor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple

# ── 部署相关：按实际环境替换 ───────────────────────────
WorkingDirectory=/path/to/apmm                 # ← 仓库根目录
EnvironmentFile=/path/to/apmm/.agents/hermes-agent.env   # ← 飞书/Bastion 密钥（勿提交 git）

# ExecStart：激活 ut-supervisor profile 后以 Agent 形式常驻订阅飞书。
# 注意：仓库内已验证的 Hermes 长驻命令是 `hermes gateway run`（见 start_gateway.py）；
# Agent 订阅模式的确切子命令需以部署机 `hermes --help` 为准，下面是代表性写法，
# 部署时请确认（DEPLOY-CONFIRM）。
ExecStart=/usr/bin/env bash -lc 'hermes profile use %i && hermes agent run'
# ─────────────────────────────────────────────────────

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
| `%i` | 实例名 = `ut-supervisor`，使同一模板可复用 |
| `WorkingDirectory` | **部署相关**：apmm 仓库根，使 skill / `.agents/` 相对路径可解析 |
| `EnvironmentFile` | **部署相关**：存飞书 app_secret、Bastion 静态密码等，文件权限 `600`，不入 git |
| `ExecStart` | **DEPLOY-CONFIRM**：`hermes profile use %i` 已验证；`hermes agent run` 为代表性 Agent 长驻命令，须以部署机 `hermes --help` 实际子命令为准 |
| `Restart=on-failure` | 进程非零退出自动重启（OTP 等待属正常运行态，不会触发退出） |

> **ExecStart 接地说明**：仓库中唯一被脚本验证过的 Hermes 长驻命令是 `hermes gateway run`（`skills/ut/workflow/scripts/start_gateway.py`、`tasks/ut/docs/kanban/README.md`）。Supervisor 是 **Agent**（飞书订阅者）而非 Gateway（派发器），其专用启动子命令未在本仓库代码中固化，故上面标注为部署时确认。请勿臆造不存在的 flag。
>
> 另：仓库内的 `tools/agent.py` 是 **Bastion SSH daemon** 工具（`serve` / `run` / `ping`），与此处的 Hermes Agent 无关，**不要**用它作 ExecStart。

---

## 4. 运维操作

```bash
# 重载 unit 定义（每次修改 .service 后）
systemctl --user daemon-reload

# 开机自启 + 立即启动
systemctl --user enable --now hermes-agent@ut-supervisor

# 查看状态
systemctl --user status hermes-agent@ut-supervisor

# 实时日志
journalctl --user -u hermes-agent@ut-supervisor -f

# 重启 / 停止
systemctl --user restart hermes-agent@ut-supervisor
systemctl --user stop hermes-agent@ut-supervisor

# 关闭自启
systemctl --user disable hermes-agent@ut-supervisor
```

> 若需用户登出后仍运行：`loginctl enable-linger $USER`。
> 若用 system-level（非 `--user`）unit：放 `/etc/systemd/system/`，命令去掉 `--user`，并在 unit 内设 `User=`。

---

## 5. 验证与排错

### 5.1 确认已订阅飞书

1. `systemctl --user status hermes-agent@ut-supervisor` 显示 `active (running)`。
2. 在 `apmm-ut` 群发送触发关键词（如 `跑 ut workflow`）。
3. 机器人应回复【参数确认卡片】（蓝色，展示 test_list_path / batch_size / manifest_source / kanban.enabled / resume_from 五字段）。收到即说明订阅与 skill 加载正常。
4. 看日志确认无报错：`journalctl --user -u hermes-agent@ut-supervisor -f`。

### 5.2 常见问题

| 现象 | 排查 |
|------|------|
| 服务起不来 / 反复重启 | `journalctl --user -u hermes-agent@ut-supervisor -e`；多为 `ExecStart` 子命令或 `WorkingDirectory` 不对 → 核对 §3 DEPLOY-CONFIRM 项 |
| 发关键词无回复 | 检查 `channel_directory.json` 的 chat_id 绑定（§2.1）、机器人是否在群、飞书权限（§2.3） |
| 起了但不加载 workflow | 检查 `config.yaml` 的 `channel_skill_bindings` 与 `skills.*` 是否绑定 `ut/hermes-workflow`（§2.1 SCHEMA NOTE） |
| Bastion 连不上 / 一直等 OTP | 见 [bastion.md](../../../docs/guides/bastion.md) 与 hermes-runner.md §6.1；运行期在飞书回复 `OTP <request_id> <code>` 恢复 |
| Kanban 模式启动校验失败 | 红色错误卡片提示某 Gateway 未 active → 见 [hermes-gateway-service.md](hermes-gateway-service.md) |

---

## 6. 相关文档

| 文档 | 说明 |
|------|------|
| `skills/ut/hermes-workflow/SKILL.md` | Supervisor 通道 skill（状态机 / 回调 / OTP） |
| `skills/ut/hermes-workflow/profile.yaml` | ut-supervisor profile（含部署绑定 SCHEMA NOTE） |
| [hermes-gateway-service.md](hermes-gateway-service.md) | 3 个 Kanban Gateway 的 systemd 模板部署指南 |
| [bastion.md](../../../docs/guides/bastion.md) | Bastion 堡垒机连接与凭据配置 |
| `tasks/ut/docs/guides/hermes-runner.md` | Runner 双模式运行、OTP 交互、排错 |

---

*创建日期: 2026-06-20*
