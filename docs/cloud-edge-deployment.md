# Cloud / Edge 零基础部署手册

> 本文面向**没有 Linux、反向代理、WebSocket、Python、Node.js 或服务器运维经验**的部署人员。
>
> 请严格按顺序操作。每一节都告诉你“做什么”“为什么”“成功后应该看到什么”。如果某一步没有通过，请先解决该步骤，再继续下一步。

---

## 1. 先理解最终部署结构

本项目的正式 Cloud / Edge 模式由两个部分组成：

```text
公网用户
   │
   │ HTTPS 28443
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

- **Cloud**：给公网用户提供网页、登录、权限和远程控制入口。
- **Edge**：真正执行 KOOK Bot、搜索、播放、FFmpeg、音乐平台登录等动作。
- Edge **不需要公网 IP**，只需要能访问互联网。
- Edge 主动连接 Cloud，所以不需要在 Edge 路由器上配置端口映射。
- Cloud 或 WSS 临时断线时，Edge 本地 WebUI、KOOK Bot 和已经运行的播放仍然继续工作。

### 1.1 默认端口

| 用途 | 默认地址/端口 | 是否对公网开放 |
|---|---|---|
| Cloud Web HTTPS | `28443/tcp` | 是 |
| Cloud WSS 端口池 | `28470-28479/tcp` | 是 |
| ACME HTTP-01 证书验证 | `80/tcp` | 推荐，仅证书用途 |
| Cloud Flask | `127.0.0.1:18473` | 否 |
| Cloud Relay backend | `127.0.0.1:18476` | 否 |
| Edge 本地 WebUI | `127.0.0.1:18473` | 默认否 |
| Edge 网易云 API | `127.0.0.1:18474` | 否 |
| Edge QQ API | `127.0.0.1:18475` | 否 |

### 1.2 重要变化：Cloud Web 不再使用 443

Cloud 公网控制台正式访问地址是：

```text
https://你的域名:28443/
```

例如：

```text
https://music.example.com:28443/
```

浏览器地址中**必须写 `:28443`**。如果只输入：

```text
https://music.example.com/
```

浏览器会默认尝试 443，而本项目不再把 443 作为正式 Cloud Web 入口。

### 1.3 80 端口是做什么的

如果你使用本文推荐的 Caddy 自动申请和自动续期 HTTPS 证书，最简单的方式是允许：

```text
TCP 80
```

它主要用于 ACME HTTP-01 证书验证。

正式用户访问仍然使用：

```text
28443
```

而不是 80。

如果你已经有自己的证书，或者使用 DNS challenge，可以根据自己的证书方案关闭 80。

### 1.4 不要开放的端口

Cloud 的下面两个端口只能监听本机：

```text
18473
18476
```

Edge 的下面几个端口也不应做公网映射：

```text
18473
18474
18475
```

---

# 第一部分：部署前准备

## 2. 需要准备什么

### 2.1 一台公网 Cloud 服务器

推荐最低配置：

```text
Ubuntu 22.04 / 24.04 64 位
CPU：2 核
内存：2 GB
磁盘：20 GB
公网 IPv4：需要
```

Cloud 不需要 GPU、FFmpeg、Node.js 或音乐平台 Cookie。

### 2.2 一个域名

本文统一使用示例：

```text
music.example.com
```

你必须替换成自己的真实域名。

### 2.3 一台 Edge 执行机

支持：

```text
Windows 10 / 11 / Server
或
Ubuntu Linux
```

Edge 必须能够：

- 访问互联网；
- 访问 KOOK；
- 访问网易云、QQ、Bilibili；
- 主动连接 Cloud 的 `28470-28479/tcp`；
- 正常解析 Cloud 域名。

Edge 不要求公网 IP。

### 2.4 KOOK Bot Token

Bot Token **只放 Edge**。

不要把 Bot Token 放到：

```text
Cloud
GitHub
部署文档
截图
群聊
```

### 2.5 一个密码管理器或安全记录位置

部署过程中会产生：

```text
Cloud SECRET_KEY
EDGE_AGENT_TOKEN
Cloud Bootstrap 管理员密码
Edge Local Bootstrap 管理员密码
```

这些内容都不要写入 Git。

---

# 第二部分：部署 Cloud 公网服务器

## 3. 通过 SSH 登录 Cloud

在 Windows PowerShell 中：

```powershell
ssh 用户名@服务器公网IP
```

例如：

```powershell
ssh ubuntu@203.0.113.10
```

登录后通常会看到：

```text
ubuntu@cloud:~$
```

后续 Linux 命令都在这个窗口中执行。

---

## 4. 更新 Ubuntu 并安装基础工具

执行：

```bash
sudo apt update
sudo apt upgrade -y
```

安装：

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

- Git 能显示版本号；
- Python 至少 3.10；
- Caddy 能显示版本号。

如果 Python 小于 3.10，请先升级 Python。

---

## 5. 下载项目代码

推荐放到：

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

确认分支：

```bash
git branch --show-current
```

必须看到：

```text
feature/cloud-edge-control-plane
```

---

## 6. 创建 Cloud Python 虚拟环境

执行：

```bash
cd /opt/Kook_Web_Music
python3 -m venv cloud/.venv
cloud/.venv/bin/python -m pip install --upgrade pip
cloud/.venv/bin/python -m pip install -r cloud/requirements.txt
```

验证：

```bash
cloud/.venv/bin/python -c "import flask,aiohttp; print('Cloud Python OK')"
```

成功应显示：

```text
Cloud Python OK
```

---

## 7. 配置域名 DNS

到你的域名服务商控制台创建 A 记录。

例如：

```text
主机记录：music
类型：A
值：Cloud 公网 IPv4
```

如果使用 Cloudflare 等代理服务，首次部署建议先使用普通 DNS 解析，不要启用会代理非标准端口的 CDN 功能，避免把问题复杂化。

在自己的 Windows 电脑检查：

```powershell
nslookup music.example.com
```

必须解析到 Cloud 的公网 IP。

### 7.1 IPv6

如果服务器没有正确的公网 IPv6，请不要添加 AAAA 记录。

错误 AAAA 记录会造成部分客户端优先 IPv6 后访问失败。

---

## 8. 配置 Cloud 安全组和防火墙

通常有两层：

```text
云厂商安全组
Ubuntu UFW
```

两层都要正确配置。

### 8.1 云厂商安全组

建议入站规则：

```text
TCP 22             SSH
TCP 80             Caddy/ACME HTTP-01 证书验证
TCP 28443          Cloud HTTPS WebUI
TCP 28470-28479    Edge WSS 端口池
```

本项目正式业务**不要求开放 443**。

不要开放：

```text
18473
18474
18475
18476
```

### 8.2 如果服务器原来已经开放 443

如果这台服务器只运行本项目，并确认没有其他网站或服务依赖 443，可以关闭该规则。

如果服务器还有别的业务使用 443，则不要因为本项目修改其他业务的防火墙。

### 8.3 Ubuntu UFW

先检查：

```bash
sudo ufw status
```

如果 SSH 是 22：

```bash
sudo ufw allow 22/tcp
```

添加项目端口：

```bash
sudo ufw allow 80/tcp
sudo ufw allow 28443/tcp
sudo ufw allow 28470:28479/tcp
```

启用：

```bash
sudo ufw enable
sudo ufw status numbered
```

在退出 SSH 之前，必须确认 SSH 端口仍然允许。

---

## 9. 生成 Cloud SECRET_KEY

执行：

```bash
cd /opt/Kook_Web_Music
cloud/.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))"
```

复制生成结果到密码管理器，名称例如：

```text
KOOK Music Cloud SECRET_KEY
```

不要使用文档里的示例字符串。

---

## 10. 生成 EDGE_AGENT_TOKEN

再执行一次：

```bash
cloud/.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))"
```

保存为：

```text
KOOK Music EDGE_AGENT_TOKEN
```

这个值必须同时配置到 Cloud 和对应 Edge。

Cloud 和 Edge 的 Token 不一致时，WSS 会认证失败。

---

## 11. 创建 Cloud `.env`

执行：

```bash
cd /opt/Kook_Web_Music
cp cloud/.env.example cloud/.env
nano cloud/.env
```

至少确认：

```env
HOST=127.0.0.1
PORT=18473

