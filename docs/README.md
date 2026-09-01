# 项目文档

文档只描述当前分支已经实现的行为，不保留版本流水账。根 README 只提供项目入口；工程交接信息始终维护在本目录。

## 接手入口

1. [HANDOFF.md](HANDOFF.md)
2. [cloud-edge-architecture.md](cloud-edge-architecture.md)
3. [cloud-edge-deployment.md](cloud-edge-deployment.md)
4. [authentication.md](authentication.md)
5. [security.md](security.md)
6. [operations.md](operations.md)

> 如果任务是“安装或部署系统”，即使没有 Linux、Python、Node.js、Caddy、WSS 或服务器运维经验，也应直接从 [cloud-edge-deployment.md](cloud-edge-deployment.md) 开始。该文档按零基础人员可逐步执行的方式编写，并为每一步给出验证和常见故障处理。

## 当前核心事实

- 公网 Web UI 使用 HTTPS 443。
- Edge WSS 使用独立非标准公网端口池，默认 `28470-28479`。
- Edge 任意时刻只维持一条 Active WSS，并在网络型端口故障时自动切换。
- Edge 保留完整 v2 本地 WebUI；Cloud/WSS 不是本地 Bot/播放能力的运行前提。
- Edge 本地设置页可维护 Cloud 主机、WSS 端口池、Agent 身份/TLS/Token。
- Agent Token 不通过读取 API 回显，动态配置和 Secret 留在 Edge `data/`。
- Handoff 不写入项目根 README。

## 文档索引

| 文档 | 负责内容 |
|---|---|
| [HANDOFF.md](HANDOFF.md) | 当前工程交接、关键实现、运行数据、质检边界 |
| [cloud-edge-architecture.md](cloud-edge-architecture.md) | 双控制面、WSS 端口池、Agent Supervisor、状态同步、故障与安全边界 |
| [cloud-edge-deployment.md](cloud-edge-deployment.md) | 面向零基础部署人员的完整 Cloud/Edge 安装、域名、DNS、防火墙、Caddy、443 Web、28470-28479 WSS、Windows/Ubuntu Edge、本地 WebUI、验证、排错、备份、升级和回滚步骤 |
| [security-hardening.md](security-hardening.md) | 深度审计问题、修复与验证证据 |
| [architecture.md](architecture.md) | 单机兼容模式与播放核心 |
| [deployment.md](deployment.md) | Windows/Ubuntu 单机兼容部署 |
| [authentication.md](authentication.md) | 登录、Session、CSRF、Admin/User、Scope、IAM |
| [music-platforms.md](music-platforms.md) | 网易/QQ/Bilibili 与 Credential 生命周期 |
| [web-api.md](web-api.md) | HTTP API 与鉴权约束 |
| [ui.md](ui.md) | 桌面/移动 UI 与主题 |
| [operations.md](operations.md) | 日志、SQLite、健康、备份和故障处理 |
| [development.md](development.md) | 开发与同步约束 |
| [security.md](security.md) | 网络、身份、凭据、RCE 与秘密扫描 |

## 维护原则

1. 同一个事实只在一份专题文档中完整说明，其他位置使用链接。
2. Cloud/Edge 端口、环境变量、持久化文件、协议 Action、页面/API 或安全边界变化时，必须同步更新对应专题。
3. 文档不得包含真实 Token、Cookie、Credential、Session/CSRF、账号密码、签名 URL 或其他秘密。
4. 版本变化由 Git 提交承载；Handoff 只记录当前状态。
5. 根 README 不承载工程 handoff。
