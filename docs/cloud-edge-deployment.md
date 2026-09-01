# Cloud / Edge 部署

## 前提

Cloud：

- Linux 云服务器；
- 公网 HTTPS 域名；
- Python 3.10+；
- 不需要 Node.js、FFmpeg、BOT_TOKEN 或音乐平台 Cookie。

Edge：

- Windows 或 Ubuntu；
- 不需要公网 IP；
- 必须允许出站 DNS、HTTPS/WSS、KOOK 和音乐平台访问；
- 保留现有 Node.js 20+、FFmpeg、BOT_TOKEN 和音乐平台凭据。

## 生成 Agent Token

在安全终端生成至少 256-bit 随机值，例如：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

同一个值分别放入：

```text
cloud/.env -> EDGE_AGENT_TOKEN
edge/.env  -> EDGE_AGENT_TOKEN
```

不要写入 Git、文档或命令行历史。

## Cloud

```bash
cd cloud
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

至少修改：

```env
EDGE_AGENT_ID=edge-main
EDGE_AGENT_TOKEN=<secret>
SECRET_KEY=<random-secret>
AUTH_COOKIE_SECURE=true
AUTH_TRUST_PROXY_HEADERS=true
```

启动：

```bash
python run.py
```

默认：

```text
Cloud Flask  127.0.0.1:18473
Edge Relay   127.0.0.1:18476
```

二者都不应直接开放公网。

### Caddy

参考 `cloud/Caddyfile.example`：

```caddy
music.example.com {
    @edge path /edge/v1/connect
    reverse_proxy @edge 127.0.0.1:18476

    reverse_proxy 127.0.0.1:18473
}
```

WebSocket Upgrade 由 Caddy 自动处理。

Nginx 使用时同样应把 `/edge/v1/connect` 单独反代到 `18476`，其他请求反代到 `18473`。

公网防火墙只开放：

```text
80  可选，仅用于跳转/ACME
443 HTTPS/WSS
```

不要开放 `18473`、`18476`。

## 迁移现有 Web 用户

Cloud 使用与现有控制面相同的 Auth Schema。

如需要保留现有用户、Scope 和审计，在旧实例停止后，把：

```text
windows/data/kook_music.db
或
Ubuntu/data/kook_music.db
```

复制到：

```text
cloud/data/kook_music.db
```

推荐重新登录所有浏览器，并根据域名/HTTPS 情况重新签发 Session。

若不迁移数据库，Cloud 首次启动会按现有 Auth 逻辑建立 Bootstrap 管理员。

## Edge

现有平台 `.env` 继续保存：

```text
BOT_TOKEN
ALLOW*
Cookie 路径
Node API 端口
FFmpeg
队列/资源上限
```

配置 `edge/.env`：

```env
EDGE_AGENT_ID=edge-main
EDGE_AGENT_TOKEN=<same-secret>
EDGE_RELAY_URL=wss://music.example.com/edge/v1/connect
EDGE_RELAY_TLS_VERIFY=true
```

然后从仓库根目录启动：

```bash
python edge/run.py
```

Windows：

```powershell
python edge\run.py
```

程序自动根据 OS 选择：

```text
Windows -> windows/
Linux   -> Ubuntu/
```

也可以通过 `EDGE_PLATFORM_DIR` 显式指定。

Edge 本地 Flask 被强制监听：

```text
127.0.0.1:18473
```

不需要也不应该配置端口映射。

## Edge 防火墙

Edge 无需任何公网入站规则。

允许必要出站：

```text
TCP 443 -> Cloud WSS
KOOK Gateway/API
网易云 / QQ / Bilibili
DNS
```

本机：

```text
127.0.0.1:18473 Edge Flask
127.0.0.1:18474 NetEase Node API
127.0.0.1:18475 QQ Node API
```

## 启动顺序

推荐：

```text
1. Cloud
2. HTTPS reverse proxy
3. Edge
4. 登录 Web 验证 Edge Online
```

但 Cloud 和 Edge 启动顺序不是硬依赖。

Edge 先启动时会按指数退避持续重连 Cloud，同时 KOOK Bot/播放运行时继续启动。

## 运行验证

Cloud：

```text
GET /healthz
```

管理员登录后：

```text
GET /api/edge/status
GET /api/edge/state
```

可查看 Agent 在线状态与同步状态。

正常情况下：

```text
connected=true
protocol_version=1
last_event_at 持续更新
```

Edge 日志应看到：

```text
Edge relay connected
Cloud acknowledged edge agent
```

## 断网验证

建议人工测试：

1. 正在 KOOK 中播放歌曲；
2. 临时阻断 Edge -> Cloud 443；
3. 确认 KOOK Bot 和当前播放继续；
4. Web 写操作返回 `EDGE_OFFLINE`；
5. 恢复网络；
6. Edge 自动重连；
7. `state.full` 恢复 Cloud Read Cache；
8. Web 再次控制播放。

## 当前 Cloud 扩容限制

Cloud 第一版是：

```text
1 Flask process
1 RelayHub event loop
1 in-memory Runtime Cache
```

因此不要用多个独立 Gunicorn worker。

需要 HA/水平扩容时，下一代应增加：

```text
Redis/NATS
共享 Agent connection ownership
Command correlation bus
Shared Read Model
```

在此之前，单实例 Cloud 配合 systemd/进程守护即可。
