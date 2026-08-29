# 部署、升级与验证

## 部署模型

选择 `windows/` 或 `Ubuntu/` 作为运行目录。每个实例有独立的 Python 环境、`.env`、`Cookie/` 和日志；同一主机上的所有实例与本地音乐 API 共用系统 Node.js 和系统全局 npm 包。

仓库内不得存在 Node 可执行文件、Node API 源码或 `node_modules`。`run.py` 只接受项目目录外的系统 Node/npm。

默认端口：

| 服务 | 地址 |
|---|---|
| 网易云 API | `127.0.0.1:3000` |
| QQ 音乐 API | `127.0.0.1:3200` |
| Flask Web | `HOST:PORT`，默认 `0.0.0.0:5000` |

同一主机默认只运行一个完整实例。即使为 Web 配置不同端口，`run.py` 仍会固定启动 3000/3200；第二个实例会发生冲突。确需并行实例时，应使用独立主机/容器，或先完成 Node API 端口和启动策略的代码级隔离。

## 公共依赖

- Python 3.8+。
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
| `MUSIC_API_BASE` | 网易云 API 地址或本地失败后的回退地址 | `http://localhost:3000` |
| `QQ_MUSIC_API_BASE` | QQ 音乐 API 地址 | `http://localhost:3200` |
| `QQ_COOKIE_PATH` | QQ 兼容 Cookie | `./Cookie/qq_cookie.txt` |
| `QQ_CREDENTIAL_PATH` | QQ 刷新元数据 | `./Cookie/qq_credential.json` |
| `BILI_COOKIE_PATH` | Bilibili Cookie | `./Cookie/bili_cookie.txt` |
| `ALLOWGROUP` / `ALLOWCHANNEL` / `ALLOWUSER` | 普通命令白名单，逗号分隔 | 留空不限制该维度 |
| `CMD_ALLOWUSER` | `/cmd` 独立用户白名单 | 留空即无人可用 |
| `SECRET_KEY` | Flask session 密钥 | 必须为随机长字符串 |
| `HOST` | Web 监听地址 | 本机建议 `127.0.0.1` |
| `PORT` | Web 端口 | `5000` |
| `DEBUG` | Flask 调试 | 生产保持 `False` |

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

## 迁移已有登录态

先停止源实例和目标实例，再按存在情况复制以下文件：

```text
Cookie/cookie.txt
Cookie/qq_cookie.txt
Cookie/qq_credential.json
Cookie/bili_cookie.txt
```

同步规则：

1. 保持文件名和目标平台的 `Cookie/` 相对路径。
2. 不复制日志、二维码图片、`.env`、`node_modules` 或全局 npm 包内配置。
3. `.env` 中的 Token、白名单和端口逐项合并，不整文件覆盖。
4. QQ 的 `qq_cookie.txt` 与 `qq_credential.json` 应作为同一账号状态一起迁移。
5. 复制后限制文件权限，并在账号页面检查三个平台状态。

## 启动与验证

在目标平台目录运行 `python run.py` 或 `python3 run.py`。日志应确认：

- 解析到项目外的系统 Node 20+。
- 从 `npm root --global` 找到两个固定包。
- 网易云 3000、QQ 3200 和 Flask 端口就绪。
- FFmpeg/ffprobe 可用。
- Bot 进入运行状态。

基础探针：

```bash
curl http://127.0.0.1:3000/login/status
curl http://127.0.0.1:3200/getSearchByKey/test
curl http://127.0.0.1:5000/
curl http://127.0.0.1:5000/api/system/status
curl http://127.0.0.1:5000/api/debug
```

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

服务用户必须能读取系统 Node、全局 npm 包、项目目录、`.env` 和 `Cookie/`，并能写入平台日志。

## 反向代理

推荐令 Flask 只监听 `127.0.0.1`，由带 TLS 和认证的代理转发：

```nginx
server {
    listen 443 ssl;
    server_name music.example.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

证书和认证配置取决于部署环境。不要直接暴露 3000/3200；完整边界见 [安全文档](security.md)。

## 升级与回滚

升级：

1. 停止服务，备份 `.env` 与 `Cookie/`。
2. 拉取目标分支并确认工作区没有误覆盖的本地凭据。
3. 重新安装有变化的 Python 依赖。
4. 按文档固定版本更新系统全局 Node 包。
5. 确认仓库内不存在 `node_modules` 或便携 Node。
6. 启动并执行全部基础探针和实际播放检查。

回滚时切回已知可用提交，恢复与该提交兼容的 Python 依赖和全局 Node 包版本，再恢复备份的配置与凭据。不要把 Cookie 写回全局 npm 包目录。

## 端口冲突

启动前检查 3000、3200、5000。若端口由旧的本项目实例占用，先正常停止该实例；无法停止时只终止已确认属于该实例的 PID。不要按进程名批量结束系统上的所有 Node、Python 或 FFmpeg 进程。
