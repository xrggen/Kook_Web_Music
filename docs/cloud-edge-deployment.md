# Cloud / Edge 零基础部署手册

> 本文面向**没有 Linux、反向代理、WebSocket、Python、Node.js 或服务器运维经验**的部署人员。
>
> 请严格按顺序操作。每一节都包含“做什么”“为什么”“怎么确认成功”。如果某一步验证没有通过，请先解决该步骤，不要继续向后执行。

---

## 1. 先理解你要部署什么

本项目的正式 Cloud / Edge 模式由两台逻辑机器组成。

```text
公网用户
   │
   │ HTTPS 443
   ▼
Cloud 公网服务器
   ├─ Web UI / 登录 / 用户权限
   ├─ Flask：127.0.0.1:18473
   └─ WSS Relay：127.0.0.1:18476
             ▲
             │ 公网 TCP 28470-28479 中自动选择一个端口
             │ WSS，由 Edge 主动连接
             │
Edge 内网执行机
   ├─ 本地 WebUI：18473
   ├─ KOOK Bot
   ├─ 网易云 API：18474
   ├─ QQ API：18475
   ├─ Bilibili
   ├─ PlayHandler / FFmpeg
   └─ 音乐平台 Cookie / Credential
```

两边职责不同：

- **Cloud**：给公网用户提供网页、登录、权限、远程控制入口。
- **Edge**：真正执行 KOOK Bot、搜索、播放、FFmpeg、平台登录等动作。
- Edge **不需要公网 IP**，只需要能访问互联网。
- Edge 主动连接 Cloud，所以不需要在 Edge 路由器上做端口映射。
- Cloud 断线时，Edge 本地 WebUI、KOOK Bot 和已经运行的播放仍然可以继续工作。

### 1.1 默认端口

| 用途 | 默认地址/端口 | 是否对公网开放 |
|---|---|---|
| Cloud Web | `443/tcp` | 是 |
| Cloud WSS 端口池 | `28470-28479/tcp` | 是 |
| Cloud Flask | `127.0.0.1:18473` | 否 |
| Cloud Relay backend | `127.0.0.1:18476` | 否 |
| Edge 本地 WebUI | `127.0.0.1:18473` | 默认否 |
| Edge 网易云 API | `127.0.0.1:18474` | 否 |
| Edge QQ API | `127.0.0.1:18475` | 否 |

**非常重要：** Cloud 的 `18473`、`18476` 不要加入公网安全组；Edge 的 `18474`、`18475` 也不要映射到公网。

---

# 第一部分：准备资料

## 2. 部署前需要准备的东西

请先准备好下面的信息。

### 2.1 一台公网 Cloud 服务器

推荐：

```text
操作系统：Ubuntu 22.04 / 24.04 64 位
CPU：2 核或以上
内存：2 GB 或以上
磁盘：20 GB 或以上
公网 IPv4：需要
```

Cloud 不需要 GPU，不需要 FFmpeg，也不需要 Node.js。

### 2.2 一个域名

示例本文统一使用：

```text
music.example.com
```

实际部署时必须替换成你自己的真实域名。

### 2.3 一台 Edge 执行机

支持：

```text
Windows 10 / 11 / Server
或
Ubuntu Linux
```

Edge 必须：

- 能访问互联网；
- 能连接 KOOK；
- 能访问网易云、QQ、Bilibili；
- 能主动访问 Cloud 的 `28470-28479/tcp`；
- 不要求公网 IP。

### 2.4 KOOK Bot Token

Bot Token **只放 Edge**。

不要把 Bot Token 放到：

```text
Cloud
GitHub
聊天截图
部署文档
日志
```

### 2.5 记事本

部署过程中会生成两类秘密：

1. `SECRET_KEY`：Cloud Flask 使用；
2. `EDGE_AGENT_TOKEN`：Cloud 和 Edge 相互认证使用。

请暂时保存在安全的密码管理器中，不要发到群聊。

---

# 第二部分：部署 Cloud 公网服务器

## 3. 登录 Cloud 服务器

Windows 电脑可以使用 PowerShell：

```powershell
ssh 用户名@服务器公网IP
```

例如：

```powershell
ssh root@203.0.113.10
```

如果云厂商要求使用普通用户，例如 Ubuntu：

```powershell
ssh ubuntu@203.0.113.10
```

登录成功后，你会看到类似：

```text
ubuntu@cloud:~$
```

后面的 Linux 命令都在这个 SSH 窗口执行。

---

## 4. 更新 Ubuntu

执行：

```bash
sudo apt update
sudo apt upgrade -y
```

然后安装基础工具：

```bash
sudo apt install -y git python3 python3-venv python3-pip curl ca-certificates caddy
```

检查：

```bash
git --version
python3 --version
caddy version
```

预期：

- Git 能显示版本；
- Python 至少为 `3.10`；
- Caddy 能显示版本号。

如果 `python3 --version` 小于 3.10，请先升级系统 Python，再继续。

---

## 5. 下载项目代码

推荐安装在：

```text
/opt/Kook_Web_Music
```

执行：

```bash
cd /opt
sudo git clone --branch feature/cloud-edge-control-plane https://github.com/xrggen/Kook_Web_Music.git
sudo chown -R $USER:$USER /opt/Kook_Web_Music
cd /opt/Kook_Web_Music
```

确认当前分支：

```bash
git branch --show-current
```

必须看到：

```text
feature/cloud-edge-control-plane
```

如果不是这个分支，不要继续。

---

## 6. 创建 Cloud Python 环境

