# Cloud / Edge 部署

在公网服务器运行 Cloud，在常开播放机运行 Edge。Edge 主动建立出站 WSS。本地 Web、Bot、Node API 和 FFmpeg 都在播放机运行。

## 端口

| 节点 | 入口 | 用途 |
| --- | --- | --- |
| Cloud 公网 | TCP `28443` | 浏览器与小程序的 HTTPS Web/API |
| Cloud 公网 | TCP `28470–28479` | Edge WSS 端口池，路径 `/edge/v1/connect` |
| Cloud 回环 | `127.0.0.1:18473`、`127.0.0.1:18476` | Flask 与 RelayHub |
| Edge 回环 | `127.0.0.1:18473–18475` | 本地 Web、网易云 API、QQ API |

公网服务器需有域名和可信 TLS 证书。使用 Caddy HTTP-01 时，按证书申请方案放行 TCP 80。Cloud 和 Edge 的内部端口留在回环接口，Edge 无需配置公网入站。

## 启动 Cloud

在服务器以专用服务账号准备仓库和 Python 3.10+。从仓库根目录操作。

```bash
python3 -m venv ~/.venvs/kook-cloud
source ~/.venvs/kook-cloud/bin/activate
python -m pip install -r cloud/requirements.txt
test -e cloud/.env || (umask 077; cp cloud/.env.example cloud/.env)
```

在 `cloud/.env` 设置随机的 `SECRET_KEY` 和 `EDGE_AGENT_TOKEN`。`EDGE_AGENT_ID` 的默认值为 `edge-main`，须与 Edge 一致。保留 `AUTH_COOKIE_SECURE=true`，仅当 Web 入口是受信反代且后端保持回环监听时使用 `AUTH_TRUST_PROXY_HEADERS=true`。若启用小程序微信绑定，另外设置该小程序的 `WECHAT_MINIAPP_APP_ID` 和 `WECHAT_MINIAPP_APP_SECRET`。运行后打开另一个终端检查回环端口。

```bash
python cloud/run.py
# 另开终端
curl -fsS http://127.0.0.1:18473/healthz
```

部署 [Caddy 示例](../cloud/Caddyfile.example)前替换所有 `music.example.com`，并按实际环境校验证书和配置。HTTPS `28443` 转发到 Cloud Flask，WSS 端口池仅在指定路径转发到 RelayHub。用 `caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile` 检查配置，再由服务管理器加载。

Cloud 可用 [systemd 示例](deployment.md#systemd)托管，把启动脚本、服务名和解释器改为 Cloud 对应值。Cloud 的 Relay 与状态缓存保存在进程内，先使用单进程部署。

## 启动 Edge

1. 按 [Windows](../windows/README.md) 或 [Ubuntu](../Ubuntu/README.md) 准备播放依赖，配置平台目录的 Bot Token 与白名单。已有单机进程时先停它。
2. 按 [Edge 配置模板](../edge/.env.example)创建 `edge/.env`。设置 `EDGE_RELAY_ENABLED=true`、Cloud 主机名、端口池、`EDGE_AGENT_ID` 和与 Cloud 一致的 `EDGE_AGENT_TOKEN`。公网 TLS 校验保持开启。
3. 从仓库根目录运行 `python edge/run.py`，Windows CMD 可运行 `start-edge.cmd`。Edge 同时提供本地页面和播放服务。
4. 从本地 Web 的设置页查看远程连接状态。Edge 第一次启动从环境配置初始化，后续远程连接设置以 Edge 本地保存的配置为准。在设置页保存修改即可让 Agent 重连。

## 验收与升级

- 访问 `https://<cloud-domain>:28443/healthz`，确认 `role=cloud`、`edge_connected=true`。首次从公网控制台登录后按提示改密。Cloud 与 Edge 各自管理 Web 账号和会话。
- 在 Cloud 选择目标频道并发起播放，核对 Edge 本地页面的队列与 KOOK 实际音频。用 `/ping` 检查 Bot 指令。
- 连接失败时先核对配置中的 Agent ID、Token、域名、WSS 路径与证书。若只有部分端口异常，在 Edge 设置页检测端口池。Cloud 离线时，Edge 可继续本地管理和播放。
- 按 [运维](operations.md)与 [发布流程](release-workflow.md)记录当前版本、备份和回滚能力。仅在运行组件变更需要重启时切换对应单元。完整重启播放端会清空内存队列。
