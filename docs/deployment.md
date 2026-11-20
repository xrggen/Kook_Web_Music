# 单机部署与升级

先按 [Windows](../windows/README.md) 或 [Ubuntu](../Ubuntu/README.md) 完成安装。本手册补充运行配置、托管与升级。远程控制见 [Cloud / Edge 部署](cloud-edge-deployment.md)。

## 配置

每个播放实例使用对应平台目录的 `.env`、`Cookie/` 和 `data/`。平台运行脚本以该目录为工作目录解析相对路径。所有 Node API 使用系统 Node.js 20+ 与系统全局 npm 包，检查安装位置时以服务运行账号的 `npm root --global` 为准。

| 配置 | 用途 |
| --- | --- |
| `BOT_TOKEN` | KOOK 机器人凭据 |
| `ALLOWGROUP`、`ALLOWCHANNEL`、`ALLOWUSER` | KOOK 指令白名单。每项使用逗号分隔的 ID。全部为空时默认拒绝指令 |
| `HOST`、`PORT` | Flask 监听。建议本机设 `127.0.0.1:18473` |
| `MUSIC_API_PORT`、`QQ_MUSIC_API_PORT` | 网易云和 QQ 本地端口，默认 `18474`、`18475` |
| `FFMPEG_PATH`、`FFPROBE_PATH` | 覆盖媒体工具查找 |
| `SECRET_KEY` | 建议设置随机、稳定的 Flask 密钥 |
| `AUTH_DATABASE_PATH` | 控制台数据库，默认 `data/kook_music.db` |
| `INITIAL_ADMIN_USERNAME`、`INITIAL_ADMIN_PASSWORD` | 首次初始化的用户名与可选密码 |
| `AUTH_COOKIE_SECURE`、`AUTH_TRUST_PROXY_HEADERS` | 本地 HTTP 通常均为 `false`，受信 TLS 反代部署按 [鉴权说明](authentication.md#公网部署要求)设置 |
| `MAX_REQUEST_BYTES`、`MAX_PLAYLIST_IMPORT_TRACKS`、`MAX_QUEUE_TRACKS` | 请求及队列上限 |

更多变量见平台的 `.env.example`、[鉴权配置](authentication.md#环境变量)和 [看门狗](operations.md#watchdog)。如需同机多实例，分别配置控制台与两个 Node 端口及对应 API 地址，隔离数据库、凭据和进程。

### Watchdog 配置

| 变量 | 默认值 |
| --- | --- |
| `WATCHDOG_STARTUP_GRACE`、`WATCHDOG_INTERVAL` | 180、15 秒 |
| `WATCHDOG_LOOP_TIMEOUT`、`WATCHDOG_GATEWAY_TIMEOUT` | 90、90 秒 |
| `WATCHDOG_FAILURES`、`WATCHDOG_REPAIR_COOLDOWN` | 3 次、60 秒 |
| `WATCHDOG_RESTART_WINDOW`、`WATCHDOG_MAX_RESTARTS` | 900 秒、3 次 |

## systemd

示例路径和用户需换成实际安装位置。先以同一账号确认 Python、Node 和 npm 全局包能被找到。若配置的是远程 Edge，把 `ExecStart` 的脚本换成 `edge/run.py`。

```ini
[Unit]
Description=KOOK Web Music
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=kook
WorkingDirectory=/opt/kook-web-music
Environment=PATH=/usr/local/bin:/usr/bin:/bin
ExecStart=/home/kook/.venvs/kook-web-music/bin/python Ubuntu/run.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

将单元存到 `/etc/systemd/system/kook-web-music.service`，然后执行 `sudo systemctl daemon-reload` 和 `sudo systemctl enable --now kook-web-music`。服务用户须能读取配置和依赖，并能写入本实例的数据目录。

## 启动与验证

- `GET /healthz` 应返回 200。未登录访问受保护的 API 应返回 401。
- 通过 KOOK `/ping` 验证指令和白名单，登录控制台后选择语音频道并播放测试曲目。
- 从同一机器检查 `http://127.0.0.1:18474/` 和 `http://127.0.0.1:18475/` 的 HTTP 响应。本地 API 响应正常只代表该进程可用，平台搜索和播放还依赖上游服务。
- 公网访问使用带 HTTPS 的受信反向代理。音乐 API 和内部 Relay 留在回环接口。

## 迁移已有实例

先停对应实例并确认进程退出。按 [运维备份说明](operations.md#备份与恢复)处理控制面数据库及允许迁移的配置和登录态。Web 用户、Scope、Session 和微信关联保存在数据库里，音乐平台登录态保存在平台目录的 `Cookie/`。迁移后在同一部署角色启动，再验证登录、指令和播放。

## 升级与回滚

先验证两平台同步和相关测试，再保留当前运行版本及一致性备份。更新后检查 Web、Bot、平台 API 和播放。已经升级 SQLite Schema 时，先确认回滚程序支持现有版本，或由运维团队按既有恢复流程处理数据库。Windows / Ubuntu 单机与 Edge 的运行入口应和升级前的部署角色一致。

发布验收后执行 [发布收尾](release-workflow.md)。
