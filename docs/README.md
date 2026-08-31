# 项目文档

文档只描述当前分支已经实现的行为，不保留版本流水账。根 [README](../README.md) 只提供项目入口；完整事实与工程交接信息集中维护在本目录。

## 接手入口

新接手开发、审计或部署工作时，先读：

1. [HANDOFF.md](HANDOFF.md)
2. [authentication.md](authentication.md)
3. [security.md](security.md)
4. [architecture.md](architecture.md)
5. [deployment.md](deployment.md)

`HANDOFF.md` 记录当前已验证实现基线、近期完成工作、关键文件、运行数据、接手顺序和已知风险。Handoff 只放在 `docs/`，不写入项目根 README。

## 文档索引

| 文档 | 负责内容 |
|---|---|
| [HANDOFF.md](HANDOFF.md) | 当前工程交接、已验证基线、关键实现、风险与推荐后续工作 |
| [security-hardening.md](security-hardening.md) | 深度审计问题、逐项修复、兼容性变化、代码位置与验证证据 |
| [architecture.md](architecture.md) | 进程拓扑、Web 控制面持久化、播放会话、媒体管道、并发和恢复机制 |
| [deployment.md](deployment.md) | Windows/Ubuntu 安装、Auth/SQLite 配置、启动、升级、回滚和验证 |
| [authentication.md](authentication.md) | Web 登录、Session、CSRF、管理员/普通用户、RBAC、Scope、SQLite IAM 与审计 |
| [music-platforms.md](music-platforms.md) | 三平台接入方式、登录态与 QQ Credential 生命周期 |
| [web-api.md](web-api.md) | 页面、HTTP API、鉴权状态码、Role/Scope/CSRF 调用约束 |
| [ui.md](ui.md) | 桌面/移动共享 UI、登录/改密/用户管理、主题和前端资源职责 |
| [operations.md](operations.md) | 日志、审计、SQLite 运维、健康检查、watchdog、备份与故障处理 |
| [development.md](development.md) | 平台同步、Auth 开发约束、安全检查与维护规则 |
| [security.md](security.md) | 网络、身份、凭据、RCE 边界、秘密扫描与发布安全 |

## 维护原则

1. 同一个事实只在一份专题文档中完整说明，其他位置使用链接。
2. Windows 和 Ubuntu 共用架构、Auth、配置语义和 Node 依赖；平台文档只写安装命令与系统差异。
3. 新增服务、环境变量、持久化文件、SQLite 表、页面、API、Role/Scope 或 Bot 命令时，必须更新对应专题文档。
4. 文档不得包含真实 Token、Cookie、Credential、Session/CSRF、账号密码、频道、签名 URL、内网地址或个人推广链接。
5. 临时密码与 Bootstrap 初始密码只能通过安全交付渠道传递，不进入 Git 文档。
6. 版本变化由 Git 提交和发布记录承载；Handoff 记录接手所需“当前状态”，不复制完整历史流水账。
7. 根 README 不承载工程 handoff；交接始终维护在 `docs/HANDOFF.md`。
