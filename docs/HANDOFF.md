# 工程 Handoff

生成日期：2026-09-01

工作分支：`feature/cloud-edge-control-plane`

基线来源：`refactor/desktop-ui-v2` @ `076ad3d0e3f7461efa6686a0aaa5a12621b650d9`。

> 安全约束：本文以及仓库其他文档不得记录真实 Bot Token、Agent Token、Cookie、Credential、Session/CSRF、管理员明文密码或签名媒体 URL。

## 1. 当前目标架构

本分支已经把部署模型从“Web + Bot + Playback 同机”扩展为正式的 Cloud / Edge 分离模式，同时保留原单机入口作为兼容模式。

### Cloud Control Plane

入口：

```text
cloud/run.py
```

职责：

- 公网 Web UI / HTTP API；
- Web 用户、Session、CSRF、Admin/User、Scope；
- SQLite IAM / audit；
- Edge Agent Registry；
- WSS Relay Hub；
- Runtime Read Cache；
- 把现有 `/api/*` Contract 转成严格白名单 RPC。

Cloud 不持有：

```text
BOT_TOKEN
音乐平台 Cookie/Credential
Node API
FFmpeg
PlayHandler
```

### Edge Runtime

入口：

```text
edge/run.py
```

职责：

- 根据 OS 选择 `windows/` 或 `Ubuntu/` 现有运行时；
- 启动网易云 / QQ 本地 Node API；
- 启动 KOOK Bot；
- 保留原 `kookvoice`、PlayHandler、FFmpeg、Opus/RTP；
- Flask API 强制绑定 `127.0.0.1`；
- Edge Agent 主动通过 WSS 连接 Cloud；
- 接收 Cloud 业务命令并调用 loopback 现有 API；
- 周期推送拓扑、播放状态和健康状态。

Edge 不需要公网 IP，也不开放任何公网入站端口。

## 2. 关键设计

### 2.1 通信

```text
Browser
  -> HTTPS
Cloud
  -> WSS command
Edge Agent
  -> 127.0.0.1 Flask API
Existing Runtime
```

Edge 主动发起：

```text
wss://<public-domain>/edge/v1/connect
```

外部反向代理把该路径转给 Cloud Relay；其他 HTTP 请求转给 Cloud Flask。

### 2.2 Keepalive

不是单独的 keepalive TCP，而是：

```text
WebSocket ping/pong
+
应用层 heartbeat
+
指数退避重连
```

默认：

- application heartbeat：15 秒；
- runtime state：5 秒；
- topology/full state：300 秒。

### 2.3 命令协议

唯一协议定义：

```text
shared/relay_protocol.py
```

当前版本：

```text
PROTOCOL_VERSION = 1
```

只允许 `ACTIONS` 中显式声明的业务动作。

严禁增加：

```text
shell
exec
任意 subprocess
任意 URL 请求
任意文件读写
```

### 2.4 离线语义

Cloud 不对播放写命令做离线排队。

Agent 离线：

```text
HTTP 503
EDGE_OFFLINE
```

命令超时：

```text
HTTP 504
EDGE_TIMEOUT
```

每条命令带 deadline 和唯一 id。Edge 缓存最近 1024 个 result，重复 command id 不重复执行。

## 3. 状态所有权

Edge 始终是运行状态权威源。

Cloud 只保存 Read Cache：

```text
Guild
Channel
Active Channel
Queue
Now Playing
Playback Modes
Health
Account Status
```

高频读取：

```text
/api/guilds
/api/channels
/api/channels/active
/api/playlist/current
```

优先使用 Cloud Cache，避免浏览器轮询每次跨公网 RPC。

搜索、账号操作、播放写操作实时走 Edge。

## 4. KOOK Bot 故障隔离

KOOK Bot 完整留在 Edge，并继续直接调用现有平台适配器与 `kookvoice`。

因此 Cloud/WSS 故障时：

```text
KOOK Bot           正常
正在播放           正常
队列自动推进       正常
FFmpeg/RTP         正常
Web UI             不可用或显示旧状态
远程 Web 控制      不可用
```

不要把 Bot Command 改造成必须经过 Cloud 的 RPC。

## 5. Web 鉴权

Cloud 复用当前成熟的 `windows/auth.py` Auth 实现以及 Windows 共享模板/静态资源。

Cloud SQLite 保存：

```text
users
sessions
login_attempts
guilds
channels
user_scopes
audit_logs
schema_migrations
edge_agents
edge_agent_guilds
```

Role/Scope 仍为：

```text
admin -> global
user  -> playback.read + playback.control + Global/Guild/Channel Scope
```

Edge 的 `data/edge_internal.db` 只用于 loopback Agent Service Session，不是 Web 用户数据库。