EDGE_RELAY_HOST=127.0.0.1
EDGE_RELAY_PORT=18476
EDGE_PUBLIC_WSS_PORT_START=28470
EDGE_PUBLIC_WSS_PORT_END=28479

EDGE_AGENT_ID=edge-main
EDGE_AGENT_NAME=Primary Edge
EDGE_AGENT_TOKEN=这里填第10步生成的AgentToken

AUTH_DATABASE_PATH=./data/kook_music.db
INITIAL_ADMIN_USERNAME=gen
INITIAL_ADMIN_PASSWORD=
INITIAL_ADMIN_CREDENTIAL_PATH=./data/bootstrap-admin.json

AUTH_COOKIE_SECURE=true
AUTH_TRUST_PROXY_HEADERS=true
SECRET_KEY=这里填第9步生成的SECRET_KEY

CLOUD_STATE_CACHE_MAX_AGE=20
MAX_REQUEST_BYTES=1048576
LOG_LEVEL=INFO
```

注意：

- Cloud 公网 `28443` 是 Caddy 层端口，不是 Flask `PORT`。
- Flask `PORT` 继续保持 `18473`。
- 不要把 Flask 改成直接监听 `28443`。

保存 nano：

```text
Ctrl + O
Enter
Ctrl + X
```

限制配置文件权限：

```bash
chmod 600 cloud/.env
```

---

## 12. 第一次手工启动 Cloud

先不要配置 systemd。

执行：

```bash
cd /opt/Kook_Web_Music
cloud/.venv/bin/python cloud/run.py
```

正常日志应能看到 Cloud Flask 和 Relay 启动。

另开一个 SSH 窗口：

```bash
curl http://127.0.0.1:18473/healthz
```

应该返回 JSON。

检查 Relay：

```bash
ss -lnt | grep 18476
```

应该看到类似：

```text
127.0.0.1:18476
```

如果看到：

```text
0.0.0.0:18476
```

请检查 `EDGE_RELAY_HOST`，不应让内部 Relay 直接公网监听。

检查 Flask：

```bash
ss -lnt | grep 18473
```

也应该是：

```text
127.0.0.1:18473
```

确认后按 `Ctrl + C` 停止手工 Cloud。

---

## 13. 配置 Caddy：公网 Web 改用 28443

项目提供模板：

```text
cloud/Caddyfile.example
```

当前模板设计：

```text
28443           -> Cloud Flask 127.0.0.1:18473
28470-28479     -> RelayHub 127.0.0.1:18476
```

复制：

```bash
sudo cp /opt/Kook_Web_Music/cloud/Caddyfile.example /etc/caddy/Caddyfile
```

编辑：

```bash
sudo nano /etc/caddy/Caddyfile
```

把全部：

```text
music.example.com
```

替换成你的真实域名。

Cloud Web 站点应该类似：

```caddy
https://kookmusic.yourdomain.com:28443 {
    encode zstd gzip
    reverse_proxy 127.0.0.1:18473
}
```

WSS 端口类似：

```caddy
https://kookmusic.yourdomain.com:28470 {
    @edge path /edge/v1/connect
    handle @edge {
        reverse_proxy 127.0.0.1:18476
    }
    respond 404
}
```

其余 `28471-28479` 使用相同结构。

不要把 Web 站点改回普通：

```text
https://domain:443
```

除非你明确决定改变当前项目端口规划。

### 13.1 验证 Caddy 配置

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
```

