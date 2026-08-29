# KOOK Music 项目文档

本目录保存当前项目的结构化技术文档。根目录 `README.md` 继续承担项目简介、快速开始和版本历史；实现细节、部署边界和维护约束统一放在这里。

## 文档索引

- [architecture.md](architecture.md) — 运行时架构、播放链路、线程/事件循环、状态边界与 Windows/Ubuntu 同步原则。
- [deployment.md](deployment.md) — Windows / Ubuntu 安装、Node API、FFmpeg、环境变量、启动与升级流程。
- [music-platforms.md](music-platforms.md) — 网易云、QQ 音乐、Bilibili 的接入方式、账号凭据和播放取链差异。
- [web-api.md](web-api.md) — Web 页面与主要 HTTP API 的职责、参数边界和兼容说明。
- [ui.md](ui.md) — 桌面/移动端 UI 架构、深浅色主题、响应式断点和前端资源职责。
- [operations.md](operations.md) — 日志、健康检查、看门狗、故障恢复、账号失效和常见排障路径。
- [development.md](development.md) — 开发规则、平台同步、测试、提交前检查和高风险修改边界。
- [security.md](security.md) — 当前安全边界、凭据管理、网络暴露风险和部署建议。

## 文档维护规则

1. Windows 运行时是共享实现的权威来源；共享文件变更必须同步 Ubuntu，并通过 `scripts/check_platform_sync.py` 保持字节一致。
2. 文档只描述已经存在于代码中的能力；规划项必须明确标记为“规划”或“未实现”。
3. 新增 HTTP API、机器人命令、环境变量、持久化文件、后台线程或本地服务时，必须同步更新对应专题文档。
4. 不在文档中记录真实 Token、Cookie、UID、服务器 ID、频道 ID、签名 URL 或其他凭据。
5. 根 `README.md` 保持面向使用者；超过几段的实现细节优先迁移到 `/docs`。

## 当前 UI 状态

当前开发分支已经进入桌面与移动端共用模板的响应式架构：

- 桌面端：左侧导航 + 主工作区 + 右侧队列 + 全局播放器。
- 移动端：顶部上下文 + 单主视图 + 底部导航 + 迷你播放器 + Bottom Sheet 队列/菜单。
- 主题：深色、浅色、跟随系统。
- 移动端断点：`max-width: 820px`。

移动端仍应继续做真机视觉与触控回归，但不再采用独立 `mobile.html` 或复制业务逻辑的方案。
