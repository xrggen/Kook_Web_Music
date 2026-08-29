# 项目文档

文档只描述当前分支已经实现的行为，不保留版本流水账。根 [README](../README.md) 提供项目入口；完整事实按主题集中维护在本目录。

## 文档索引

| 文档 | 负责内容 |
|---|---|
| [architecture.md](architecture.md) | 进程拓扑、播放会话、媒体管道、并发和恢复机制 |
| [deployment.md](deployment.md) | Windows/Ubuntu 安装、配置、启动、升级、回滚和验证 |
| [authentication.md](authentication.md) | Web 登录、管理员/普通用户、Session、RBAC、Scope 与 SQLite 表设计 |
| [music-platforms.md](music-platforms.md) | 三平台接入方式、登录态与 QQ Credential 生命周期 |
| [web-api.md](web-api.md) | 页面、HTTP API 分类和调用约束 |
| [ui.md](ui.md) | 桌面/移动端共享 UI、主题和前端资源职责 |
| [operations.md](operations.md) | 日志、健康检查、watchdog 与故障处理 |
| [development.md](development.md) | 平台同步、实现约束和维护检查 |
| [security.md](security.md) | 网络、凭据、命令执行与发布安全 |

## 维护原则

1. 同一个事实只在一份专题文档中完整说明，其他位置使用链接。
2. Windows 和 Ubuntu 共用架构、配置语义和 Node 依赖；平台文档只写安装命令与系统差异。
3. 新增服务、环境变量、持久化文件、页面、API 或 Bot 命令时，必须更新对应专题文档。
4. 文档不得包含真实 Token、Cookie、账号密码、频道、签名 URL、内网地址或个人推广链接。
5. 版本变化由 Git 提交和发布记录承载，不在运行文档中复制历史演进。
