# 开发与维护

## 平台一致性

`windows/` 与 `Ubuntu/` 是同一应用的两个部署目录，不是两套产品。共享文件由 `scripts/check_platform_sync.py` 管理：

```bash
python scripts/check_platform_sync.py
```

共享范围包括 Python 业务、Auth、路由、Bot 命令、模板、静态资源、配置模板和测试。平台差异只允许出现在 FFmpeg 来源、系统路径、服务管理和平台说明。

修改共享文件时应在同一变更中同步两端。不要让一个平台长期携带修复而另一个平台保持不同逻辑。

Windows 是权威主线；新业务逻辑应先在共享实现中收敛，再同步 Ubuntu 对应文件。

## Node 依赖政策

- 只支持系统 PATH 中的 Node.js 20+ 与 npm。
- Node API 从 `npm root --global` 加载固定版本。
- 仓库不保存 Node API 源码、Node 可执行文件或 `node_modules`。
- Python 启动器不执行 npm 安装或构建。
- 用户 Cookie 不写入全局 npm 包目录。

修改 Node 启动逻辑时必须同时更新部署、架构和两个平台入口；项目根 README 只保留入口性说明，不承载 handoff。

## Web Auth 维护规则

鉴权核心位于 `auth.py`，由 `api.py` 在现有路由注册后统一安装。

新增页面/API 时必须先回答：

1. 是否公开？默认答案应为否。
2. 最低 Role 是 Admin 还是 User？
3. 如果是 User，是否属于 `playback.read` 或 `playback.control`？
4. 是否需要 `guild_id` / `channel_id` 才能精确执行 Scope？
5. 是否为写请求，需要 CSRF？
6. 是否应写审计？
7. 返回数据是否包含凭据或可推导敏感信息？

不要在业务路由里通过“临时跳过 Middleware”解决授权问题。若确实需要普通用户读取某个账号只读接口，应将最小路径加入明确 allowlist，并保证响应不含 Cookie/Credential。

### 密码与 Session

- 不实现明文密码存储。
- 不打印密码、临时密码、Session Token、CSRF Token。
- 修改角色、启用状态或密码时必须使旧 Session 失效。
- 新增恢复工具时只能生成/设置新 Hash，不读取原密码。
- 不通过删除 SQLite 数据库实现管理员恢复。

### Scope

普通用户 playback Scope 只有：

```text
*
guild:<id>
channel:<guild>/<channel>
```

新增播放 API 必须携带足够的 Guild/Channel 上下文；否则无法执行资源级授权。

### SQLite

控制面数据库不是播放状态数据库。不要把高频播放进度、PCM/Opus 数据或每秒队列状态写入 SQLite。

未来变更 Schema 时，不应只依赖新的 `CREATE TABLE IF NOT EXISTS`。应增加明确、顺序化、可测试的 Schema Migration，并在部署/回滚文档说明兼容性。

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

SQLite 连接应保持短事务。不要在数据库事务内执行音乐平台公网请求、FFmpeg 等待或 KOOK 网络 I/O。

## 媒体子进程

- 使用参数数组和 `shell=False`。
- 创建时保存进程引用和归属。
- 正常、超时、取消和异常路径都执行幂等回收。
- 等待进程退出并关闭管道。
- 不按进程名或端口误杀其他应用。

运行日志接口只允许读取增量输出；项目不提供远程 shell 命令执行能力。

## 前端

- 桌面和移动端共用模板、API 和业务 JS。
- 登录、强制改密和用户管理同样使用共享模板，不新增平台分叉。
- 移动差异放入 `mobile.css`、`mobile-polish.css` 和 `mobile-ui.js`。
- 外部数据默认通过 `textContent` 写入 DOM。
- 异步请求使用序列或上下文校验。
- 新控件提供可访问名称和足够触控区域。
- 所有同源写请求应继续通过 `auth-client.js` 获取 CSRF，不在业务脚本中复制 Token 管理逻辑。

UI 隐藏不是授权。任何 Admin-only 功能都必须有后端 Role 校验。

## 账号与 API

凭据只保存在服务端受忽略文件中，不写日志、前端存储或普通 API 响应。修改 QQ Credential Manager 时保持 `qq_cookie.txt` 与 `qq_credential.json` 的一致写入和迁移能力。

修改 HTTP API 时：

1. 查找 Web、Bot 和脚本调用点。
2. 确定 Role/Scope/CSRF。
3. 保持现有字段兼容，或提供明确迁移。
4. 同步两个平台。
5. 更新 [web-api.md](web-api.md)、[authentication.md](authentication.md) 与 [security.md](security.md)。

## 秘密扫描

`scripts/check_secrets.py` 扫描当前 tracked 文件以及全部可达 Git 历史对象和 Commit Message。

增加新的秘密类型或运行数据文件时，应同时更新：

- `.gitignore`；
- `scripts/check_secrets.py` 的敏感路径/模式；
- `.env.example`；
- `security.md`；
- CI。

扫描器不得把秘密值打印到日志。

## 检查

最低检查：

```bash
python scripts/check_secrets.py
python scripts/check_platform_sync.py
python -m compileall windows Ubuntu
```

双平台测试：

```bash
python -m unittest discover -s windows/tests -p "test_*.py"
python -m unittest discover -s Ubuntu/tests -p "test_*.py"
```

Auth 变更至少覆盖：

- 空库 Bootstrap 管理员；
- 密码 Hash/校验；
- 首次登录强制改密；
- 未登录页面/API；
- Admin/User 页面边界；
- Global/Guild/Channel Scope；
- CSRF；
- 登录限速；
- 用户禁用/角色/密码变化后的 Session 失效；
- Windows/Ubuntu 同步。

前端变更还应覆盖桌面/移动、深色/浅色、窄屏、横屏、软键盘和播放器/队列交互。

## 文档

文档只维护当前实现。新增或删除服务、变量、文件、页面、接口、命令、线程、锁、SQLite 表或恢复流程时，更新对应专题文档。

项目交接信息集中维护在 `docs/HANDOFF.md`，不把 handoff 堆入项目根 README。发布演进交由 Git 与发布系统记录。
