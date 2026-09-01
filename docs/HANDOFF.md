# 工程 Handoff

当前开发分支：`feature/cloud-edge-control-plane`

基线来源：`refactor/desktop-ui-v2` @ `076ad3d0e3f7461efa6686a0aaa5a12621b650d9`。

> 安全约束：本文以及仓库其他文档不得记录真实 Bot Token、Agent Token、Cookie、Credential、Session/CSRF、管理员明文密码或签名媒体 URL。

## 当前架构

当前目标已经从单机 v2 扩展为“双控制面 + 单 Edge Runtime”模式：

```text
Cloud Web :28443 ---------\
                            -> Edge Runtime -> KOOK
Cloud WSS :28470-28479 ---/
Local Edge WebUI ---------/
KOOK Bot ----------------/
```

Cloud 负责公网 Web 用户、Session/RBAC/Scope、审计、状态缓存和 Relay。Edge 保留完整 v2 本地 WebUI、KOOK Bot、PlayHandler、FFmpeg、Node API 与音乐 Credential。

## 已收口的最终需求

- Cloud 公网 Web 不使用标准 443，默认改为 `28443/tcp`。
- 公网正式 Web 地址为 `https://<cloud-domain>:28443/`。
- 公网 Web 与 WSS 使用不同的非标准端口。
- 默认 WSS 公网端口池 `28470-28479`。
- 任意时刻一个 Edge 只维持一条 Active WSS。
- Active Port 发生网络型失败时在池内自动故障转移。
- 上次成功端口作为 `preferred_port` 优先复用，其余候选随机化。
- 全池失败后指数退避 + jitter。
- `AUTH_FAILED`、TLS 证书错误、协议不匹配不进行无意义的全池轮询。
- Edge 本地 WebUI 独立于 Cloud，Cloud/WSS 失败不影响本地使用、Bot、当前播放或自动下一首。
- Edge `/settings` 可配置 Cloud host、端口池、path、TLS、Agent ID/名称和 Token。
- 修改远程配置只重连 Agent，不重启 Bot/播放核心。
- Agent Token 独立安全保存，API 只返回是否已配置，不回显原值。
- 旧 `EDGE_RELAY_URL` 保留首次迁移兼容。
- Handoff 只维护在 `docs/`，不写根 README。

## 关键实现

```text
cloud/run.py                    Cloud 入口
cloud/app.py                    Cloud Web/Auth/Edge 状态接口
cloud/relay.py                  单内部 RelayHub
cloud/Caddyfile.example         28443 Web + 28470-28479 WSS ingress

edge/run.py                     Edge 完整本地 WebUI + Runtime 入口
edge/agent.py                   EdgeAgentSupervisor / PortPool Failover
edge/config_store.py            动态远程配置 SQLite
edge/secret_store.py            Agent Token Secret Store
edge/management.py              本地 Admin 配置/状态 API
edge/templates/settings.html    Edge 专属 v2 设置页
edge/static/edge-settings.js    本地远程节点配置交互
edge/local_control.py           Relay 到现有 loopback API 的兼容桥

shared/relay_protocol.py        唯一远程业务 Action 白名单
```

## 数据归属

Cloud：

```text
cloud/data/kook_music.db
```

保存 Web user/session/scope/audit、Agent registry 与 Guild 路由副本。

Edge：

```text
<platform>/data/kook_music.db
<platform>/data/edge_config.db
<platform>/data/edge-agent.secret
<platform>/Cookie/
```

Edge 是 Queue、Now Playing、Credential 与媒体执行状态的权威源。

## 公网与内部网络边界

公网正式业务端口：

```text
28443/tcp         Cloud HTTPS Web
28470-28479/tcp   Edge WSS ingress pool
```

如果使用 Caddy 自动申请/续期公网 TLS 证书，推荐同时允许：

```text
80/tcp            ACME HTTP-01 challenge
```

`80/tcp` 只用于证书验证，不是正式 Web 业务入口。项目不再要求 `443/tcp` 作为 Cloud Web 访问端口。

Cloud 内部：

```text
127.0.0.1:18473  Flask
127.0.0.1:18476  RelayHub
```

Edge 默认：

```text
127.0.0.1:18473  Local WebUI
127.0.0.1:18474  NetEase API
127.0.0.1:18475  QQ API
```

不要公网开放 `18473-18476`。Edge 只主动建立出站 WSS，不需要公网 IP 或入站映射。

## 本地 WebUI

`edge/run.py` 继续复用现有 Windows/Ubuntu v2 页面和业务，因此本地保留：

- Dashboard/播放
- 音乐库
- 网易/QQ/Bilibili 账号
- 系统状态
- 用户管理
- 桌面/移动布局
- 深色/浅色/跟随系统
- Edge 专属远程节点设置

默认 `EDGE_LOCAL_WEB_HOST=127.0.0.1`。需要 LAN 访问时可显式改为 `0.0.0.0`，但 Auth/CSRF 不关闭。

## Edge 动态配置

`.env` 只作为首次 bootstrap。运行后的动态配置以 `edge_config.db` 为准；Agent Token 单独保存为 `edge-agent.secret`。

UI 支持：

```text
启用/停用远程控制
Cloud Host
WSS Port Start/End
WSS Path
TLS Verify
Agent ID / Name
更新 Agent Token
检测端口池
保存并重新连接
立即重连
```

端口池检测使用未认证 HTTPS 请求验证 TCP/TLS/HTTP ingress 可达性，避免用第二条同 Agent 的认证 WSS 把正式连接挤下线。

## 故障模型

Cloud/WSS 故障：本地 WebUI、KOOK Bot、正在播放、队列推进、FFmpeg 和音乐平台继续工作；只有公网远程 UI 控制不可用或显示旧缓存。

Edge 故障：Cloud Web/Auth 仍可用，但运行时写操作返回 Edge Offline。

Cloud 不保存并延迟执行播放命令。

## 安全边界

远程协议不得增加 shell、exec、任意 subprocess、任意 URL proxy 或任意文件读写。Agent Token 不进入 URL/query/log，Cloud Registry 只保存 Hash，Edge Secret 不通过读取 API 回显。

## 当前质检状态

按项目所有者要求，本轮实现：

- 不创建 PR；
- 不创建、修改或主动运行 CI；
- 不声明已经完成生产质检。

后续由其他 Agent 或人工至少覆盖：

1. Windows/Ubuntu `edge/run.py` 启动与 Local WebUI 登录。
2. 本地 v2 播放、音乐库、三平台账号与用户管理。
3. Cloud `28443` Web 与 `28470-28479` WSS 分离。
4. `https://<domain>:28443/` 公网 HTTPS 访问与证书续期。
5. Active Port 被防火墙阻断后的自动切换。
6. 全池阻断时 Bot/播放/Local WebUI 持续工作。
7. Token 错误停止无意义端口轮询。
8. 本地设置修改 Cloud/端口池后播放不中断。
9. Cloud 与 Local 双控制面操作同一 Queue。
10. Edge 重连后 `state.full` 恢复 Cloud Read Cache。
11. Secret、日志、数据库、WSS payload 的敏感信息审计。

## 推荐阅读顺序

1. `docs/HANDOFF.md`
2. `docs/cloud-edge-architecture.md`
3. `docs/cloud-edge-deployment.md`
4. `shared/relay_protocol.py`
5. `edge/config_store.py`
6. `edge/secret_store.py`
7. `edge/agent.py`
8. `edge/management.py`
9. `cloud/relay.py`
10. `cloud/runtime_proxy.py`