成功应显示配置有效。

### 13.2 启动或重启 Caddy

```bash
sudo systemctl enable caddy
sudo systemctl restart caddy
sudo systemctl status caddy --no-pager
```

状态应为：

```text
active (running)
```

### 13.3 如果 Caddy 证书申请失败

查看日志：

```bash
sudo journalctl -u caddy -n 100 --no-pager
```

重点检查：

1. DNS 是否已经指向正确公网 IP；
2. 云安全组是否开放 TCP 80；
3. UFW 是否开放 TCP 80；
4. 域名是否有错误 AAAA 记录；
5. 是否有其他程序占用 80。

检查 80：

```bash
sudo ss -lntp | grep ':80 '
```

使用 stock Caddy 自动证书时，保留 80 通常是最简单的部署方式。

---

## 14. 从外部电脑测试 Cloud Web 端口

不要只在服务器本机测试。

在 Windows PowerShell：

```powershell
Test-NetConnection music.example.com -Port 28443
```

预期：

```text
TcpTestSucceeded : True
```

然后浏览器打开：

```text
https://music.example.com:28443/
```

必须包含：

```text
:28443
```

### 14.1 常见错误

如果：

```powershell
Test-NetConnection ... -Port 28443
```

失败，优先检查：

```text
云安全组
UFW
Caddy 是否监听
域名是否正确
```

Cloud 上执行：

```bash
sudo ss -lntp | grep 28443
```

如果 Caddy 正常，应看到对应监听。

---

## 15. 测试 WSS 公网端口池

先从 Windows 电脑简单检查 TCP：

```powershell
28470..28479 | ForEach-Object {
    Test-NetConnection music.example.com -Port $_ -WarningAction SilentlyContinue |
        Select-Object RemotePort,TcpTestSucceeded
}
```

理想情况下 10 个端口全部显示：

