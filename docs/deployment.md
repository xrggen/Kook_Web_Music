# 部署与启动

## 1. 运行边界

Windows 与 Ubuntu 是两个可独立部署的运行目录。不要跨平台共享 `venv`、`node_modules`、FFmpeg 二进制或 Cookie 文件。

### Windows

```powershell
cd windows
python run.py
```

### Ubuntu

```bash
cd Ubuntu
python3 run.py
```

启动入口没有因 UI、移动端或账号续期改造而改变。

## 2. 前置依赖

共同依赖：

- Python 3.8+
- Node.js + npm
- KOOK Bot Token
- 可访问 KOOK、音乐平台和 CDN 的网络

Windows：

- 项目使用 `windows/ffmpeg/bin` 下的 FFmpeg/ffprobe（若配置有效）。

Ubuntu：

- 推荐系统安装 `ffmpeg` / `ffprobe`。

## 3. Python 依赖

在目标平台目录中安装：

```bash
pip install -r requirements.txt
```

Ubuntu 推荐先创建虚拟环境：

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 4. Node 音乐 API

源码已经纳入仓库，但 `node_modules` 不应提交，需要在目标机器安装。

### 网易云

目录：

```text
NeteaseCloudMusicApi/NeteaseCloudMusicApiBackup-main
```

安装：

```bash
npm install
```

`run.py` 默认将其以 `PORT=3000` 启动。

### QQ 音乐

目录：

```text
qq-music-api
```

安装并构建：

```bash
npm install
npm run build
```

如果 `dist/app.js` 不存在，`run.py` 会尝试执行构建。默认端口为 3200。

### Bilibili

没有独立 Node 服务。`bili_utils.py` 直接调用：

- `https://api.bilibili.com`
- `https://passport.bilibili.com`
- `https://www.bilibili.com`

因此不要为了“对齐三平台”额外部署一个未被代码使用的 Bilibili API 进程。

## 5. `.env`

推荐从当前平台目录执行：

```bash
python create_env.py
```

或根据 `.env.example` 手工配置。

关键项：

- `BOT_TOKEN`
- `HOST` / `PORT`
- `FFMPEG_PATH` / `FFPROBE_PATH`
- `MUSIC_API_BASE`
- `QQ_MUSIC_API_BASE`
- `QQ_COOKIE_PATH`
- `BILI_COOKIE_PATH`
- `ALLOWGROUP` / `ALLOWCHANNEL` / `ALLOWUSER`
- watchdog 参数
- QQ Credential 自动续期参数（若未配置则使用代码默认值）

相对路径应以平台目录为基准，不依赖启动终端的当前目录。

## 6. 首次启动检查

启动日志至少应确认：

1. `.env` 正确加载。
2. Node 和 npm 可解析。
3. 网易云 API 能启动或明确回退至 `MUSIC_API_BASE`。
4. QQ API 能启动并通过基本探针。
5. FFmpeg 路径存在。
6. Bot Token 验证成功。
7. Flask Web 端口监听成功。

访问：

```text
http://<HOST>:<PORT>/
```

## 7. 升级流程

建议：

1. 停止当前进程。
2. 备份 `.env` 和 `Cookie/`。
3. 拉取新代码。
4. 如 `requirements.txt` 改变，重新安装 Python 依赖。
5. 如两个 Node API 的 `package.json` / lockfile 改变，重新安装依赖并构建。
6. 启动 `run.py`。
7. 检查 `/status`、账号状态和至少一次搜索/入队。

QQ 音乐升级到 Credential Manager 后，旧 `qq_cookie.txt` 可自动迁移；不需要为了升级主动删除现有登录态。

## 8. 网络暴露

当前 `HOST` 默认值可能使 Web 服务监听所有网卡。Web API 中包含播放控制、账号管理和部分运维能力，因此不建议未经额外访问控制直接暴露到公网。

更安全的部署方式见 [security.md](security.md)。
