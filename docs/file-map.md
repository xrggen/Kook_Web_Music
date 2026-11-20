# 项目文件地图

路径以仓库根目录为起点。播放端的 Windows 和 Ubuntu 目录共享运行逻辑，修改共享实现时需要同步对应文件。

| 查找目标 | 入口 | 继续查 |
| --- | --- | --- |
| 播放端启动、本地 API、进程监督 | [windows/run.py](../windows/run.py) · [Ubuntu/run.py](../Ubuntu/run.py) | `config.py`、`runtime_health.py`、`service_watchdog.py` |
| Web 与 Bot 指令 | [windows/app.py](../windows/app.py) | `routes.py`、`api.py`、`bot_gateway.py` |
| 控制台账号、权限、微信绑定 | [windows/auth.py](../windows/auth.py) | [鉴权](authentication.md)、[Web API](web-api.md) |
| 页面、样式和前端脚本 | [windows/templates/](../windows/templates/) · [windows/static/](../windows/static/) | `_app_early_ui.html`、`theme-init.js`、`auth-client.js` |
| 队列、FFmpeg、RTP、KOOK 语音 | [windows/kookvoice/](../windows/kookvoice/) | `kookvoice.py` 管理播放，`requestor.py` 调用语音服务 |
| 音乐平台、搜索、账号登录 | [windows/](../windows/) · [Ubuntu/](../Ubuntu/) | `utils.py` / `account_api.py`（网易云），`qq_utils.py` / `qq_account_api.py`，`bili_utils.py` / `bili_account_api.py` |
| Cloud Web、Relay、路由缓存 | [cloud/run.py](../cloud/run.py) · [cloud/app.py](../cloud/app.py) | `relay.py`、`runtime_proxy.py`、`agent_registry.py`。Web 页面和鉴权复用 `windows/` |
| Edge 启动、重连、设置 | [edge/run.py](../edge/run.py) · [edge/agent.py](../edge/agent.py) | `local_control.py` 调用本地 Web API，`management.py` 提供管理入口，`templates/` 提供 Edge 设置页 |
| Cloud / Edge 协议 | [shared/relay_protocol.py](../shared/relay_protocol.py) | 消息封装、业务动作白名单、超时与校验 |
| 微信小程序 | [wechat-miniapp/](../wechat-miniapp/) | `tool.json` 描述宿主入口，`pages/console/` 为原生页面，`services/` 处理请求与管理，`utils/` 处理映射与布局 |
| 回归测试 | [windows/tests/](../windows/tests/) · [Ubuntu/tests/](../Ubuntu/tests/) · [cloud/tests/](../cloud/tests/) · [edge/tests/](../edge/tests/) · [wechat-tests/](../wechat-tests/) | 测试播放、鉴权、Relay、启动、微信客户端 |
| 提交前验证 | [scripts/](../scripts/) · [.github/workflows/](../.github/workflows/) | 平台同步、凭据扫描和 CI |

各角色根据对应目录的 `.env.example` 创建运行配置。`.env`、`Cookie/` 实际凭据、`data/` 数据库、日志、虚拟环境和全局 Node 包属于运行环境，发布只包含源码、文档、配置模板及测试。