进入项目根目录：

```bash
cd /opt/Kook_Web_Music
```

创建 Python 虚拟环境：

```bash
python3 -m venv cloud/.venv
```

升级 pip：

```bash
cloud/.venv/bin/python -m pip install --upgrade pip
```

安装 Cloud 依赖：

```bash
cloud/.venv/bin/python -m pip install -r cloud/requirements.txt
```

检查：

```bash
cloud/.venv/bin/python -c "import flask,aiohttp; print('Cloud Python OK')"
```

成功应显示：

```text
Cloud Python OK
```

---

## 7. 配置域名 DNS

进入你的域名服务商控制台，例如阿里云、腾讯云、Cloudflare 等。

创建一条 **A 记录**：

```text
主机记录：music
记录类型：A
记录值：Cloud 服务器公网 IPv4
```

如果你的完整域名就是别的名字，以实际域名为准。

等待 DNS 生效后，在自己的电脑执行：

```powershell
nslookup music.example.com
```

应该能看到 Cloud 的公网 IP。

如果返回的是错误 IP，请不要继续配置 HTTPS。

### IPv6 注意

如果服务器没有正确配置公网 IPv6，请不要随意添加 `AAAA` 记录。错误的 AAAA 记录可能导致部分用户优先走 IPv6 后无法访问。

---

## 8. 配置 Cloud 防火墙 / 安全组

这里通常有两层：

```text
云厂商安全组
+
Ubuntu 本机防火墙
```

两层都必须允许需要的端口。

### 8.1 云厂商安全组

在云服务器控制台增加入站规则：

```text
TCP 22             SSH，管理服务器
TCP 80             HTTP / HTTPS 证书申请和跳转
TCP 443            Web HTTPS
TCP 28470-28479    Edge WSS 端口池
```

**不要开放：**

```text
18473
18474
18475
18476
```

### 8.2 Ubuntu UFW

先检查状态：

```bash
sudo ufw status
```

如果 UFW 尚未启用，先确保 SSH 不会被锁死。

如果 SSH 是标准 22：

```bash
sudo ufw allow 22/tcp
```

再添加：

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 28470:28479/tcp
```

然后：

```bash
sudo ufw enable
sudo ufw status numbered
```

必须确认 SSH 端口仍然是 Allow，否则不要退出当前 SSH 会话。

---

## 9. 生成 Cloud SECRET_KEY

进入项目目录：

```bash
cd /opt/Kook_Web_Music
```

生成：

```bash
cloud/.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))"
```

会得到类似一长串随机字符。

复制到密码管理器，名称可以记为：

```text
KOOK Music Cloud SECRET_KEY
```

不要使用本文中的任何示例字符串作为真实 Secret。

---

## 10. 生成 Edge Agent Token

再次执行：

```bash
cloud/.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))"
```

这一次得到的是另外一个随机值。

保存为：

```text
KOOK Music EDGE_AGENT_TOKEN
```

这个 Token 后面需要：

```text
Cloud 保存一份
Edge 保存同一个值
```

两边必须完全一致。

---

## 11. 创建 Cloud 配置文件

执行：

```bash
cd /opt/Kook_Web_Music
cp cloud/.env.example cloud/.env
nano cloud/.env
```

建议初次部署至少确认以下内容：

```env
HOST=127.0.0.1
PORT=18473

EDGE_RELAY_HOST=127.0.0.1
EDGE_RELAY_PORT=18476
EDGE_PUBLIC_WSS_PORT_START=28470
EDGE_PUBLIC_WSS_PORT_END=28479

EDGE_AGENT_ID=edge-main
EDGE_AGENT_NAME=Primary Edge
EDGE_AGENT_TOKEN=这里填写第10步生成的AgentToken

AUTH_DATABASE_PATH=./data/kook_music.db
INITIAL_ADMIN_USERNAME=gen
INITIAL_ADMIN_PASSWORD=
INITIAL_ADMIN_CREDENTIAL_PATH=./data/bootstrap-admin.json

AUTH_COOKIE_SECURE=true
AUTH_TRUST_PROXY_HEADERS=true
SECRET_KEY=这里填写第9步生成的SECRET_KEY

CLOUD_STATE_CACHE_MAX_AGE=20
MAX_REQUEST_BYTES=1048576
LOG_LEVEL=INFO
```

保存 nano：

```text
Ctrl + O
回车
Ctrl + X
```

限制权限：

```bash
chmod 600 cloud/.env
```

### 11.1 为什么 `INITIAL_ADMIN_PASSWORD` 建议留空

留空后，首次初始化 Cloud 用户数据库时程序会自动生成随机 Bootstrap 管理员密码，并写入：

```text
cloud/data/bootstrap-admin.json
```

第一次登录修改密码后，该临时文件会被清理。

这比在 `.env` 中长期保存管理员密码更安全。

---

## 12. 第一次手动启动 Cloud

现在先不要设置 systemd，先手工运行一次确认没有错误。

执行：

```bash
cd /opt/Kook_Web_Music
cloud/.venv/bin/python cloud/run.py
```

正常情况下日志应该说明：

```text
Cloud control plane ... 127.0.0.1:18473
Relay backend ... 127.0.0.1:18476
```

保持这个窗口运行，再开一个新的 SSH 窗口。

新窗口执行：

```bash
curl http://127.0.0.1:18473/healthz
```

应该得到 JSON，而不是 Connection refused。

再检查 Relay 端口：

```bash
ss -lnt | grep 18476
```

应该看到 `127.0.0.1:18476` 正在监听。

如果看到：

```text
0.0.0.0:18476
```

说明配置有误，应立即检查 `EDGE_RELAY_HOST`。

确认后，在第一个 SSH 窗口按：

```text
Ctrl + C
```

停止手工 Cloud。

---

## 13. 配置 Caddy

项目已经提供完整模板：

```text
cloud/Caddyfile.example
```

它的设计是：

```text
443              -> Cloud Web 127.0.0.1:18473
28470-28479      -> Relay 127.0.0.1:18476
```

复制模板：

```bash
sudo cp /opt/Kook_Web_Music/cloud/Caddyfile.example /etc/caddy/Caddyfile
```

编辑：

```bash
sudo nano /etc/caddy/Caddyfile
```

把文件里所有：

```text
music.example.com
```

替换成你真实使用的域名。

例如：

```text
kookmusic.yourdomain.com
```

不要修改：

```text
127.0.0.1:18473
127.0.0.1:18476
28470-28479
/edge/v1/connect
```

除非你明确知道自己在改变端口规划。

验证 Caddy 配置：

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
```

