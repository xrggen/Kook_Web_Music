# Windows 运行教程

本文只保留 Windows 平台差异。Node、配置、凭据迁移、升级和验证的完整说明见 [部署指南](docs/deployment.md)；升级兼容性和安全行为变化见 [安全审计修复基线](docs/security-hardening.md)。

## 前置检查

```powershell
node --version
npm --version
```

Node.js 必须为 20+，且来自系统 PATH。全局安装项目使用的 API：

```powershell
npm install --global NeteaseCloudMusicApi@4.25.0 @sansenjian/qq-music-api@2.3.1
```

不要在项目目录安装 Node 依赖，也不要放置便携 Node 或 `node_modules`。

## 安装与启动

```powershell
cd windows
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python create_env.py
python run.py
```

`create_env.py` 会创建 `windows/.env`。Windows 默认优先使用 `windows/ffmpeg/bin`，也可以在 `.env` 中显式配置系统 FFmpeg。

启动后访问 `http://127.0.0.1:18473/`。日志位于 `windows/debug.log`、`windows/netease_api_output.log` 和 `windows/qq_api_output.log`。

## 登录态

三平台凭据保存在 `windows/Cookie/`。从其他安装迁移时先停止两边实例，只复制凭据文件，不复制 Node 包配置、日志或 `node_modules`。

## 常见问题

- 端口冲突：确认 18473、18474、18475 的占用 PID，再只停止旧的本项目实例。
- Node 包未找到：重新检查 `npm root --global` 和全局安装版本。
- FFmpeg 未找到：检查随包文件或设置 `FFMPEG_PATH`、`FFPROBE_PATH`。
- PowerShell 无法激活 venv：直接运行 `.\.venv\Scripts\python.exe run.py`。