```text
True
```

如果部分端口失败，Edge 后续仍可能通过其他可用端口建立连接，但应先确认 Cloud 安全组和 Caddy 配置完整。

---

## 16. 首次 Cloud 管理员登录

Cloud 第一次初始化数据库时，如果没有显式设置 `INITIAL_ADMIN_PASSWORD`，会生成 Bootstrap 管理员凭据文件：

```text
cloud/data/bootstrap-admin.json
```

查看：

```bash
sudo cat /opt/Kook_Web_Music/cloud/data/bootstrap-admin.json
```

用户名通常是：

```text
gen
```

使用浏览器打开：

```text
https://你的域名:28443/login
```

登录后系统会强制修改密码。

请立即设置自己的新密码。

### 16.1 不要长期保存 Bootstrap 密码

首次改密后，临时凭据应不再作为日常登录方式。

建议之后创建第二个管理员作为恢复路径。

---

## 17. 将 Cloud 配置为 systemd 服务

先查看当前 Linux 用户：

```bash
whoami
```

假设结果是：

```text
ubuntu
```

创建：

```bash
sudo nano /etc/systemd/system/kook-music-cloud.service
```

内容：

```ini
[Unit]
Description=KOOK Music Cloud Control Plane
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/Kook_Web_Music
ExecStart=/opt/Kook_Web_Music/cloud/.venv/bin/python cloud/run.py
Restart=on-failure
RestartSec=5
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
```

如果你的 `whoami` 不是 `ubuntu`，把 `User=ubuntu` 改成实际用户名。

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now kook-music-cloud
sudo systemctl status kook-music-cloud --no-pager
```

实时日志：

```bash
sudo journalctl -u kook-music-cloud -f
```

---

# 第三部分：部署 Edge

## 18. Edge 与 Cloud 的关系

Edge 启动时会运行：

```text
本地完整 WebUI
KOOK Bot
网易云 API
QQ API
Bilibili 适配
FFmpeg / 播放核心
EdgeAgentSupervisor
```

即使 Cloud 不在线，本地功能仍应可以启动。

---

# 第四部分：Windows Edge 安装

## 19. Windows 安装基础软件

至少需要：

```text
Git
Python 3.10+
Node.js 20+
npm
FFmpeg/ffprobe
```

如果系统有 `winget`，可以使用 Windows Terminal / PowerShell 管理员窗口安装。

例如：

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id Gyan.FFmpeg -e
```

安装后关闭并重新打开 PowerShell。

检查：

```powershell
git --version
python --version
node --version
npm --version
ffmpeg -version
ffprobe -version
```

Node 必须至少 20。

---

## 20. Windows 下载项目

示例安装到：

```text
C:\Kook_Web_Music
```

执行：

```powershell
cd C:\
git clone --branch feature/cloud-edge-control-plane https://github.com/xrggen/Kook_Web_Music.git
cd C:\Kook_Web_Music
git branch --show-current
```

必须看到：

```text
feature/cloud-edge-control-plane
```

---

## 21. Windows 安装全局 Node 音乐 API

执行：

```powershell
npm install --global NeteaseCloudMusicApi@4.25.0 @sansenjian/qq-music-api@2.3.1
```

验证：

```powershell
npm root --global
```

不要在项目目录中执行不带 `--global` 的 npm install。

---

## 22. Windows 创建 Python 环境

```powershell
cd C:\Kook_Web_Music
python -m venv windows\.venv
windows\.venv\Scripts\python.exe -m pip install --upgrade pip
windows\.venv\Scripts\python.exe -m pip install -r windows\requirements.txt
```

验证：

```powershell
windows\.venv\Scripts\python.exe -c "import flask,aiohttp,requests; print('Edge Python OK')"
```

应该看到：

```text
Edge Python OK
```

---

## 23. Windows 创建平台 `.env`

推荐运行：

```powershell
windows\.venv\Scripts\python.exe windows\create_env.py
```

程序会要求输入 KOOK Bot Token。

输入时终端不会显示 Token，这是正常的。

脚本会创建：

```text
windows\.env
```

### 23.1 Bot 命令权限

安全默认下，如果：

```env
ALLOWGROUP=
ALLOWCHANNEL=
ALLOWUSER=
BOT_ALLOW_UNRESTRICTED=false
```

则 Bot 指令默认不会开放给所有人。

建议根据实际 KOOK Guild/Channel/User 填写白名单。

不要为了“先跑起来”长期设置：

```env
BOT_ALLOW_UNRESTRICTED=true
```

