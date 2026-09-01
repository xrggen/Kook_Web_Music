# Cloud / Edge 部署

## 端口规划

| 服务 | 默认 |
|---|---|
| Cloud Web HTTPS | `443/tcp` |
| Cloud Public WSS Pool | `28470-28479/tcp` |
| Cloud Flask | `127.0.0.1:18473` |
| Cloud Relay backend | `127.0.0.1:18476` |
| Edge Local WebUI | `127.0.0.1:18473` |
| Edge 网易 API | `127.0.0.1:18474` |
| Edge QQ API | `127.0.0.1:18475` |

公网防火墙只需允许 443 与 WSS 端口池。18473/18476 不应直接暴露公网。

## Cloud

复制：

```bash
cp cloud/.env.example cloud/.env
```

至少配置：

```env
SECRET_KEY=<random>
EDGE_AGENT_TOKEN=<same secret as Edge>
EDGE_PUBLIC_WSS_PORT_START=28470
EDGE_PUBLIC_WSS_PORT_END=28479
```

启动：

```bash
python cloud/run.py
```

Cloud Flask 和 Relay 默认都只监听回环。反向代理配置参考 `cloud/Caddyfile.example`。

WSS 证书必须覆盖 Edge 配置使用的 Cloud hostname。十个端口使用相同证书和 `/edge/v1/connect` 路径。

## Edge

平台 `.env` 继续保存 BOT_TOKEN、FFmpeg、Node API、音乐平台相关配置。

复制：

```bash
cp edge/.env.example edge/.env
```

Bootstrap 示例：

```env
EDGE_LOCAL_WEB_HOST=127.0.0.1
EDGE_LOCAL_PORT=18473
EDGE_RELAY_ENABLED=true
EDGE_RELAY_HOST=music.example.com
EDGE_RELAY_PORT_START=28470
EDGE_RELAY_PORT_END=28479
EDGE_RELAY_PATH=/edge/v1/connect
EDGE_RELAY_TLS_VERIFY=true
EDGE_AGENT_ID=edge-main
EDGE_AGENT_NAME=Primary Edge
EDGE_AGENT_TOKEN=<same secret as Cloud>
```

启动：

```bash
python edge/run.py
```

Edge 启动后可直接访问本地 `/settings` 修改 Cloud 主机、端口池、Agent ID/名称、TLS 和 Token。保存会触发 WSS reload，不会重启 KOOK Bot/FFmpeg/播放。

## 本地 WebUI

默认仅本机：

```env
EDGE_LOCAL_WEB_HOST=127.0.0.1
```

需要 LAN 访问：

```env
EDGE_LOCAL_WEB_HOST=0.0.0.0
```

此时必须同时配置主机防火墙，不要直接映射到公网。Web Auth、Session 与 CSRF 始终保持启用。

## 动态持久化

运行后生成：

```text
<platform>/data/edge_config.db
<platform>/data/edge-agent.secret
```

`data/` 与 `*.secret` 已被 Git 忽略。Secret 在 POSIX 上以 0600 原子写入。

配置优先级：

```text
EdgeConfigStore / SecretStore
> 首次 bootstrap 的 edge/.env
> 内置默认值
```

`.env` 后续修改不会自动覆盖已经持久化的动态配置；应使用本地 WebUI 修改，或在停机后明确维护 Edge 配置库。

## 旧版迁移

仍支持：

```env
EDGE_RELAY_URL=wss://host:28476/edge/v1/connect
```

当 `EDGE_RELAY_HOST` 未设置时首次解析旧 URL，并创建 `port_start=port_end=28476` 的单端口配置。之后可以在本地 UI 扩为 `28470-28479`。

## 故障验证

建议人工覆盖：

1. 当前端口可用，Edge 正常连接。
2. 防火墙屏蔽 Active Port，Edge 自动切到池内其他端口。
3. 全池不可用，KOOK Bot/本地 WebUI/当前播放仍工作。
4. 恢复任一端口，Agent 自动重连并发送 `state.full`。
5. Token 错误时进入 `AUTH_FAILED`，不轮询全部端口。
6. 修改 Cloud host/端口池并“保存并重新连接”，播放不中断。
7. Cloud Web 操作与 Local Web 操作看到同一 Queue。

## 当前 Cloud 扩容限制

Cloud 第一版仍是单 Flask process + 单 RelayHub + 内存 Read Cache，不应直接配置多个独立 Gunicorn worker。需要 HA 时再引入 Redis/NATS、Agent connection ownership 与共享 Read Model。
