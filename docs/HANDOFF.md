# 工程 Handoff

生成日期：2026-08-29

工作分支：`refactor/desktop-ui-v2`

最近一次完整验证的实现基线：`823141b01e0f26fb6786481482bb74c8a061496c`（`feat(auth): add SQLite web control-plane authentication`）。本文描述该实现及其后的文档状态；接手时应先读取当前分支 HEAD，而不是把此 SHA 当作永久最新版本。

> 安全约束：本文以及仓库其他文档不得记录真实 Bot Token、Cookie、Credential、Session Token、CSRF Token、管理员明文密码或签名媒体 URL。Bootstrap 管理员的初始明文密码已通过实现时的对话渠道交付，不进入 Git。

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

实现基线对应的 GitHub Actions Run `33241568022`（Run #74）最终为 `success`：

- 全历史秘密扫描：通过；
- Windows/Ubuntu 共享文件同步：通过；
- Python compile：通过；
- Ubuntu 全量 `test_*.py`：通过；
- Windows 全量 `test_*.py`：通过。

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
- Socket.IO 连接时的登录状态检查；
- 桌面/移动共享登录、改密、用户管理 UI。

## 3. Bootstrap 管理员

默认 Bootstrap 用户名固定为 `gen`。

只有 `users` 表为空时才创建该账号。它具有：

- `role=admin`；
- `enabled=1`；
- `must_change_password=1`。

初始明文密码**不在仓库中**；当前对话已将其交付给项目所有者。代码只包含与该一次性初始密码对应的 PBKDF2-SHA256 Hash。

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
7. 使用项目所有者安全保存的 Bootstrap 凭据登录；
8. 完成强制改密；
9. 创建第二个管理员作为恢复路径；
10. 再创建普通用户并验证 Scope；
11. 验证账号页、系统页只有管理员可进入；
12. 验证 Windows/Ubuntu CI。

生产环境应令 Flask 只监听回环地址并由 HTTPS 反向代理暴露；3000/3200 绝不能直接暴露公网。

## 9. 已知风险与建议后续工作

以下不是本轮未完成的故障，而是接手后优先级较高的硬化项：

### P0：移除 Web shell 边界

`POST /api/terminal/command` 目前虽然已被管理员鉴权和 CSRF 保护，但底层仍是“首词白名单 + `shell=True`”。这仍然是高危远程命令执行边界。建议改成固定命令 ID → 参数数组映射并使用 `shell=False`，或彻底删除 Web 终端执行能力。

### P1：Bootstrap Secret 生命周期

当前源码保存 Bootstrap 初始密码的强哈希，明文不在 Git。更成熟的首次部署模型可以改为：首次启动生成一次性密码写入受限本地文件/控制台，或从部署 Secret 注入，完成初始化后不再依赖源码内固定 Hash。

### P1：正式 Schema Migration

当前 Schema 版本为 1，初始化主要依靠 `CREATE TABLE/INDEX IF NOT EXISTS`。未来新增字段/索引前应实现按版本顺序执行、可验证的迁移函数，并在升级/回滚文档中明确兼容性。

### P1：Socket.IO Scope 复核

当前 Socket.IO 在 connect 时验证 Session 和首次改密状态。若以后通过 Socket.IO 发送敏感播放状态、控制事件或按房间推送数据，应对 `join_room`/事件处理增加与 HTTP 相同的 Role/Scope 校验，不能只依赖连接时登录。

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
