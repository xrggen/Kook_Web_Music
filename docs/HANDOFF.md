# 工程 Handoff

生成日期：2026-08-31

工作分支：`refactor/desktop-ui-v2`

本文以当前分支工作树为准；接手时先读取当前分支 HEAD、工作区差异和部署配置，不把历史提交当作运行时配置依据。

> 安全约束：本文以及仓库其他文档不得记录真实 Bot Token、Cookie、Credential、Session Token、CSRF Token、管理员明文密码或签名媒体 URL。Bootstrap 管理员初始密码只能通过部署 Secret 或受限本地凭据文件提供，不进入 Git。

## 1. 当前系统状态

项目是 Windows/Ubuntu 双部署目录、共享业务实现的 KOOK 音乐控制服务：

- Flask 提供 Web 控制面和 HTTP API；
- KOOK Bot 维护命令和网关连接；
- 网易云与 QQ 使用本机 Node API；Bilibili 直接访问公网 API；
- 播放状态继续驻留内存，以 `channel_id` 为主键；
- Web 身份、Session、Scope、登录尝试和审计日志持久化到 SQLite；
- FFmpeg/Opus/RTP 播放链路没有迁入数据库。

Windows 是共享实现的权威主线；`scripts/check_platform_sync.py` 要求 Windows/Ubuntu 的共享 Python、模板、静态资源和测试保持字节一致。

## 2. 本轮已完成工作

### 2.1 仓库秘密审计

`scripts/check_secrets.py` 已接入 `.github/workflows/platform-sync.yml`，CI 使用 `actions/checkout` 的完整历史检出，对以下范围执行扫描：

- 当前所有 tracked 文件；
- 所有可达 Git Blob；
- Commit Message；
- 敏感路径；
- 私钥、常见平台 Token、JWT、Authorization 值、凭据 URL、真实环境变量秘密赋值等模式。

第三方依赖作者邮箱、历史教程示例值和 npm/yarn lockfile 高熵串被归类为隐私/启发式告警，不作为凭据失败。扫描输出只报告类型与位置，不回显匹配值。

发布前由 CI 或本地执行秘密扫描、平台同步、Python 编译和双平台单元测试；结果以当前提交和当前运行环境为准。

### 2.2 Web 控制面鉴权

核心实现：`windows/auth.py` 与 `Ubuntu/auth.py`。

`api.py` 在 Blueprint 注册阶段调用 `register_auth(app)`，因此鉴权以统一 `before_request` / `after_request` Middleware 覆盖现有页面和 API，而没有给播放函数逐个增加装饰器。

已实现：

- 本地用户名/密码；
- `admin` / `user` 两种角色；
- playback Global/Guild/Channel Scope；
- SQLite Session；
- CSRF；
- 登录失败限速；
- 首次登录强制改密；
- 用户创建、禁用、角色修改、Scope 修改、密码重置、删除；
- `auth_version` 驱动的旧 Session 立即失效；
- 审计日志；
- 安全响应头；
- 桌面/移动共享登录、改密、用户管理 UI。

### 2.3 深度审计修复基线

本分支已完成授权资源绑定、应用工厂、管理员并发不变量、Bot 默认授权、媒体 URL、第三方重定向、请求/队列上限、凭据原子写入、DOM XSS、日志脱敏和系统 Node 收缩等修复。Web 与 KOOK Bot 的通用命令执行能力以及 `/cmd` 已取消。

完整问题矩阵、代码级修法、部署兼容性与后续约束集中记录在 [security-hardening.md](security-hardening.md)，不要在 Handoff 中复制一套容易失真的实现细节。

### 2.4 最近自动化验证

2026-08-31 由独立 `luna_worker` 在未修改工作树的前提下完成：

- Windows unittest：57/57；
- Ubuntu unittest：57/57；
- Python 双平台编译：通过；
- 平台同步：通过；
- `git diff --check`：通过。

上述 114 个测试结果不替代第三方平台在线验证、生产网络策略或 Git 全历史秘密扫描。

## 3. Bootstrap 管理员

默认 Bootstrap 用户名固定为 `gen`。

只有 `users` 表为空时才创建该账号。它具有：

- `role=admin`；
- `enabled=1`；
- `must_change_password=1`。

初始明文密码**不在仓库中**。可通过 `INITIAL_ADMIN_PASSWORD` 注入；留空时首次启动生成 `INITIAL_ADMIN_CREDENTIAL_PATH` 指向的受限凭据文件（默认 `data/bootstrap-admin.json`），首次改密成功后自动删除。数据库只保存 PBKDF2-SHA256 Hash。

首次成功登录后，只允许访问改密、注销和 Session 状态；其他页面会跳转到 `/change-password`，API 返回 `428`。改密成功会提升 `auth_version`、撤销旧 Session，并重新签发 Session。

不要通过删除 `data/kook_music.db` 来“重置密码”，因为这会同时删除用户、Scope、Session 与审计记录并重新触发 Bootstrap 初始化。

## 4. SQLite 控制面数据

默认路径：

```text
data/kook_music.db
```

主要表：

- `users`
- `sessions`
- `login_attempts`
- `guilds`
- `channels`
- `user_scopes`
- `audit_logs`
- `schema_migrations`

SQLite 使用 WAL、Foreign Key、`busy_timeout=5000` 和 `synchronous=FULL`。

数据库、`-wal`、`-shm`、`.env`、Cookie/Credential 等均为运行数据，已通过 `.gitignore` 排除。备份/迁移时 `data/` 与 `.env`、`Cookie/` 同等重要。

