# Ubuntu 运行目录

本目录是 Ubuntu 部署单元，与 `windows/` 共用业务实现和系统 Node 机制。

## 启动

从仓库根目录执行：

```bash
cd Ubuntu
./.venv/bin/python run.py
```

首次安装请先阅读根目录 [Ubuntu 运行教程](../Ubuntu运行教程.md)；完整配置、systemd、迁移、升级和验证流程见 [部署指南](../docs/deployment.md)。

## Ubuntu 差异

- 从系统 PATH 解析 `ffmpeg` 与 `ffprobe`。
- `run.py` 从系统 PATH 查找 Node.js 20+，并从 `npm root --global` 加载固定的网易云和 QQ API 包。
- 推荐由 systemd 管理 Python 主进程，Node API 由 `run.py` 作为子进程统一管理。
- Ubuntu 提供额外的 `/monitor` 页面。

## 本地数据

- `.env`：实例配置和 KOOK Token。
- `Cookie/`：三平台登录态。
- `debug.log`：Python/Bot/Web 日志。
- `netease_api_output.log`、`qq_api_output.log`：系统 Node API 输出。

这些运行数据不得提交 Git。项目目录内不得存在 `node_modules` 或自带 Node。
