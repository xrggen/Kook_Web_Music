# 开发与维护约束

## 1. 分支与实现原则

当前共享运行时采用 Windows 主线：先在 `windows/` 形成正确实现，再同步 `Ubuntu/` 对应共享文件。不要让两个平台长期形成不同业务版本。

本项目当前开发流程允许直接向工作分支提交；是否创建 PR、跑 CI 或做发布审计由具体任务决定。

## 2. 平台同步

执行：

```bash
python scripts/check_platform_sync.py
```

脚本检查共享文件是否字节一致。新增共享文件时必须加入 `SHARED_FILES`。

适合保持共享的内容：

- Python 业务逻辑。
- Flask 路由。
- KOOK Bot 命令。
- 前端模板、CSS、JS。
- 测试。

允许平台差异：

- FFmpeg 二进制和系统路径。
- 安装/打包脚本。
- 平台专属部署文档。

## 3. 并发状态修改

任何修改播放队列、当前播放状态、处理器注册表的代码都必须尊重 `kookvoice.state_lock` 和现有所有权模型。

禁止：

- 在锁外直接修改共享队列后假设不会竞争。
- 旧 PlayHandler 退出时无条件清理当前频道状态。
- 在锁内执行长时间公网请求。

推荐模式：

```text
锁内读取标记/状态
   ↓
锁外网络或媒体操作
   ↓
锁内确认状态仍属于当前操作
   ↓
回填结果
```

## 4. 媒体进程

创建 FFmpeg/ffprobe 时：

- 使用参数数组，避免 shell。
- 保存进程引用。
- 超时/取消/异常路径都要回收。
- 等待进程结束并处理管道。
- Windows 不得仅凭进程名或端口误杀其他应用。

## 5. 前端修改

核心原则：桌面/移动端共用业务逻辑。

- 不复制 `dashboard.js` 为 `mobile-dashboard.js`。
- 移动端特有的布局/Sheet 行为放在 `mobile.css`、`mobile-polish.css`、`mobile-ui.js`。
- DOM 中展示外部数据优先 `textContent`。
- 异步搜索、频道切换继续使用请求序列/上下文校验，防止旧响应覆盖新状态。
- 新增触控按钮应有 `aria-label`，命中区域优先达到 44px。

## 6. 账号与凭据

凭据文件只在服务端：

- 不写到 localStorage。
- 不提交 Git。
- 不把完整值放进日志。

修改 QQ Credential Manager 时必须保留旧 `qq_cookie.txt` 兼容路径，除非一次性完成所有调用点迁移并有明确升级策略。

## 7. API 兼容性

修改已有 HTTP API 时优先向后兼容。若必须破坏字段：

1. 查找 Web 和 Bot 两侧调用点。
2. 更新文档。
3. 给出迁移路径。
4. 避免只修 Web、遗漏 KOOK 命令链路。

## 8. 推荐检查

按修改范围选择：

```bash
python -m compileall windows Ubuntu
python scripts/check_platform_sync.py
```

以及对应单元测试，例如：

```bash
python -m unittest windows.tests.test_stability
python -m unittest windows.tests.test_watchdog
python -m unittest windows.tests.test_qq_credential
```

前端修改还需要浏览器回归：

- 桌面深色/浅色。
- 移动端深色/浅色。
- 390px 级手机宽度。
- 横屏。
- 软键盘。
- 队列 Sheet 和全屏播放器。

## 9. 文档更新

以下变化视为“必须更新 `/docs`”：

- 新增/删除本地服务。
- 新增环境变量。
- 新增持久化文件。
- 新增一级页面。
- 新增重要 API 或 KOOK 命令。
- 修改平台接入方式。
- 修改播放线程、锁、watchdog 或恢复流程。
- 修改移动端断点或主题机制。