成功应看到类似：

```text
Valid configuration
```

如果验证失败，不要重启 Caddy，先检查域名和括号。

---

## 14. 把 Cloud 配置成 systemd 服务

创建服务文件：

```bash
sudo nano /etc/systemd/system/kook-music-cloud.service
```

粘贴：

```ini
[Unit]
Description=KOOK Music Cloud Control Plane
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/Kook_Web_Music
ExecStart=/opt/Kook_Web_Music/cloud/.venv/bin/python /opt/Kook_Web_Music/cloud/run.py
Restart=on-failure
RestartSec=5
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
```

### 14.1 修改 `User=`

执行：

```bash
whoami
```

如果结果不是：

```text
ubuntu
```

把上面服务文件里的：

```ini
User=ubuntu
```

改成 `whoami` 的真实结果。

然后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now kook-music-cloud
```

查看状态：

```bash
sudo systemctl status kook-music-cloud --no-pager
```

正常应看到：

```text
active (running)
```

查看实时日志：

```bash
journalctl -u kook-music-cloud -f
```

按 `Ctrl + C` 退出日志查看不会停止服务。

---

## 15. 启动 Caddy

执行：

```bash
sudo systemctl enable --now caddy
sudo systemctl reload caddy
sudo systemctl status caddy --no-pager
```

正常应看到：

```text
active (running)
```

查看 Caddy 日志：

```bash
journalctl -u caddy -f
```

Caddy 会自动为域名申请和维护 HTTPS 证书。

证书申请失败时，优先检查：

```text
DNS A 记录是否正确
TCP 80 是否开放
TCP 443 是否开放
域名是否真的指向这台服务器
```

---

## 16. 从公网验证 Cloud Web

在自己的电脑浏览器打开：

```text
https://你的域名/login
```

例如：

```text
https://music.example.com/login
```

如果能看到登录页面，说明：

```text
DNS
443
Caddy
Cloud Flask
```

基本都已经正常。

### 16.1 获取 Cloud 首次管理员密码

Cloud 首次启动后，在服务器执行：

```bash
sudo cat /opt/Kook_Web_Music/cloud/data/bootstrap-admin.json
```

文件中会包含 Bootstrap 用户名和临时密码。

默认用户名通常是：

```text
gen
```

请使用文件中的实际值。

登录以后系统会强制要求修改密码。

修改成功后不要继续使用临时密码。

### 16.2 Cloud 和 Edge 管理员不是同一个登录会话

即使 Cloud 和 Edge 都叫 `gen`，它们也属于两个独立安全域：

```text
Cloud 用户数据库 ≠ Edge 本地用户数据库
Cloud Session ≠ Edge Session
```

请分别管理密码。

---

# 第三部分：部署 Edge

## 17. Edge 的部署顺序

Edge 需要完成：

```text
Python
Node.js 20+
FFmpeg
两个全局 Node 音乐 API
平台 .env
edge/.env
本地 WebUI
Agent Token
```

如果 Edge 是 Windows，请看第 18 节。

如果 Edge 是 Ubuntu，请看第 19 节。

---

# 第四部分：Windows Edge

## 18. Windows Edge 安装

以下命令都在 **PowerShell** 中执行。

### 18.1 检查 Python

```powershell
python --version
```

要求至少：

```text
Python 3.10
```

如果系统提示找不到 `python`，请先从 Python 官方安装 Python，并在安装界面勾选：

```text
Add Python to PATH
```

安装后关闭并重新打开 PowerShell，再检查版本。

### 18.2 检查 Git

```powershell
git --version
```

如果找不到 Git，请先安装 Git for Windows。

### 18.3 检查 Node.js

```powershell
node --version
npm --version
```

Node.js 必须为：

```text
20 或更高
```

如果低于 20，请升级后再继续。

### 18.4 安装音乐 Node API

执行：

```powershell
npm install --global NeteaseCloudMusicApi@4.25.0 @sansenjian/qq-music-api@2.3.1
```

检查全局 npm 目录：

```powershell
npm root --global
```

不要在项目目录执行不带 `--global` 的 `npm install`。

### 18.5 检查 FFmpeg

执行：

```powershell
ffmpeg -version
ffprobe -version
```

如果可以显示版本，说明系统 FFmpeg 可用。

如果使用项目自带/手工放置的 FFmpeg，则应确保：

```text
windows\ffmpeg\bin\ffmpeg.exe
windows\ffmpeg\bin\ffprobe.exe
```

存在，或者稍后在 `windows/.env` 中正确指定 `FFMPEG_PATH` 和 `FFPROBE_PATH`。

---

## 18.6 下载项目

例如安装到：

```text
C:\Kook_Web_Music
```

执行：

```powershell
cd C:\
git clone --branch feature/cloud-edge-control-plane https://github.com/xrggen/Kook_Web_Music.git
cd C:\Kook_Web_Music
```

确认：

```powershell
git branch --show-current
```

应为：

```text
feature/cloud-edge-control-plane
```

---

## 18.7 创建 Windows Python 环境

执行：

```powershell
python -m venv windows\.venv
windows\.venv\Scripts\python.exe -m pip install --upgrade pip
windows\.venv\Scripts\python.exe -m pip install -r windows\requirements.txt
```

验证：

```powershell
windows\.venv\Scripts\python.exe -c "import flask,aiohttp,requests; print('Edge Python OK')"
```

应该显示：

```text
Edge Python OK
```

---

## 18.8 创建 Windows 平台 `.env`

执行：

```powershell
cd C:\Kook_Web_Music\windows
..\windows\.venv\Scripts\python.exe create_env.py
```

程序会提示输入 KOOK Bot Token。

输入时不会显示字符，这是正常安全行为。

完成后会生成：

```text
C:\Kook_Web_Music\windows\.env
```

打开：

```powershell
notepad .env
```

重点检查：

```env
BOT_TOKEN=已经配置
MUSIC_API_PORT=18474
QQ_MUSIC_API_PORT=18475
PORT=18473
AUTH_COOKIE_SECURE=false
```

### Bot 白名单

当前安全设计下：

```env
ALLOWGROUP=
ALLOWCHANNEL=
ALLOWUSER=
BOT_ALLOW_UNRESTRICTED=false
```

全部保持空白时，KOOK Bot 指令默认会拒绝。

推荐填写你允许控制 Bot 的 KOOK 用户/服务器/频道 ID，而不是直接开启无限制模式。

只有明确理解风险时才使用：

```env
BOT_ALLOW_UNRESTRICTED=true
```

---

## 18.9 创建 Edge Agent 配置

回到仓库根目录：

```powershell
cd C:\Kook_Web_Music
Copy-Item edge\.env.example edge\.env
notepad edge\.env
```

推荐第一版填写：

```env
EDGE_LOCAL_WEB_HOST=127.0.0.1
EDGE_LOCAL_PORT=18473

