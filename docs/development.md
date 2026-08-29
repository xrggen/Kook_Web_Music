# 开发与维护

## 平台一致性

`windows/` 与 `Ubuntu/` 是同一应用的两个部署目录，不是两套产品。共享文件由 `scripts/check_platform_sync.py` 管理：

```bash
python scripts/check_platform_sync.py
```

共享范围包括 Python 业务、路由、Bot 命令、模板、静态资源、配置模板和测试。平台差异只允许出现在 FFmpeg 来源、系统路径、服务管理和平台说明。

修改共享文件时应在同一变更中同步两端。不要让一个平台长期携带修复而另一个平台保持不同逻辑。

## Node 依赖政策

- 只支持系统 PATH 中的 Node.js 20+ 与 npm。
- Node API 从 `npm root --global` 加载固定版本。
- 仓库不保存 Node API 源码、Node 可执行文件或 `node_modules`。
- Python 启动器不执行 npm 安装或构建。
- 用户 Cookie 不写入全局 npm 包目录。

修改 Node 启动逻辑时必须同时更新根 README、部署、架构和两个平台入口。

## 并发与状态

播放状态以 `channel_id` 为键，修改队列、当前播放或处理器注册表时必须使用 `kookvoice.state_lock` 和所有权校验。

推荐顺序：

```text
锁内读取状态与操作标识
    ↓
锁外执行网络或媒体 I/O
    ↓
锁内确认状态仍属于当前操作
    ↓
提交结果
```

禁止在锁内执行长时间公网请求，也禁止旧处理器退出时无条件清理新会话。

## 媒体子进程

- 使用参数数组和 `shell=False`。
- 创建时保存进程引用和归属。
- 正常、超时、取消和异常路径都执行幂等回收。
- 等待进程退出并关闭管道。
- 不按进程名或端口误杀其他应用。

## 前端

- 桌面和移动端共用模板、API 和业务 JS。
- 移动差异放入 `mobile.css`、`mobile-polish.css` 和 `mobile-ui.js`。
- 外部数据默认通过 `textContent` 写入 DOM。
- 异步请求使用序列或上下文校验。
- 新控件提供可访问名称和足够触控区域。

## 账号与 API

凭据只保存在服务端受忽略文件中，不写日志、前端存储或 API 普通响应。修改 QQ Credential Manager 时保持 `qq_cookie.txt` 与 `qq_credential.json` 的一致写入和迁移能力。

修改 HTTP API 时：

1. 查找 Web、Bot 和脚本调用点。
2. 保持现有字段兼容，或提供明确迁移。
3. 同步两个平台。
4. 更新 [web-api.md](web-api.md) 与安全说明。

## 检查

按变更范围执行：

```bash
python -m compileall windows Ubuntu
python scripts/check_platform_sync.py
python scripts/check_secrets.py
```

单元测试位于两个平台的 `tests/`。前端变更还应覆盖桌面/移动、深色/浅色、窄屏、横屏、软键盘和播放器/队列交互。

## 文档

文档只维护当前实现。新增或删除服务、变量、文件、页面、接口、命令、线程、锁或恢复流程时，更新对应专题文档；发布演进交由 Git 与发布系统记录，不复制到 README。
