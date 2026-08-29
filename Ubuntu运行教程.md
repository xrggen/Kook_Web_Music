# Ubuntu 运行教程

本文只保留 Ubuntu 平台差异。Node、配置、systemd、反向代理、凭据迁移、升级和验证的完整说明见 [部署指南](docs/deployment.md)。

## 安装系统依赖

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg
node --version
```

Node.js 必须为 20+，且来自系统 PATH。全局安装项目使用的 API：

```bash
sudo npm install --global NeteaseCloudMusicApi@4.25.0 @sansenjian/qq-music-api@2.3.1
```

不要把便携 Node、Node API 源码或 `node_modules` 放入项目目录。

## 安装与启动

```bash
cd Ubuntu
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 create_env.py
python3 run.py
```

`create_env.py` 会创建 `Ubuntu/.env`。Ubuntu 默认从 PATH 解析 `ffmpeg` 和 `ffprobe`。

启动后访问 `http://127.0.0.1:5000/`。日志位于 `Ubuntu/debug.log`、`Ubuntu/netease_api_output.log` 和 `Ubuntu/qq_api_output.log`。

## 登录态

三平台凭据保存在 `Ubuntu/Cookie/`。从其他安装迁移时先停止两边实例，只复制凭据文件，不复制 Node 包配置、日志或 `node_modules`。

## 常见问题

- Node 版本过低：先通过发行版或 Node.js 官方渠道升级系统 Node。
- 全局包无权限：确保运行用户可读取 `npm root --global` 返回的目录。
- FFmpeg 未找到：检查 `command -v ffmpeg`，或在 `.env` 配置绝对路径。
- 端口冲突：用 `ss -ltnp` 确认 PID，只停止已确认属于旧实例的进程。
- 后台服务：使用 [systemd 示例](docs/deployment.md#ubuntu-systemd)，不要依赖长期运行的交互终端。