## 5. 权限模型

### Admin

管理员拥有隐式全局权限，可以访问播放、账号、状态、设置、用户管理和管理 API。

### User

普通用户固定拥有：

- `playback.read`
- `playback.control`

并必须至少配置一个 playback Scope：

```text
*
guild:<KOOK_GUILD_ID>
channel:<KOOK_GUILD_ID>/<KOOK_CHANNEL_ID>
```

Role 决定“能做什么”，Scope 决定“能在哪个 KOOK 资源做”。管理员不需要在 `user_scopes` 中重复写全局 Scope。

普通用户可访问 `/dashboard`、`/library`，以及播放所需的音乐账号只读状态/歌单接口；不能进入音乐账号管理、系统运维、设置和用户管理页面。

## 6. Session / CSRF

默认：

- Session idle：24 小时；
- Session absolute：7 天；
- Session Token：随机生成，浏览器 Cookie 持有原值，数据库只保存 SHA-256；
- CSRF Token：独立随机值，数据库只保存 SHA-256；
- Session Cookie：`HttpOnly`、`SameSite=Lax`；
- CSRF Cookie：可供同源前端读取、`SameSite=Lax`；
- 所有 POST/PUT/PATCH/DELETE 需要有效 CSRF；
- `auth-client.js` 为同源 fetch/XHR 自动注入 `X-CSRF-Token`。

公网 HTTPS 必须启用：

```env
AUTH_COOKIE_SECURE=true
```

仅当受信任反向代理会覆盖并清洗客户端 `X-Forwarded-For` 时启用：

```env
AUTH_TRUST_PROXY_HEADERS=true
```

## 7. 关键文件

| 文件 | 作用 |
|---|---|
| `windows/auth.py` / `Ubuntu/auth.py` | 身份、Session、CSRF、Role/Scope、IAM、审计 |
| `api.py` | 在现有路由注册完成后安装统一 Auth Middleware |
| `static/js/auth-client.js` | CSRF 自动注入和当前会话前端辅助 |
| `static/js/users.js` | 用户管理 UI |
| `static/css/auth.css` | 登录/改密/用户管理样式 |
| `templates/login.html` | 登录 |
| `templates/change_password.html` | 首次/主动改密 |
| `templates/users.html` | 管理员用户管理 |
| `tests/test_auth.py` | Bootstrap、密码、Scope、强制改密等回归测试 |
| `scripts/check_secrets.py` | 当前树与全部可达历史秘密扫描 |
| `scripts/check_platform_sync.py` | Windows/Ubuntu 共享文件一致性 |
| `.github/workflows/platform-sync.yml` | 安全、同步、编译、双平台测试 CI |

## 8. 部署接手检查

首次部署或升级到该鉴权版本时：

1. 备份平台目录的 `.env`、`Cookie/`、`data/`；
2. 拉取当前目标提交；
3. 安装 Python 依赖并确认系统 Node/npm 与全局音乐 API 版本；
4. 检查 `.env` 的 `SECRET_KEY` 和 `AUTH_*`；
5. 启动应用；
6. 访问 `/login`；
7. 从部署 Secret 或受限凭据文件读取 Bootstrap 凭据并登录；
8. 完成强制改密；
9. 创建第二个管理员作为恢复路径；
10. 再创建普通用户并验证 Scope；
11. 验证账号页、系统页只有管理员可进入；
12. 验证 Windows/Ubuntu CI。

生产环境应令 Flask 只监听回环地址并由 HTTPS 反向代理暴露；18474/18475 绝不能直接暴露公网。

## 9. 当前安全边界与后续工作

当前 Web 控制面不提供远程 shell 命令执行能力，KOOK `/cmd` 指令也已取消。`/api/terminal/output` 仅返回管理员可读的运行日志增量。

Bootstrap 密码支持部署 Secret 注入或首次启动生成受限本地凭据文件；首次改密成功后凭据文件会被删除。Schema 使用顺序化版本迁移，升级前仍应备份 `data/`。

### P1：管理员恢复流程

目前没有离线管理员密码恢复 CLI。建议增加只允许本机运行、明确审计/提示的数据恢复工具，而不是通过删除数据库恢复 Bootstrap 账号。

### P2：审计日志运维界面

`audit_logs` 已落库，但尚无专门的只读查询/导出页面。后续可以提供管理员只读查询、保留周期和安全导出能力。

## 10. 接手后的推荐阅读顺序

1. `docs/HANDOFF.md`
2. `docs/authentication.md`
3. `docs/security.md`
4. `docs/architecture.md`
5. `windows/auth.py`
6. `windows/api.py`
7. `windows/tests/test_auth.py`
8. `scripts/check_secrets.py`
9. `scripts/check_platform_sync.py`
10. `docs/deployment.md`

## 11. 修改完成后的最低验证

仓库根目录：

```bash
python scripts/check_secrets.py
python scripts/check_platform_sync.py
python -m compileall windows Ubuntu
```

再分别执行两个平台的全部测试：

```bash
python -m unittest discover -s windows/tests -p "test_*.py"
python -m unittest discover -s Ubuntu/tests -p "test_*.py"
```

对于鉴权改动，还要人工覆盖：未登录、错误密码限速、首次改密、Admin/User 页面边界、Global/Guild/Channel Scope、CSRF、禁用/角色变化后的 Session 失效、移动端导航与 HTTPS Cookie 行为。