EDGE_RELAY_ENABLED=true
EDGE_RELAY_HOST=你的Cloud域名
EDGE_RELAY_PORT_START=28470
EDGE_RELAY_PORT_END=28479
EDGE_RELAY_PATH=/edge/v1/connect
EDGE_RELAY_TLS_VERIFY=true

EDGE_AGENT_ID=edge-main
EDGE_AGENT_NAME=Primary Edge
EDGE_AGENT_TOKEN=
```

这里暂时把：

```env
EDGE_AGENT_TOKEN=
```

留空。

我们稍后从本地 WebUI 输入，这样 Token 不需要长期重复保存在多个配置位置。

---

## 18.10 第一次启动 Windows Edge

执行：

```powershell
cd C:\Kook_Web_Music
windows\.venv\Scripts\python.exe edge\run.py
```

第一次启动可能需要一些时间，因为程序会同时启动：

```text
网易云 Node API
QQ Node API
KOOK Bot
Flask 本地 WebUI
Edge Agent Supervisor
```

即使此时 Agent Token 还没有配置，**本地 WebUI 和 KOOK Bot 仍应启动**。

---

## 18.11 登录 Windows 本地 WebUI

在 Edge 这台 Windows 电脑浏览器打开：

```text
http://127.0.0.1:18473/login
```

首次管理员凭据文件在：

```text
C:\Kook_Web_Music\windows\data\bootstrap-admin.json
```

PowerShell 查看：

```powershell
Get-Content C:\Kook_Web_Music\windows\data\bootstrap-admin.json
```

使用其中的用户名和临时密码登录。

系统会要求立即修改密码。

---

## 18.12 在本地 WebUI 配置 Cloud

登录本地 WebUI 后：

```text
左侧菜单
→ 设置
→ 远程 Cloud 节点
```

填写：

```text
启用远程控制：开启
Cloud 主机：你的 Cloud 域名
端口开始：28470
端口结束：28479
路径：/edge/v1/connect
TLS 验证：开启
Agent ID：edge-main
Agent 名称：Primary Edge
```

Agent Token 输入第 10 步在 Cloud 上生成的**同一个 Token**。

保存 Token 后再点击：

```text
保存并重新连接
```

然后点击：

```text
检测端口池
```

正常情况下应该至少有一个端口显示可达；理想状态是 28470-28479 全部可达。

---

## 18.13 Windows Edge 允许局域网访问（可选）

默认：

```env
EDGE_LOCAL_WEB_HOST=127.0.0.1
```

只能 Edge 本机浏览器打开。

如果需要让同一个局域网中的其他电脑访问：

```env
EDGE_LOCAL_WEB_HOST=0.0.0.0
```

然后以管理员 PowerShell 创建 Windows 防火墙规则：

```powershell
New-NetFirewallRule -DisplayName "KOOK Music Edge Local Web" -Direction Inbound -Protocol TCP -LocalPort 18473 -Action Allow -RemoteAddress LocalSubnet
```

重新启动 Edge 后，局域网电脑访问：

```text
http://Edge局域网IP:18473
```

**不要在路由器上把 18473 映射到公网。**

---

# 第五部分：Ubuntu Edge

## 19. Ubuntu Edge 安装

### 19.1 安装系统工具

执行：

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip ffmpeg curl ca-certificates
```

