# Windows 运行目录

本目录是 Windows 部署单元，与 `Ubuntu/` 共用业务实现和系统 Node 机制。

## 启动

从仓库根目录执行：

```powershell
cd windows
.\.venv\Scripts\python.exe run.py
```

首次安装请先阅读根目录 [Windows 运行教程](../Windows运行教程.md)；完整配置、迁移、升级和验证流程见 [部署指南](../docs/deployment.md)。

## Windows 差异

- 优先使用 `ffmpeg/bin/ffmpeg.exe` 与 `ffprobe.exe`，缺失时从系统 PATH 解析。
- `run.py` 从系统 PATH 查找 Node.js 20+，并从 `npm root --global` 加载固定的网易云和 QQ API 包。
- 3000、3200 的残留进程清理会检查端口和进程归属；不要手工批量结束所有 Node 进程。
- `/monitor` 不是 Windows 页面，访问时返回 404。

## 本地数据

- `.env`：实例配置和 KOOK Token。
- `Cookie/`：三平台登录态。
- `debug.log`：Python/Bot/Web 日志。
- `netease_api_output.log`、`qq_api_output.log`：系统 Node API 输出。

这些运行数据不得提交 Git。项目目录内不得存在 `node_modules` 或自带 Node。
