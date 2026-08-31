# 部署、升级与验证

## 部署模型

选择 `windows/` 或 `Ubuntu/` 作为运行目录。每个实例有独立的 Python 环境、`.env`、`Cookie/`、`data/` 和日志；同一主机上的所有实例与本地音乐 API 共用系统 Node.js 和系统全局 npm 包。

仓库内不得存在 Node 可执行文件、Node API 源码或 `node_modules`。`run.py` 只接受项目目录外的系统 Node/npm。

从旧版本升级前先阅读 [安全审计修复与加固基线](security-hardening.md#兼容性与部署影响)。该基线包含 Bot 默认拒绝、`/cmd` 删除、资源 ID 冲突拒绝、媒体 URL 限制、凭据权限收紧和端口变化等兼容性影响。

默认端口：

| 服务 | 地址 |
|---|---|
| 网易云 API | `127.0.0.1:18474` |
| QQ 音乐 API | `127.0.0.1:18475` |
| Flask Web | `HOST:PORT`，默认 `0.0.0.0:18473` |

同一主机默认只运行一个完整实例。默认端口为连续的 18473–18475；若并行运行多个实例，必须为每个实例配置独立的 `PORT`、`MUSIC_API_PORT`、`QQ_MUSIC_API_PORT` 及对应的 `*_BASE` 地址。

## 公共依赖

- Python 3.10+。
- 系统 Node.js 20+ 与 npm。
- FFmpeg 和 ffprobe。
- KOOK Bot Token。

先确认系统运行时：

```bash
node --version
npm --version
npm root --global
```

全局安装项目要求的 Node API：

```bash
npm install --global NeteaseCloudMusicApi@4.25.0 @sansenjian/qq-music-api@2.3.1
```

安装结果必须位于项目目录之外。不要在 `windows/`、`Ubuntu/` 或仓库根目录运行不带 `--global` 的 npm 安装。

## Windows 部署

在 PowerShell 中执行：

```powershell
node --version
npm install --global NeteaseCloudMusicApi@4.25.0 @sansenjian/qq-music-api@2.3.1

cd windows
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python create_env.py
python run.py
```

Windows 优先使用 `windows/ffmpeg/bin/ffmpeg.exe` 和 `ffprobe.exe`。也可以通过 `FFMPEG_PATH`、`FFPROBE_PATH` 指向系统安装。

如果 PowerShell 禁止激活脚本，可直接调用：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe create_env.py
.\.venv\Scripts\python.exe run.py
```

## Ubuntu 部署

安装系统依赖；Node.js 必须由系统安装并达到 20+：

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg
node --version
sudo npm install --global NeteaseCloudMusicApi@4.25.0 @sansenjian/qq-music-api@2.3.1
```

部署应用：

```bash
cd Ubuntu
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 create_env.py
python3 run.py
```

如果 `node --version` 低于 20，先通过发行版或 Node.js 官方渠道升级系统 Node，不要把便携 Node 复制进项目目录。

## 配置

`create_env.py` 会在当前平台目录创建 `.env`，不回显 Bot Token，并生成随机 `SECRET_KEY`。也可以从 `.env.example` 手工配置。

| 变量 | 用途 | 默认或建议 |
|---|---|---|
| `BOT_TOKEN` | KOOK Bot Token | 必填 |
| `APP_VERSION` | `/版本信息` 展示的构建标识 | `desktop-ui-v2` |
| `FFMPEG_PATH` / `FFPROBE_PATH` | 媒体工具路径或 PATH 命令名 | 自动探测 |
| `MUSIC_API_PORT` | 网易云 API 监听端口 | `18474` |
| `QQ_MUSIC_API_PORT` | QQ 音乐 API 监听端口 | `18475` |
| `QQ_COOKIE_PATH` | QQ 兼容 Cookie | `./Cookie/qq_cookie.txt` |
| `QQ_CREDENTIAL_PATH` | QQ 刷新元数据 | `./Cookie/qq_credential.json` |
| `BILI_COOKIE_PATH` | Bilibili Cookie | `./Cookie/bili_cookie.txt` |
| `ALLOWGROUP` / `ALLOWCHANNEL` / `ALLOWUSER` | Bot 普通命令白名单，逗号分隔 | 全部留空时拒绝所有 Bot 指令 |
| `BOT_ALLOW_UNRESTRICTED` | 无白名单时允许所有 KOOK 用户控制 Bot | `false` |
| `MAX_REQUEST_BYTES` | Web 请求体上限（字节） | `1048576` |
| `MAX_PLAYLIST_IMPORT_TRACKS` | 单次歌单导入曲目上限 | `1000` |
| `MAX_QUEUE_TRACKS` | 单频道待播队列上限 | `2000` |
| `MAX_PLAYLIST_IMPORT_CONCURRENCY` | 同时执行的 Web 歌单导入数 | `2` |
| `SECRET_KEY` | Flask 密钥 | 必须为随机长字符串 |
| `HOST` | Web 监听地址 | 生产建议 `127.0.0.1` |
| `PORT` | Web 端口 | `18473` |
| `DEBUG` | Flask 调试 | 生产保持 `False` |

Web 控制面鉴权：

| 变量 | 用途 | 默认 |
|---|---|---:|
| `AUTH_DATABASE_PATH` | SQLite 控制面数据库 | `./data/kook_music.db` |
| `AUTH_SESSION_IDLE_SECONDS` | Session 空闲过期 | `86400` |
| `AUTH_SESSION_ABSOLUTE_SECONDS` | Session 绝对过期 | `604800` |
| `AUTH_LOGIN_WINDOW_SECONDS` | 登录失败统计窗口 | `600` |
| `AUTH_LOGIN_USER_FAILURES` | 同用户名窗口内失败阈值 | `5` |
| `AUTH_LOGIN_IP_FAILURES` | 同来源 IP 窗口内失败阈值 | `20` |
| `AUTH_COOKIE_SECURE` | Session/CSRF Cookie Secure | 本地 `false`；生产 HTTPS `true` |
| `AUTH_TRUST_PROXY_HEADERS` | 是否信任 `X-Forwarded-For` | 默认 `false` |

QQ 自动续期参数：

| 变量 | 默认值 |
|---|---|
| `QQ_CREDENTIAL_CHECK_INTERVAL` | `10800` 秒 |
| `QQ_CREDENTIAL_REFRESH_INTERVAL` | `64800` 秒 |
| `QQ_CREDENTIAL_REFRESH_WINDOW` | `86400` 秒 |

watchdog 可选参数：

| 变量 | 默认值 |
|---|---|
| `WATCHDOG_STARTUP_GRACE` | `180` 秒 |
| `WATCHDOG_INTERVAL` | `15` 秒 |
| `WATCHDOG_LOOP_TIMEOUT` | `90` 秒 |
| `WATCHDOG_GATEWAY_TIMEOUT` | `90` 秒 |
| `WATCHDOG_FAILURES` | `3` 次 |
| `WATCHDOG_REPAIR_COOLDOWN` | `60` 秒 |
| `WATCHDOG_RESTART_WINDOW` | `900` 秒 |
| `WATCHDOG_MAX_RESTARTS` | `3` 次 |

相对路径始终以当前平台目录为基准。

## 首次启动与管理员初始化

首次启动时，如果 `AUTH_DATABASE_PATH` 指向的数据库中 `users` 表为空，会创建 Bootstrap 管理员：

```text
username = gen
role = admin
must_change_password = 1
```

初始明文密码不写入 Git。可以通过 `INITIAL_ADMIN_PASSWORD` 注入部署 Secret；留空时，首次启动会在 `INITIAL_ADMIN_CREDENTIAL_PATH`（默认 `data/bootstrap-admin.json`）生成受限凭据文件。首次改密成功后该文件会自动删除。

首次登录流程：

1. 打开 `/login`；
2. 从部署 Secret 或受限凭据文件读取 Bootstrap 凭据并登录；
3. 系统强制跳转 `/change-password`；
4. 设置满足密码策略的新密码；
5. 创建第二个管理员作为恢复路径；
6. 再创建普通用户并按最小权限配置 Scope。

不要通过删除数据库来恢复管理员密码，因为这样会同时丢失用户、Scope、Session 和审计记录。

## 持久数据

必须视为持久数据：

```text
.env
Cookie/
data/
```

`data/kook_music.db` 保存 Web 用户、Session、Scope、登录失败记录和审计。数据库启用 WAL，因此运行中可能同时存在：

```text
kook_music.db
kook_music.db-wal
kook_music.db-shm
```

这些文件都不进入 Git。

## 迁移已有实例

停止源实例和目标实例后再迁移。

需要按存在情况复制：

```text
Cookie/cookie.txt
Cookie/qq_cookie.txt
Cookie/qq_credential.json
Cookie/bili_cookie.txt
data/kook_music.db
```

迁移规则：

1. 保持文件名和目标平台相对路径。
2. `.env` 中 Token、白名单、端口和 `AUTH_*` 逐项合并，不整文件无脑覆盖。
3. QQ 的 `qq_cookie.txt` 与 `qq_credential.json` 作为同一账号状态迁移。
4. SQLite 建议在实例停止后复制，避免遗漏 WAL 中尚未 checkpoint 的事务。
5. 若必须在线备份，使用 SQLite 一致性备份机制，不只复制主 `.db`。
6. 复制后限制文件权限：Linux 建议目录 `0700`、敏感文件 `0600`；Windows 仅授予运行服务账号访问 ACL。
7. 启动后检查登录、用户 Scope 和三个音乐平台状态。

如果不迁移 `data/`，目标实例会失去现有 Web 用户与授权，并可能重新触发 Bootstrap 管理员初始化。

## 启动与验证

在目标平台目录运行 `python run.py` 或 `python3 run.py`。日志应确认：

- 解析到项目外的系统 Node 20+；
- 从 `npm root --global` 找到两个固定包；
- 网易云 18474、QQ 18475 和 Flask 18473 端口就绪；
- FFmpeg/ffprobe 可用；
- Bot 进入运行状态；
- `data/` 可写，SQLite 可初始化/打开。

本地 Node 探针：

```bash
curl http://127.0.0.1:18474/login/status
curl http://127.0.0.1:18475/getSearchByKey/test
```

Web 鉴权探针：

```bash
curl -i http://127.0.0.1:18473/login
curl -i http://127.0.0.1:18473/api/system/status
```

预期：

- `/login` 返回登录页面；
- 未登录访问 `/api/system/status` 返回 `401`；
- 未登录访问 `/dashboard` 等页面跳转登录；
- Bootstrap 首次登录后被强制改密；
- 普通用户无法进入 `/account`、`/status`、`/settings`、`/users`；
- 普通用户只能看到 Scope 内的 Guild/Channel；
- Admin 能完成账号、状态和用户管理。

所有 POST/PUT/PATCH/DELETE 都要求 CSRF；用裸 `curl` 调管理写 API 时需要先建立 Session 并携带 CSRF Header。

随后在 Web 控制台验证服务器/频道读取、三平台搜索、加入频道、入队、暂停、继续、跳过和离开。HTTP 200 只代表请求到达路由；还要检查 JSON 中的 `success`、`code` 或错误字段。

## Ubuntu systemd

示例以项目位于 `/opt/kook-web-music/Ubuntu`、服务用户为 `kook`：

```ini
[Unit]
Description=KOOK Web Music
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=kook
WorkingDirectory=/opt/kook-web-music/Ubuntu
Environment=PATH=/opt/kook-web-music/Ubuntu/.venv/bin:/usr/local/bin:/usr/bin
ExecStart=/opt/kook-web-music/Ubuntu/.venv/bin/python run.py
Restart=on-failure
RestartSec=10
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
```

保存为 `/etc/systemd/system/kook-web-music.service` 后：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now kook-web-music
sudo systemctl status kook-web-music
journalctl -u kook-web-music -f
```

服务用户必须能读取系统 Node、全局 npm 包、项目目录、`.env` 和 `Cookie/`，并能写入 `data/` 与平台日志。

## 反向代理

推荐令 Flask 只监听 `127.0.0.1`，由 HTTPS 代理转发：

```nginx
server {
    listen 443 ssl;
    server_name music.example.com;

    location / {
        proxy_pass http://127.0.0.1:18473;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

生产 `.env`：

```env
HOST=127.0.0.1
AUTH_COOKIE_SECURE=true
DEBUG=False
```

只有确认代理会覆盖并清洗客户端 `X-Forwarded-For` 时，才设置：

```env
AUTH_TRUST_PROXY_HEADERS=true
```

不要直接暴露 18474/18475。完整边界见 [security.md](security.md)。

## 升级与回滚

升级：

1. 停止服务。
2. 备份 `.env`、`Cookie/`、`data/`。
3. 拉取目标分支并确认没有误覆盖本地凭据。
4. 重新安装有变化的 Python 依赖。
5. 按文档固定版本更新系统全局 Node 包。
6. 确认仓库内不存在 `node_modules` 或便携 Node。
7. 阅读目标版本是否包含 SQLite Schema 变化。
8. 启动并执行登录、Scope、账号和实际播放检查。

回滚时，除代码和 Python/Node 依赖外，还必须确认目标提交是否兼容当前 SQLite Schema。若涉及不兼容迁移，恢复升级前数据库备份，而不是让旧代码直接打开未知新 Schema。

## 端口冲突

启动前检查 18473、18474、18475。若端口由旧的本项目实例占用，先正常停止该实例；无法停止时只终止已确认属于该实例的 PID。不要按进程名批量结束系统上的所有 Node、Python 或 FFmpeg 进程。