除非你明确接受所有 KOOK 用户都能控制机器人。

---

## 24. Windows 创建 `edge/.env`

执行：

```powershell
Copy-Item edge\.env.example edge\.env
notepad edge\.env
```

建议：

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
EDGE_AGENT_TOKEN=
```

把：

```text
music.example.com
```

换成你的 Cloud 域名。

`EDGE_AGENT_TOKEN` 可以先保持空白，之后通过 Edge 本地 WebUI 安全写入 Secret Store。

---

## 25. Windows 首次启动 Edge

在项目根目录运行：

```powershell
cd C:\Kook_Web_Music
windows\.venv\Scripts\python.exe edge\run.py
```

不要执行：

```text
windows/run.py
```

如果你要运行 Cloud/Edge 分离模式，正式 Edge 入口是：

```text
edge/run.py
```

### 25.1 成功后应该发生什么

至少应该看到：

```text
Edge Local WebUI listening on http://127.0.0.1:18473
```

同时网易云、QQ、本地 Flask 和 KOOK Bot 会按现有运行逻辑启动。

如果 Agent Token 尚未配置，WSS 可以显示 configuration error，但这不应该阻止本地 WebUI 启动。

---

## 26. Windows 打开 Edge 本地 WebUI

在 Edge 自己的浏览器打开：

```text
http://127.0.0.1:18473/
```

这是本地 HTTP，不是公网 Cloud HTTPS。

第一次启动本地控制面时，Bootstrap 管理员凭据通常位于：

```text
windows\data\bootstrap-admin.json
```

可以用记事本打开，登录 `gen`，然后按要求修改密码。

Cloud 管理员和 Edge Local 管理员属于两个独立安全域，密码可以不同。

---

## 27. Windows 在本地 WebUI 配置 Cloud

登录 Edge Local WebUI 后：

```text
设置
→ 远程控制节点
```

填写：

```text
启用远程控制：开启
Cloud 主机：你的 Cloud 域名
起始端口：28470
结束端口：28479
WSS 路径：/edge/v1/connect
TLS Verify：开启
Agent ID：edge-main
Agent Name：Primary Edge
```

然后设置 Agent Token。

这里输入的 Token 必须与 Cloud `.env` 中：

```env
EDGE_AGENT_TOKEN=
```

完全相同。

保存后 Edge 会重连 WSS，不会重启 Bot、FFmpeg 或当前播放。

---

## 28. Windows 检测 WSS 端口池

在 Edge 本地设置页点击：

```text
检测端口池
```

正常情况下应该看到 `28470-28479` 多数或全部为 reachable。

如果全部失败，在 PowerShell 测试：

```powershell
28470..28479 | ForEach-Object {
    Test-NetConnection music.example.com -Port $_ -WarningAction SilentlyContinue |
        Select-Object RemotePort,TcpTestSucceeded
}
```

如果 TCP 都失败，问题通常在：

```text
Cloud 安全组
Cloud UFW
Caddy
Edge 出站防火墙
企业网络出口策略
DNS
```

---

# 第五部分：Ubuntu Edge 安装

## 29. Ubuntu Edge 安装基础依赖

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip ffmpeg curl
```

Node.js 必须 20+。

检查：

```bash
node --version
npm --version
```

如果没有 Node 或低于 20，请先安装/升级 Node.js 20+。

---

## 30. Ubuntu Edge 下载项目

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

## 31. Ubuntu Edge 安装 Node API

```bash
sudo npm install --global NeteaseCloudMusicApi@4.25.0 @sansenjian/qq-music-api@2.3.1
npm root --global
```

---

## 32. Ubuntu Edge Python 环境

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

## 33. Ubuntu Edge 创建平台 `.env`

```bash
Ubuntu/.venv/bin/python Ubuntu/create_env.py
```

输入 KOOK Bot Token。

然后按需编辑：

```bash
nano Ubuntu/.env
```

配置 Bot 白名单等参数。

---

## 34. Ubuntu Edge 创建 `edge/.env`

```bash
cp edge/.env.example edge/.env
nano edge/.env
```

