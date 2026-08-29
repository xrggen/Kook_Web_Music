# KOOK 音乐机器人 Web 控制台

基于 [VexMare/Kook_Web_Music](https://github.com/VexMare/Kook_Web_Music) 持续维护的自托管 KOOK 音乐机器人，提供响应式 Web 控制台，并接入网易云音乐、QQ 音乐和 Bilibili。

## 主要能力

- 通过 KOOK 命令或 Web 控制台搜索、入队和控制播放。
- 按语音频道隔离播放会话，同一服务器可并行管理多个频道。
- 支持歌单延迟解析、预取、单曲循环、列表循环和随机播放。
- 提供三平台账号登录、歌单读取与服务端凭据持久化。
- 提供运行状态、日志和分级 watchdog 恢复。
- 桌面端与移动端共用页面、状态和 API。

## 运行架构

```text
浏览器 / KOOK 命令
        │
        ▼
Python 应用（Flask + KOOK Bot）
        │
        ├─ 网易云：系统 Node → 全局 NeteaseCloudMusicApi → 3000
        ├─ QQ 音乐：系统 Node → 全局 qq-music-api → 3200
        └─ Bilibili：Python 直连公网 API
        │
        ▼
每个 channel_id 一个播放会话
        │
        ▼
FFmpeg 解码 / Opus 编码 → RTP → KOOK 语音频道
```

仓库不包含 Node 运行时、Node API 源码或 `node_modules`。项目内所有 Node API 都由 `run.py` 使用主机 PATH 中的同一个系统 Node.js 启动，并从 `npm root --global` 解析依赖。

完整机制见 [运行时架构](docs/architecture.md)。

## 环境要求

- Python 3.8+，建议使用当前受支持的 Python 3 版本。
- 系统 Node.js 20+ 与 npm。
- FFmpeg 和 ffprobe。
- KOOK Bot Token。
- 可访问 KOOK 与三方音乐平台的网络。

全局安装固定的 Node API：

```bash
npm install --global NeteaseCloudMusicApi@4.25.0 @sansenjian/qq-music-api@2.3.1
```

## 快速启动

### Windows

```powershell
cd windows
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python create_env.py
python run.py
```

Windows 优先使用 `windows/ffmpeg/bin` 中的 FFmpeg；不存在时再从 PATH 解析。

### Ubuntu

```bash
cd Ubuntu
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 create_env.py
python3 run.py
```

Ubuntu 默认从 PATH 解析 `ffmpeg` 和 `ffprobe`。

启动后访问 `http://127.0.0.1:5000/`。首次部署、systemd、反向代理、升级与验证步骤见 [部署指南](docs/deployment.md)。

## 配置与数据

每个平台目录都是独立部署单元：

- `windows/.env` 或 `Ubuntu/.env`：Bot、Web、API、权限和 watchdog 配置。
- `windows/Cookie/` 或 `Ubuntu/Cookie/`：三平台登录态。
- 平台目录下的 `debug.log`、`netease_api_output.log`、`qq_api_output.log`：运行日志。

凭据只保存在服务端，不写入全局 npm 包目录，也不应提交 Git。跨安装同步登录态时只复制 Cookie 目录中的凭据文件，具体清单见 [部署指南](docs/deployment.md#迁移已有登录态)。

## 项目目录

```text
.
├─ windows/                 Windows 运行目录与随包 FFmpeg
├─ Ubuntu/                  Ubuntu 运行目录
├─ docs/                    架构、部署、接口和运维文档
├─ scripts/                 平台一致性与秘密扫描脚本
├─ Windows运行教程.md       Windows 最短部署入口
└─ Ubuntu运行教程.md        Ubuntu 最短部署入口
```

Windows 与 Ubuntu 的共享 Python、模板、前端和测试文件应保持一致；平台差异只保留在媒体工具、系统服务和部署说明中。

## 文档

- [文档索引](docs/README.md)
- [架构与运行机制](docs/architecture.md)
- [完整部署流程](docs/deployment.md)
- [运维与故障恢复](docs/operations.md)
- [音乐平台与凭据](docs/music-platforms.md)
- [Web 页面与 API](docs/web-api.md)
- [开发与平台同步](docs/development.md)
- [安全边界](docs/security.md)

## 安全

默认按可信网络内自托管设计。建议本机部署时设置 `HOST=127.0.0.1`；需要远程访问时，应置于带认证和 TLS 的反向代理、VPN 或零信任访问层之后。不要直接向公网暴露 3000、3200 或未经认证的 5000 端口。

发布前执行：

```bash
python scripts/check_secrets.py
```

## 许可证

本项目使用 [MIT License](LICENSE)。