检查：

```bash
python3 --version
ffmpeg -version
ffprobe -version
```

Python 必须至少 3.10。

---

## 19.2 安装 Node.js 20+

先检查：

```bash
node --version
npm --version
```

如果 Node 已经为 20 或更高，可以跳过 Node 安装。

如果没有 Node 或版本低于 20，请通过你所在发行版认可的 Node.js 20+ 安装渠道完成升级，然后再次确认：

```bash
node --version
```

必须是：

```text
v20.x.x
```

或更高版本。

安装项目需要的全局 Node API：

```bash
sudo npm install --global NeteaseCloudMusicApi@4.25.0 @sansenjian/qq-music-api@2.3.1
```

检查：

```bash
npm root --global
```

不要在仓库目录安装项目级 `node_modules`。

---

## 19.3 下载项目

执行：

```bash
cd /opt
sudo git clone --branch feature/cloud-edge-control-plane https://github.com/xrggen/Kook_Web_Music.git
sudo chown -R $USER:$USER /opt/Kook_Web_Music
cd /opt/Kook_Web_Music
```

确认：

```bash
git branch --show-current
```

必须为：

```text
feature/cloud-edge-control-plane
```

---

## 19.4 创建 Ubuntu Edge Python 环境

```bash
cd /opt/Kook_Web_Music
python3 -m venv Ubuntu/.venv
Ubuntu/.venv/bin/python -m pip install --upgrade pip
Ubuntu/.venv/bin/python -m pip install -r Ubuntu/requirements.txt
```

验证：

```bash
Ubuntu/.venv/bin/python -c "import flask,aiohttp,requests; print('Edge Python OK')"
```

---

## 19.5 创建 Ubuntu 平台 `.env`

```bash
cd /opt/Kook_Web_Music/Ubuntu
../Ubuntu/.venv/bin/python create_env.py
```

输入 KOOK Bot Token。

然后检查：

```bash
nano .env
```

重点确认：

```env
MUSIC_API_PORT=18474
QQ_MUSIC_API_PORT=18475
PORT=18473
AUTH_COOKIE_SECURE=false
```

同时按你的实际 KOOK 权限填写：

```env
ALLOWGROUP=
ALLOWCHANNEL=
ALLOWUSER=
```

不配置白名单并保持：

```env
BOT_ALLOW_UNRESTRICTED=false
```

时，Bot 指令默认拒绝。

---

## 19.6 创建 Ubuntu Edge Agent 配置

```bash
cd /opt/Kook_Web_Music
cp edge/.env.example edge/.env
nano edge/.env
```

填写：

```env
EDGE_LOCAL_WEB_HOST=127.0.0.1
EDGE_LOCAL_PORT=18473
EDGE_RELAY_ENABLED=true
EDGE_RELAY_HOST=你的Cloud域名
EDGE_RELAY_PORT_START=28470
EDGE_RELAY_PORT_END=28479
EDGE_RELAY_PATH=/edge/v1/connect
EDGE_RELAY_TLS_VERIFY=true
EDGE_AGENT_ID=edge-main
EDGE_AGENT_NAME=Primary Edge
EDGE_AGENT_TOKEN=
```

保存：

```bash
chmod 600 edge/.env
```

Token 可以先留空，之后从本地 WebUI 填写。

---

## 19.7 第一次启动 Ubuntu Edge

执行：

```bash
cd /opt/Kook_Web_Music
Ubuntu/.venv/bin/python edge/run.py
```

另开 SSH 窗口检查本地 Web：

```bash
curl -I http://127.0.0.1:18473/login
```

只要能收到 HTTP 响应，就说明 Web 服务已经启动。

查看首次管理员凭据：

```bash
cat /opt/Kook_Web_Music/Ubuntu/data/bootstrap-admin.json
```

如果 Edge 没有桌面浏览器，可先把本地 Web 开放给局域网，见下一节。

---

## 19.8 Ubuntu Edge 局域网 WebUI（可选）

编辑：

```bash
nano /opt/Kook_Web_Music/edge/.env
```

修改：

```env
EDGE_LOCAL_WEB_HOST=0.0.0.0
```

假设你的局域网是：

```text
192.168.1.0/24
```

UFW 可以只允许该局域网访问：

```bash
sudo ufw allow from 192.168.1.0/24 to any port 18473 proto tcp
```

然后局域网电脑浏览器访问：

```text
http://Edge局域网IP:18473/login
```

不要开放：

```text
18474
18475
```

---

## 19.9 配置 Edge 到 Cloud

登录本地 WebUI：

```text
设置
→ 远程 Cloud 节点
```

填写与 Windows 相同：

```text
Cloud 主机
28470-28479
/edge/v1/connect
TLS 开启
edge-main
Agent Token
```

保存后：

```text
检测端口池
保存并重新连接
```

---

## 19.10 Ubuntu Edge systemd 自动启动

确认手工启动完全正常以后，再配置自动启动。

创建：

```bash
sudo nano /etc/systemd/system/kook-music-edge.service
```

内容：

```ini
[Unit]
Description=KOOK Music Edge Runtime
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/Kook_Web_Music
ExecStart=/opt/Kook_Web_Music/Ubuntu/.venv/bin/python /opt/Kook_Web_Music/edge/run.py
Restart=on-failure
RestartSec=5
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
```