填写 Cloud 主机：

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
EDGE_AGENT_TOKEN=
```

---

## 35. Ubuntu Edge 启动

```bash
cd /opt/Kook_Web_Music
Ubuntu/.venv/bin/python edge/run.py
```

本机打开：

```text
http://127.0.0.1:18473/
```

如果 Edge 是没有桌面的服务器，可以先使用 SSH 端口转发从自己的电脑访问：

```powershell
ssh -L 18473:127.0.0.1:18473 用户名@Edge地址
```

然后浏览器打开：

```text
http://127.0.0.1:18473/
```

---

# 第六部分：允许局域网访问 Edge Local WebUI

## 36. 默认不要开放 LAN

默认：

```env
EDGE_LOCAL_WEB_HOST=127.0.0.1
```

只允许 Edge 本机访问，是最安全的。

### 36.1 Windows 如确实需要 LAN

改：

```env
EDGE_LOCAL_WEB_HOST=0.0.0.0
```

然后用管理员 PowerShell 创建仅允许本地子网的规则：

```powershell
New-NetFirewallRule `
  -DisplayName "KOOK Music Edge WebUI LAN" `
  -Direction Inbound `
  -Action Allow `
  -Protocol TCP `
  -LocalPort 18473 `
  -RemoteAddress LocalSubnet
```

不要在路由器做公网端口映射。

### 36.2 Ubuntu LAN

例如局域网是 `192.168.1.0/24`：

```bash
sudo ufw allow from 192.168.1.0/24 to any port 18473 proto tcp
```

不要使用：

```bash
sudo ufw allow 18473/tcp
```

把它无条件开放给所有来源，尤其是在机器具备公网接口时。

---

# 第七部分：Cloud / Edge 联调

## 37. 先确认 Cloud Web

从任意公网电脑打开：

```text
https://你的域名:28443/
```

如果打不开，先不要排查 Edge。

因为这一步只验证：

```text
DNS
28443 防火墙
Caddy
Cloud Flask
TLS
```

---

## 38. 再确认 Edge 本地运行

Edge 本地打开：

```text
http://127.0.0.1:18473/
```

检查：

```text
本地登录
服务器/频道
音乐搜索
Bot 状态
音乐账号
```

如果本地 Runtime 都异常，不要先排查 WSS。

---

## 39. 查看 Edge WSS 状态

本地设置页应该显示类似：

```text
Connected
Active Port: 2847x
Latency: xx ms
Last heartbeat: ...
```

Agent 任意时刻只使用一个端口。

它不会同时建立 10 条正式 WSS。

---

## 40. Cloud 查看 Edge 在线状态

登录：

```text
https://你的域名:28443/
```

Cloud 系统状态应该能够看到 Edge Agent 在线。

如果 Cloud Web 正常但 Edge Offline：

重点排查：

```text
EDGE_AGENT_TOKEN
28470-28479
Cloud Relay 18476
TLS hostname
Agent ID
```

而不是排查 Cloud Web 的 28443。

---

## 41. 验证双控制面操作同一个 Runtime

先在 Edge Local WebUI 加一首歌。

然后到 Cloud WebUI：

```text
https://你的域名:28443/
```

检查队列是否出现相同歌曲。

再从 Cloud 执行：

```text
暂停
继续
跳过
顶歌
```

回到 Edge Local WebUI，状态应该同步变化。

双方操作的是同一个 Edge Queue，不是两套独立队列。

---

# 第八部分：验证 WSS 端口池故障切换

## 42. 记录当前 Active Port

例如本地状态显示：

```text
Active Port = 28473
```

记录下来。

---

## 43. 临时阻断当前端口

在 Cloud UFW 临时拒绝这个端口，例如：

```bash
sudo ufw deny 28473/tcp
```

注意只阻断当前 Active Port，不要一次阻断整个池。

---

## 44. 观察 Edge 自动切换

Edge 应该：

```text
28473 failed
↓
尝试其他候选端口
↓
例如 28476 connected
```

同时验证：

```text
KOOK Bot             继续
当前音乐播放          继续
Local WebUI          继续
FFmpeg               继续
```

恢复规则：

```bash
sudo ufw delete deny 28473/tcp
```

---

## 45. 验证全池断开

这是维护测试，生产高峰不要随意操作。

临时阻断整个池：

```bash
sudo ufw deny 28470:28479/tcp
```

预期：

```text
Cloud Remote Control  不可用
Edge Local WebUI      正常
KOOK Bot              正常
当前播放              正常
自动下一首            正常
```

恢复：

```bash
sudo ufw delete deny 28470:28479/tcp
```

Edge 应自动重连，不需要重启播放核心。

---

# 第九部分：常见故障排查

## 46. 浏览器打不开 `https://domain:28443/`

按顺序检查。

### 46.1 DNS

Windows：

```powershell
nslookup 你的域名
```

必须指向 Cloud IP。

### 46.2 TCP

```powershell
Test-NetConnection 你的域名 -Port 28443
```

必须：