## 6. Agent 身份

第一版：

```text
TLS/WSS
+
EDGE_AGENT_ID
+
EDGE_AGENT_TOKEN >= 32 chars
```

WebSocket Upgrade：

```http
Authorization: Bearer <agent token>
X-Agent-ID: edge-main
```

Cloud DB 只保存 Agent Token SHA-256。

Agent Token 只能通过部署环境变量/Secret 管理，不进 Git。

## 7. 新增目录

```text
cloud/
  __init__.py
  app.py
  run.py
  relay.py
  runtime_proxy.py
  agent_registry.py
  requirements.txt
  .env.example
  Caddyfile.example

edge/
  __init__.py
  run.py
  agent.py
  local_control.py
  .env.example

shared/
  __init__.py
  relay_protocol.py

docs/
  cloud-edge-architecture.md
  cloud-edge-deployment.md
```

## 8. 现有目录的角色

`windows/` / `Ubuntu/` 不再需要复制一份新的 Remote Runtime 实现。

`edge/run.py` 直接复用其成熟代码，因此：

- Bot 指令行为不变；
- Node API 生命周期不变；
- QQ Credential lifecycle 不变；
- Bilibili 直连模式不变；
- PlayHandler/FFmpeg/RTP 不变；
- watchdog 不变；
- 安全加固边界继续生效。

原：

```text
python windows/run.py
python Ubuntu/run.py
```

仍是单机兼容模式。

正式分离部署使用：

```text
python cloud/run.py
python edge/run.py
```

## 9. Cloud 部署关键点

Cloud 只运行单进程第一版：

```text
1 Flask process
1 aiohttp Relay event loop
1 Runtime Read Cache
```

不要直接启动多个独立 Gunicorn worker，因为 Agent WebSocket 所有权和 Cache 当前不跨进程共享。

Cloud 监听建议：

```text
127.0.0.1:18473 Flask
127.0.0.1:18476 Relay
```

公网只开放 HTTPS 443，由 Caddy/Nginx：

```text
/edge/v1/connect -> 18476
其他请求         -> 18473
```

## 10. Edge 部署关键点

现有平台 `.env` 保留 BOT_TOKEN、Node API、FFmpeg、ALLOW* 和 Credential 配置。

新增 `edge/.env`：

```text
EDGE_AGENT_ID
EDGE_AGENT_TOKEN
EDGE_RELAY_URL
```

Edge Flask 被代码强制：

```text
127.0.0.1 only
```

不允许把 18473/18474/18475 做公网端口映射。

## 11. 数据迁移

如保留当前 Web 用户，停止旧实例后把原：

```text
windows/data/kook_music.db
或 Ubuntu/data/kook_music.db
```

复制到：

```text
cloud/data/kook_music.db
```

音乐平台状态仍留在 Edge：

```text
.env
Cookie/
```

不要把音乐 Cookie 搬到 Cloud。

## 12. 当前验证状态

按项目所有者要求，本次 Cloud/Edge 实现：

- 没有创建 PR；
- 没有创建或主动运行 CI；
- 没有修改现有 GitHub Actions；
- 新架构质检留给其他 Agent 或人工执行。

本分支新增代码集中在 `cloud/`、`edge/`、`shared/` 和 `docs/`，没有为了 Remote 架构改写 Windows/Ubuntu 播放核心。

后续质检至少应执行：

1. Python compile；
2. `shared/relay_protocol.py` Action/path 一致性；
3. Cloud/Edge 同机 `ws://` 联调；
4. Caddy/Nginx `wss://` 联调；
5. Admin/User/Scope；
6. 三平台搜索/账号/歌单；
7. join/play/pause/resume/skip/seek/promote/clear；
8. Cloud 断网时 Bot/Playback 连续性；
9. Edge 重连后的 full state 恢复；
10. Agent Token 错误/禁用/重复连接；
11. 超时命令不延迟执行；
12. 日志与 WSS 中不存在 Credential 泄漏。

## 13. 推荐阅读顺序

1. `docs/HANDOFF.md`
2. `docs/cloud-edge-architecture.md`
3. `docs/cloud-edge-deployment.md`
4. `shared/relay_protocol.py`
5. `cloud/relay.py`
6. `cloud/runtime_proxy.py`
7. `edge/agent.py`
8. `edge/local_control.py`
9. `edge/run.py`
10. `docs/security-hardening.md`

## 14. 后续扩容方向

当前 Cloud 为单实例。

真正需要多 Cloud Worker / HA 时，再引入：

```text
Redis 或 NATS
Agent connection ownership
Command correlation bus
Shared Runtime Read Model
```

不要在当前版本直接用多 worker 共享同一个公网域名，否则请求可能落到不持有对应 Agent WebSocket 的进程。