执行：

```bash
whoami
```

把 `User=ubuntu` 修改成实际运行用户。

然后：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now kook-music-edge
sudo systemctl status kook-music-edge --no-pager
```

查看实时日志：

```bash
journalctl -u kook-music-edge -f
```

---

# 第六部分：验证 Cloud 与 Edge 是否真的连接

## 20. Edge 本地检查

在 Edge 本地 WebUI 打开：

```text
设置
→ 远程 Cloud 节点
```

关注：

```text
状态
当前端口
最近心跳
延迟
Token 是否已配置
端口池检测结果
```

正常应出现：

```text
Connected / 已连接
```

并显示：

```text
Active Port = 28470-28479 中的某一个
```

端口并不要求固定为 28470。

Edge 会优先记住上一次成功端口；端口失效时会在池内自动切换。

---

## 21. Cloud 检查

登录公网 Cloud WebUI：

```text
https://你的域名/login
```

管理员进入系统状态页面。

Cloud 应能看到 Edge Agent 在线，并看到 Agent 名称、版本、协议、心跳等信息。

Cloud 本机也可以执行：

```bash
curl http://127.0.0.1:18473/healthz
```

正常时应有：

```text
edge_connected = true
```

或等价的已连接状态。

---

## 22. 从 Edge 手工测试 WSS 公网端口

### Windows

PowerShell：

```powershell
Test-NetConnection 你的Cloud域名 -Port 28470
Test-NetConnection 你的Cloud域名 -Port 28471
```

成功时：

```text
TcpTestSucceeded : True
```

不需要手工测试全部 10 个，因为本地设置页的“检测端口池”会一次检测整个范围。

### Ubuntu

可使用：

```bash
curl -I https://你的Cloud域名:28470/edge/v1/connect
```

收到 `400`、`401`、`403` 或 WebSocket Upgrade 相关响应通常说明**网络和 TLS 已经到达 Relay 入口**；因为这个手工 curl 没有 Agent Token，所以不要求返回 200。

如果直接：

```text
Connection timed out
```

优先检查云安全组和防火墙。

---

# 第七部分：完整业务验证

## 23. 先验证 Edge 本地 WebUI

Cloud 暂时不参与。

本地 WebUI 依次检查：

1. 能登录；
2. 能看到 KOOK 服务器；
3. 能看到语音频道；
4. 能搜索歌曲；
5. 能加入语音频道；
6. 能播放；
7. 能暂停 / 继续；
8. 能跳过；
9. 能查看和操作播放队列；
10. 网易 / QQ / Bilibili 账号页面可正常使用。

如果本地 WebUI 都不能播放，不要先排查 Cloud/WSS，因为问题位于 Edge Runtime 本身。

---

## 24. 再验证公网 Cloud WebUI

确保 Edge 已显示 Connected。

公网 WebUI：

1. 登录；
2. 选择与本地相同的 KOOK 服务器；
3. 选择频道；
4. 搜索歌曲；
5. 添加到队列；
6. 确认 Edge 本地 WebUI 同时看到相同队列；
7. 在 Edge 本地执行 Skip；
8. 确认 Cloud 页面随后看到最新状态；
9. 在 KOOK 中使用 Bot 指令操作；
10. 确认 Cloud 状态也随 Edge 的状态同步而变化。

最终必须满足：

```text
Cloud WebUI
Local WebUI
KOOK Bot
```

三条控制路径操作的是**同一个 Edge Playback Runtime 和 Queue**。

---

# 第八部分：验证 WSS 端口池自动切换

## 25. 人工验证单端口故障

先在 Edge 设置页记录：

```text
当前 Active Port
```

例如：

```text
28473
```

然后临时在 Cloud 防火墙阻断该端口。

例如 UFW：

```bash
sudo ufw deny 28473/tcp
```

等待 Edge 自动重连。

预期：

```text
28473 失败
→ Agent 尝试其他端口
→ 28470-28479 中另一个端口 Connected
```

同时确认：

```text
KOOK Bot 不退出
当前播放不停止
本地 WebUI 仍能操作
```

测试结束后恢复：

```bash
sudo ufw delete deny 28473/tcp
```

并确认原有端口池 Allow 规则仍存在。

---

## 26. 验证全端口池故障

这项测试只建议维护人员执行。

阻断整个范围：

```bash
sudo ufw deny 28470:28479/tcp
```

预期：

```text
Cloud 远程控制不可用
Edge Agent 显示 Disconnected
Edge 本地 WebUI 正常
KOOK Bot 正常
已经进行中的播放正常
```

恢复：

```bash
sudo ufw delete deny 28470:28479/tcp
```

Edge 应自动重新连接，并发送完整状态同步。

---

# 第九部分：常见故障排查

## 27. 公网网页打不开

按顺序检查。

### 27.1 DNS

本地电脑：

```powershell
nslookup 你的域名
```

必须指向正确 Cloud IP。

### 27.2 Cloud 服务

Cloud：

```bash
sudo systemctl status kook-music-cloud --no-pager
curl http://127.0.0.1:18473/healthz
```

如果本机 curl 都失败，先修 Cloud Python 服务。

### 27.3 Caddy

```bash
sudo systemctl status caddy --no-pager
sudo caddy validate --config /etc/caddy/Caddyfile
journalctl -u caddy -n 100 --no-pager
```

### 27.4 防火墙

```bash
sudo ufw status
```

确认：

```text
443/tcp
28470:28479/tcp
```

是 Allow。

同时检查云厂商安全组。

---

## 28. Edge 显示所有端口都失败

先从 Edge 测一个：

Windows：

```powershell
Test-NetConnection 你的域名 -Port 28470
```

Ubuntu：

```bash
curl -I https://你的域名:28470/edge/v1/connect
```

如果完全超时：

```text
检查 Cloud 云安全组
检查 UFW
检查 Caddy 是否监听 28470-28479
检查 Edge 出口防火墙
```

Cloud 检查监听：

```bash
sudo ss -lntp | grep 2847
```

应该能看到 Caddy 监听端口池。

---

## 29. `AUTH_FAILED`

含义：

```text
Edge 能连接 Cloud
但 Agent Token 不匹配
```

解决：

1. 打开 Cloud `cloud/.env`；
2. 找到 `EDGE_AGENT_TOKEN`；
3. 不要在聊天中复制；
4. 登录 Edge 本地 WebUI；
5. 设置 → 远程 Cloud 节点；
6. 重新填写同一个 Token；
7. 保存并重新连接。

Token 错误属于配置问题，程序不会通过不停切换 10 个端口来解决。

---

## 30. `TLS_CERTIFICATE_ERROR`

常见原因：

```text
EDGE_RELAY_HOST 写成 IP
证书签发给域名而不是 IP
域名写错
DNS 指向错误服务器
Cloud 系统时间错误
Edge 系统时间错误
证书尚未申请成功
```

生产环境不要为了省事永久设置：

```env
EDGE_RELAY_TLS_VERIFY=false
```

正确做法是修复证书或域名。

---

## 31. `TOKEN_MISSING`

说明 Edge Secret Store 中还没有有效 Agent Token。

登录 Edge 本地 WebUI：

```text
设置
→ 远程 Cloud 节点
→ Agent Token
```

输入 Cloud 对应 Token 并保存。

---

## 32. `LOCAL_RUNTIME_UNAVAILABLE`

说明 Agent 自己启动了，但无法访问 Edge 本机 Runtime。

检查：

```text
Edge 本地 WebUI 是否能打开
18473 是否被其他程序占用
Python 是否报错
Node API 是否启动
平台 .env 是否存在
```

Ubuntu：

```bash
ss -lntp | grep 18473
journalctl -u kook-music-edge -n 100 --no-pager
```

Windows：

```powershell
Get-NetTCPConnection -LocalPort 18473 -ErrorAction SilentlyContinue
```

---

## 33. Bot 在线但命令没有反应

优先查看平台 `.env`：

```env
ALLOWGROUP=
ALLOWCHANNEL=
ALLOWUSER=
BOT_ALLOW_UNRESTRICTED=false
```

全部为空时，安全策略默认拒绝 Bot 指令。

这不是 WSS 故障。

Cloud 不参与 KOOK Bot 命令处理。

---

## 34. 本地 Web 能播放，但公网 Web 不能

这通常说明：

```text
Edge Runtime 正常
Cloud ↔ Edge Relay 有问题
```

检查：

```text
Edge Agent 状态
Active Port
Token
WSS 端口池
Cloud Agent 状态
```

不要去重新安装 FFmpeg，因为本地已经能播放说明 FFmpeg 不是主要问题。

---

# 第十部分：数据和备份

## 35. Cloud 必须备份什么

Cloud 重要数据：

```text
cloud/.env
cloud/data/
```

其中 `cloud/data/kook_music.db` 包含：

```text
Web 用户
角色
Scope
Session
审计
Agent Registry
```

最简单可靠的备份方法是短暂停服务。

```bash
sudo systemctl stop kook-music-cloud
sudo tar -czf /tmp/kook-cloud-backup.tar.gz \
  /opt/Kook_Web_Music/cloud/.env \
  /opt/Kook_Web_Music/cloud/data