```text
TcpTestSucceeded : True
```

### 46.3 Cloud 安全组

必须允许：

```text
28443/tcp
```

### 46.4 UFW

```bash
sudo ufw status numbered
```

### 46.5 Caddy

```bash
sudo systemctl status caddy --no-pager
sudo journalctl -u caddy -n 100 --no-pager
sudo ss -lntp | grep 28443
```

### 46.6 Flask

```bash
curl http://127.0.0.1:18473/healthz
```

如果本地 Flask 正常但公网 28443 不通，问题通常在 Caddy/防火墙/TLS，而不是 Flask。

---

## 47. 浏览器证书错误

检查：

```text
浏览器访问的域名
Caddyfile 域名
DNS A 记录
证书覆盖域名
系统时间
```

不要关闭浏览器证书验证作为长期解决方案。

---

## 48. Caddy 无法申请证书

查看：

```bash
sudo journalctl -u caddy -n 100 --no-pager
```

最常见原因：

```text
80 未开放
DNS 未生效
AAAA 错误
域名代理/CDN 干扰
80 被其他程序占用
```

---

## 49. Edge 显示 `TOKEN_MISSING`

含义：Agent Token 没有配置或太短。

在 Edge Local WebUI：

```text
设置 → 远程控制节点 → Agent Token
```

输入与 Cloud 完全相同的 Token。

---

## 50. Edge 显示 `AUTH_FAILED`

网络通常已经通了，Cloud 已经收到请求，但认证失败。

重点检查：

```text
Cloud EDGE_AGENT_TOKEN
Edge Agent Token
Agent ID
```

不要因为 `AUTH_FAILED` 去修改 WSS 端口池。

---

## 51. Edge 显示 `TLS_CERTIFICATE_ERROR`

说明已经尝试 TLS，但证书不可信或域名不匹配。

检查：

```text
EDGE_RELAY_HOST 是否就是证书中的域名
Caddy 证书是否成功
Edge 系统时间是否正确
```

不要长期设置：

```env
EDGE_RELAY_TLS_VERIFY=false
```

生产环境应保持 TLS 验证开启。

---

## 52. Edge 全部 WSS 端口失败

如果 `28470-28479` 全部失败，检查：

```text
Cloud 安全组
Cloud UFW
Caddy 10 个 listener
企业出口防火墙
Edge 主机防火墙
DNS
```

Cloud 执行：

```bash
sudo ss -lntp | grep -E '2847[0-9]'
```

---

## 53. `LOCAL_RUNTIME_UNAVAILABLE`

这不是公网问题。

说明 Edge Agent 无法访问 Edge 自己的 Local Runtime。

检查 Edge：

```text
Local WebUI 18473
Python 主进程
本地 Auth DB
Node API
```

先确保：

```text
http://127.0.0.1:18473/
```

能够正常打开。

---

## 54. Bot 在线但 KOOK 指令没有反应

先检查平台 `.env`：

```env
ALLOWGROUP=
ALLOWCHANNEL=
ALLOWUSER=
BOT_ALLOW_UNRESTRICTED=false
```

默认安全策略可能拒绝所有 Bot 控制用户。

这与 Cloud 28443 或 WSS 端口池无关。

---

# 第十部分：持久数据与备份

## 55. Cloud 必须备份什么

至少：

```text
cloud/.env
cloud/data/
/etc/caddy/Caddyfile
```

Cloud `data/` 包含 Web 用户、Scope、审计和 Agent Registry 等数据。

---

## 56. Edge 必须备份什么

Windows：

```text
windows/.env
windows/Cookie/
windows/data/
edge/.env
```

Ubuntu：

```text
Ubuntu/.env
Ubuntu/Cookie/
Ubuntu/data/
edge/.env
```

其中：

```text
edge_config.db
edge-agent.secret
```

位于平台 `data/` 中。

Agent Secret 不应上传到 Git 或普通网盘公开目录。

---

## 57. SQLite 备份注意

数据库启用 WAL 后可能存在：

```text
.db
.db-wal
.db-shm
```

最简单安全方式：

1. 停止对应服务；
2. 确认进程退出；
3. 再复制整个 `data/`。

不要在高频写入时只复制主 `.db` 文件。

---

# 第十一部分：升级

## 58. Cloud 升级

先备份。

然后：

```bash
cd /opt/Kook_Web_Music
git status
git pull
cloud/.venv/bin/python -m pip install -r cloud/requirements.txt
sudo systemctl restart kook-music-cloud
sudo systemctl restart caddy
```

检查：

