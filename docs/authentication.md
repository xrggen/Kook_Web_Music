# Web 控制面鉴权

本项目的 Web 登录与 KOOK Bot Token、音乐平台 Cookie/Credential 相互独立。控制面采用本地账号 + SQLite + 服务端 Session，目标是让公网部署能够明确回答“谁能进入 Web、能做什么、能控制哪些 KOOK 资源”。

## 身份与角色

当前固定两种角色：

- `admin`：全局管理员。可访问播放、音乐账号、系统状态、用户管理、设置和管理 API。
- `user`：普通用户。可访问播放页和音乐库，并使用授权 Scope 内的播放控制 API；不可进入音乐账号、系统运维、用户管理或设置页面。

角色与 Permission 在代码中固定映射：管理员拥有 `*`；普通用户拥有 `playback.read` 和 `playback.control`。这样 Role 决定“能做什么”，Scope 决定“能在哪里做”。

## Scope

普通用户的 `playback` Scope 支持三层：

- `*`：全部 Guild/Channel。
- `guild:<KOOK_GUILD_ID>`：指定服务器及其全部语音频道。
- `channel:<KOOK_GUILD_ID>/<KOOK_CHANNEL_ID>`：只允许一个语音频道。

管理员 Scope 为隐式全局，不在 `user_scopes` 中重复存储。

## SQLite 表

数据库默认位于 `data/kook_music.db`，属于运行时持久数据，不进入 Git。

- `users`：内部 `id INTEGER PRIMARY KEY`，`username` 为业务唯一键；保存 PBKDF2-SHA256 密码哈希、角色、启用状态、首次改密状态和 `auth_version`。
- `sessions`：`id` 为主键，`token_hash` 唯一；浏览器只持有随机 Session Token，数据库不保存原始 Token。保存 CSRF Hash、空闲/绝对过期时间和认证版本。
- `login_attempts`：登录失败限速依据。
- `guilds`：内部 `id` 主键，`kook_guild_id` 唯一。
- `channels`：内部 `id` 主键，`kook_channel_id` 唯一，并通过 FK 归属 Guild。
- `user_scopes`：关联用户与 playback Domain 的 Global/Guild/Channel 范围；使用部分唯一索引防止重复 Scope。
- `audit_logs`：认证、IAM 和成功写 API 的审计记录。
- `schema_migrations`：SQLite Schema 版本。

SQLite 启用 WAL、Foreign Key、busy timeout 和 `synchronous=FULL`。

## Session

登录成功生成 256-bit 级随机 Session Token 和独立 CSRF Token：

- Session Cookie：`HttpOnly`、`SameSite=Lax`；公网部署必须通过 `AUTH_COOKIE_SECURE=true` 增加 `Secure`。
- 数据库只存 Session/CSRF 的 SHA-256 Hash。
- 默认空闲有效期 24 小时，绝对有效期 7 天。
- 用户禁用、角色修改、密码修改/重置都会提升 `auth_version` 或撤销 Session，使旧登录立即失效。

所有有副作用的 POST/PUT/PATCH/DELETE 请求必须同时通过 Session、Role/Scope 和 CSRF 校验。共享 `auth-client.js` 会为同源 fetch/XHR 自动加入 `X-CSRF-Token`。

## 初始管理员

只有当 `users` 表为空时才自动创建用户名 `gen` 的 Bootstrap 管理员。仓库中只包含一次性初始化密码的高强度 PBKDF2-SHA256 Hash，不包含明文。该账号 `must_change_password=1`，首次登录后除修改密码、注销及身份状态接口外不能访问任何控制面能力。

一旦数据库已有用户，后续启动不会重新创建或重置管理员密码。

## 用户管理

管理员可在 `/users`：

- 创建 `admin` / `user`；
- 为普通用户设置 Scope；
- 启用/禁用账号；
- 修改角色；
- 重置为一次性临时密码；
- 删除用户。

系统禁止当前管理员自我降级/禁用/删除，并保证至少保留一个启用的管理员。

## 公网部署要求

生产环境至少满足：

1. 只通过 HTTPS 反向代理暴露 Web 控制面；Flask、网易云 3000、QQ 3200 端口不要直接暴露公网。
2. `.env` 设置 `AUTH_COOKIE_SECURE=true`。
3. 如果开启 `AUTH_TRUST_PROXY_HEADERS=true`，前置代理必须覆盖并清洗客户端传入的 `X-Forwarded-For`。
4. `data/`、Cookie、`.env` 必须放在持久磁盘并限制文件系统权限。
5. 发布前运行 `python scripts/check_secrets.py`，CI 同样会扫描 tracked 文件和全部可达 Git 历史。