sudo systemctl start kook-music-cloud
```

然后把备份文件复制到安全位置。

备份中包含敏感信息，不要上传公共网盘或 GitHub。

---

## 36. Edge 必须备份什么

Edge 重要数据：

```text
windows/.env 或 Ubuntu/.env
平台 Cookie/
平台 data/
edge/.env
```

`data/` 中包含：

```text
本地 Web 用户数据库
Edge 动态 Cloud 配置
Edge Agent Secret
```

因此如果 Edge 损坏但你有完整备份，可以恢复本地账号、音乐平台登录态和远程节点配置。

---

# 第十一部分：升级

## 37. 升级前先备份

不要直接 `git pull` 后祈祷程序正常。

先按照第 35、36 节完成备份。

---

## 38. 升级 Cloud

```bash
cd /opt/Kook_Web_Music
git status
git fetch origin
git switch feature/cloud-edge-control-plane
git pull --ff-only
cloud/.venv/bin/python -m pip install -r cloud/requirements.txt
sudo systemctl restart kook-music-cloud
sudo systemctl status kook-music-cloud --no-pager
```

如果 `cloud/Caddyfile.example` 有变化，请人工对比，不要直接覆盖正在使用的 `/etc/caddy/Caddyfile`。

---

## 39. 升级 Ubuntu Edge

```bash
sudo systemctl stop kook-music-edge
cd /opt/Kook_Web_Music
git status
git fetch origin
git switch feature/cloud-edge-control-plane
git pull --ff-only
Ubuntu/.venv/bin/python -m pip install -r Ubuntu/requirements.txt
sudo systemctl start kook-music-edge
sudo systemctl status kook-music-edge --no-pager
```

---

## 40. 升级 Windows Edge

先退出正在运行的 Edge 窗口，然后 PowerShell：

```powershell
cd C:\Kook_Web_Music
git status
git fetch origin
git switch feature/cloud-edge-control-plane
git pull --ff-only
windows\.venv\Scripts\python.exe -m pip install -r windows\requirements.txt
windows\.venv\Scripts\python.exe edge\run.py
```

不要删除：

```text
.env
Cookie\
data\
edge\.env
```

---

# 第十二部分：回滚

## 41. 什么时候应该回滚

如果升级以后出现：

```text
Cloud 无法启动
Edge 无法启动
数据库迁移异常
WSS 全部异常
播放功能出现严重回归
```

先停止服务，保留日志，不要反复删除数据库。

查看最近提交：

```bash
git log --oneline -10
```

由维护人员选择已知可用提交执行回滚。

同时恢复升级前的 `.env` / `data` / Cookie 备份。

对 SQLite 数据库做版本回退前，必须确认旧代码是否兼容新 Schema；不确定时应由开发人员处理，不要自行删除表。

---

# 第十三部分：部署完成检查表

## 42. Cloud 检查

部署人员最终应逐项确认：

```text
[ ] 域名 A 记录指向 Cloud
[ ] 443 可访问
[ ] 28470-28479 已放行
[ ] 18473/18476 没有公网开放
[ ] Cloud systemd = active
[ ] Caddy = active
[ ] https://域名/login 可以打开
[ ] Cloud 管理员已修改首次密码
```

## 43. Edge 检查

```text
[ ] Python >= 3.10
[ ] Node >= 20
[ ] FFmpeg / ffprobe 可用
[ ] 两个 Node API 已全局安装
[ ] BOT_TOKEN 已配置
[ ] Bot 白名单已按实际需求配置
[ ] 本地 WebUI 能登录
[ ] 本地管理员已修改首次密码
[ ] 本地 WebUI 可以正常播放
[ ] Agent Token 已通过本地设置页写入
[ ] WSS 端口池检测至少一个端口可达
[ ] Agent 状态 Connected
[ ] Cloud Web 能看到 Edge
[ ] Cloud / Local Web / KOOK Bot 操作同一个 Queue
```

## 44. 安全检查

```text
[ ] 没有把 .env 提交 Git
[ ] 没有把 Cookie 提交 Git
[ ] 没有把 Agent Token 发到聊天或截图
[ ] Cloud 18473/18476 未公网开放
[ ] Edge 18474/18475 未公网开放
[ ] Edge Local Web 如开放 LAN，防火墙只允许可信局域网
[ ] TLS 验证保持开启
[ ] Cloud 和 Edge 都已更换首次管理员临时密码
```

---

# 第十四部分：当前架构限制

## 45. Cloud 暂时不要启动多个独立 Worker

当前 Cloud 为：

```text
1 Flask process
1 RelayHub
1 内存 Runtime Read Cache
```

因此不要直接使用：

```text
gunicorn -w 4
```

这种多独立 Worker 模式。

原因是不同 Worker 之间目前不共享：

```text
Agent WebSocket 所有权
命令关联状态
Runtime Read Cache
```

未来需要多实例 HA 时，需要增加 Redis/NATS 等共享总线。

当前单 Cloud 实例配合 systemd 自动重启即可。

---

# 第十五部分：管理员日常常用命令速查

## 46. Cloud

查看状态：

```bash
sudo systemctl status kook-music-cloud --no-pager
sudo systemctl status caddy --no-pager
```

重启：

```bash
sudo systemctl restart kook-music-cloud
sudo systemctl restart caddy
```

日志：

```bash
journalctl -u kook-music-cloud -f
journalctl -u caddy -f
```

检查内部端口：

```bash
ss -lnt | grep 18473
ss -lnt | grep 18476
```

检查公网 WSS 监听：

```bash
ss -lnt | grep 2847
```

---

## 47. Ubuntu Edge

查看：

```bash
sudo systemctl status kook-music-edge --no-pager
```

重启：

```bash
sudo systemctl restart kook-music-edge
```

日志：

```bash
journalctl -u kook-music-edge -f
```

---

## 48. Windows Edge

如果使用前台方式运行：

```powershell
cd C:\Kook_Web_Music
windows\.venv\Scripts\python.exe edge\run.py
```

查看端口：

```powershell
Get-NetTCPConnection -LocalPort 18473 -ErrorAction SilentlyContinue
Get-NetTCPConnection -LocalPort 18474 -ErrorAction SilentlyContinue
Get-NetTCPConnection -LocalPort 18475 -ErrorAction SilentlyContinue
```

测试 Cloud：

```powershell
Test-NetConnection 你的Cloud域名 -Port 28470
```

---

# 49. 仍然无法解决怎么办

向开发/运维人员反馈问题时，不要只说“连不上”。请提供以下**非敏感**信息：

```text
Cloud 操作系统版本
Edge 操作系统版本
Python 版本
Node 版本
发生问题的步骤编号
Cloud systemd 状态
Caddy 状态
Edge Agent 状态码
Active Port
端口池中哪些端口 reachable / failed
错误发生时间
```

可以提供日志中的错误类型，但必须先检查并删除：

```text
Bot Token
Agent Token
Cookie
Credential
Session / CSRF
管理员密码
签名媒体 URL
```

详细架构原理见 [cloud-edge-architecture.md](cloud-edge-architecture.md)。工程接手信息见 [HANDOFF.md](HANDOFF.md)。安全边界见 [security.md](security.md)。