```bash
sudo systemctl status kook-music-cloud --no-pager
sudo systemctl status caddy --no-pager
```

外部重新访问：

```text
https://你的域名:28443/
```

---

## 59. Windows Edge 升级

停止 Edge 进程后：

```powershell
cd C:\Kook_Web_Music
git status
git pull
windows\.venv\Scripts\python.exe -m pip install -r windows\requirements.txt
windows\.venv\Scripts\python.exe edge\run.py
```

不要删除：

```text
windows\.env
windows\Cookie\
windows\data\
edge\.env
```

---

## 60. Ubuntu Edge 升级

```bash
cd /opt/Kook_Web_Music
git status
git pull
Ubuntu/.venv/bin/python -m pip install -r Ubuntu/requirements.txt
Ubuntu/.venv/bin/python edge/run.py
```

---

# 第十二部分：回滚

## 61. 什么时候需要回滚

例如升级后：

```text
Cloud 无法启动
Edge 无法启动
WSS 协议不兼容
三平台核心功能严重异常
```

回滚前先保留新版本日志和数据备份。

### 61.1 Git 回滚原则

不要直接删除整个目录再重新部署，因为 `.env`、Cookie 和 `data/` 都是重要持久数据。

应切回确认可用的 Git commit，再恢复对应依赖。

数据库 Schema 如果发生了不可逆升级，必须按照对应版本迁移说明处理，不能只回滚 Python 文件。

---

# 第十三部分：日常运维速查

## 62. Cloud 服务状态

```bash
sudo systemctl status kook-music-cloud --no-pager
sudo systemctl status caddy --no-pager
```

## 63. Cloud 日志

```bash
sudo journalctl -u kook-music-cloud -f
sudo journalctl -u caddy -f
```

## 64. Cloud 内部健康

```bash
curl http://127.0.0.1:18473/healthz
```

## 65. Cloud 端口监听

```bash
sudo ss -lntp | grep -E '(:80 |:18473 |:18476 |:28443 |:2847[0-9] )'
```

## 66. 外部 Web 端口测试

Windows：

```powershell
Test-NetConnection 你的域名 -Port 28443
```

## 67. 外部 WSS 池 TCP 测试

```powershell
28470..28479 | ForEach-Object {
    Test-NetConnection 你的域名 -Port $_ -WarningAction SilentlyContinue |
        Select-Object RemotePort,TcpTestSucceeded
}
```

---

# 第十四部分：最终验收清单

部署人员可以逐项打勾：

```text
[ ] DNS 域名指向 Cloud 公网 IP
[ ] Cloud 80/tcp 可用于 Caddy 证书验证
[ ] Cloud 28443/tcp 已开放
[ ] Cloud 28470-28479/tcp 已开放
[ ] Cloud 没有公网开放 18473/18476
[ ] https://域名:28443/ 可以打开且证书正常
[ ] Cloud 管理员首次登录并修改密码
[ ] Edge Python / Node / FFmpeg 正常
[ ] Edge Local WebUI 可以打开
[ ] Edge Local 管理员首次登录并修改密码
[ ] KOOK Bot 已启动
[ ] 网易云 API 已启动
[ ] QQ API 已启动
[ ] Edge Agent Token 与 Cloud 一致
[ ] Edge WSS 状态 Connected
[ ] Edge 有一个 Active Port，位于 28470-28479
[ ] 端口池检测正常
[ ] Cloud 能看到 Edge 在线
[ ] Cloud Web 可以控制 Edge 播放
[ ] Local WebUI 与 Cloud Web 看到同一个 Queue
[ ] 单个 WSS 端口阻断后能自动切换
[ ] WSS 全池断开时本地 Bot/播放仍继续
[ ] 已完成 Cloud 数据备份
[ ] 已完成 Edge .env/Cookie/data 备份
```

全部完成后，才可以认为 Cloud / Edge 基础部署完成。

---

## 68. 部署人员只需要记住的几个地址

Cloud 公网 Web：

```text
https://你的域名:28443/
```

Cloud 内部 Flask：

```text
127.0.0.1:18473
```

Cloud 内部 Relay：

```text
127.0.0.1:18476
```

Cloud 公网 WSS 池：

```text
28470-28479
```

Edge Local WebUI：

```text
http://127.0.0.1:18473/
```

如果遇到故障，先判断故障属于：

```text
Cloud Web 28443
Cloud WSS 28470-28479
Edge Local Runtime
KOOK Bot
音乐平台
```

再排查对应部分，不要把所有问题都归因到 WSS 或 Cloud。
