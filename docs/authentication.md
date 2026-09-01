# Web 控制面鉴权

本项目的 Web 登录与 KOOK Bot Token、音乐平台 Cookie/Credential 相互独立。控制面采用本地账号 + SQLite + 服务端 Session，负责回答三件事：谁能进入 Web、能执行哪些能力、能控制哪些 KOOK 资源。

实现位于 `windows/auth.py` 与 `Ubuntu/auth.py`，两端保持字节一致。`api.py` 在现有业务路由注册后调用 `register_auth(app)`，通过统一 `before_request` / `after_request` Middleware 覆盖页面与 API，而不是在每个播放函数上重复实现鉴权。

## 身份与角色

当前固定两种角色：

- `admin`：全局管理员。可访问播放、音乐账号、系统状态、用户管理、设置和管理 API。
- `user`：普通用户。可访问播放页和音乐库，并使用授权 Scope 内的播放控制 API；不可进入音乐账号管理、系统运维、用户管理或设置页面。

角色与 Permission 在代码中固定映射：

```text
admin -> *
user  -> playback.read + playback.control
```

Role 决定“能做什么”，Scope 决定“能在哪里做”。

## Scope

普通用户的 `playback` Scope 支持三层：

```text
*
guild:<KOOK_GUILD_ID>
channel:<KOOK_GUILD_ID>/<KOOK_CHANNEL_ID>
```

含义：

- `*`：全部 Guild/Channel。
- `guild:<id>`：指定服务器及其全部语音频道。
- `channel:<guild>/<channel>`：只允许指定语音频道。

管理员 Scope 为隐式全局，不在 `user_scopes` 中重复存储。普通用户必须至少有一个 playback Scope。

`GET /api/guilds` 会按用户 Scope 过滤服务器；`GET /api/channels` 与 `/api/channels/active` 会按服务器内可见频道过滤结果。播放写操作除 Role 外还会校验请求中的 `guild_id` / `channel_id` 是否处于授权范围。

### 资源 ID 的唯一来源

写请求的资源 ID 在统一 Middleware 中规一化。调用方应只在 JSON Body 中提供一次 `guild_id` / `channel_id`；同名 Query 参数重复，或 Query 与 JSON 同时提供但值不一致时，服务端返回 `400`。业务路由与鉴权守卫使用同一组规一化值，不能分别选择参数来源。

Guild Scope 不能仅凭客户端提供的 `guild_id` 放行频道操作。服务端会查询 Channel 的真实 Guild 归属，并要求 Channel 已由 KOOK 同步验证且 Channel/Guild 都处于启用状态。管理员禁用频道后，普通同步只更新归属和元数据，不会自动重新启用。

## SQLite 表

数据库默认位于：

```text
data/kook_music.db
```

可通过 `AUTH_DATABASE_PATH` 覆盖。相对路径以当前平台目录为基准。

主要表：

- `users`：内部 `id INTEGER PRIMARY KEY`，`username` 唯一；保存密码哈希、角色、启用状态、首次改密状态和 `auth_version`。
- `sessions`：保存 Session Token Hash、CSRF Hash、认证版本、空闲/绝对过期时间、IP 和 User-Agent 元数据。
- `login_attempts`：登录失败限速依据。
- `guilds`：KOOK Guild 映射。
- `channels`：KOOK Channel 映射并通过 FK 归属 Guild。
- `user_scopes`：关联用户与 playback Domain 的 Global/Guild/Channel 范围。
- `audit_logs`：认证、IAM 和成功写 API 的审计记录。
- `schema_migrations`：Schema 版本。

SQLite 初始化时启用：

```text
journal_mode=WAL
foreign_keys=ON
busy_timeout=5000
synchronous=FULL
```

数据库及 `-wal` / `-shm` 均是运行数据，不进入 Git。

## 密码

密码使用 PBKDF2-HMAC-SHA256，并为每个新密码生成独立随机 Salt。当前默认迭代次数为 600000。

新密码必须满足：

- 8–128 位；
- 至少一个大写字母；
- 至少一个小写字母；
- 至少一个特殊字符。

管理员创建用户或重置用户密码时，服务端生成一次性临时密码，只在该次响应中返回；数据库只保存 Hash，并设置 `must_change_password=1`。

## 初始管理员

只有当 `users` 表为空时才自动创建 Bootstrap 管理员：

```text
username = gen
role = admin
enabled = 1
must_change_password = 1
```

仓库不保存该账号的初始明文密码，只保存与项目所有者已接收的一次性初始密码对应的 PBKDF2-SHA256 Hash。明文不得写入 README、docs、Issue、日志或配置示例。

首次登录后，除以下入口外所有控制面访问都会被拒绝：

- `/change-password`
- `/logout`
- `/api/auth/session`

页面会跳转到 `/change-password`；API 返回 HTTP `428`。改密成功后会提升 `auth_version`、撤销该用户所有旧 Session，并签发新 Session。

一旦数据库已有用户，后续启动不会重新创建或重置管理员。不要通过删除数据库来重置密码。

## Session

登录成功生成两个独立随机值：

- Session Token：浏览器持有原值，数据库只保存 SHA-256 Hash。
- CSRF Token：浏览器同源前端读取原值，数据库只保存 SHA-256 Hash。

默认：

| 项目 | 默认值 |
|---|---:|
| Session idle | 86400 秒（24 小时） |
| Session absolute | 604800 秒（7 天） |
| Session touch | 300 秒 |

Session Cookie：

- `HttpOnly`
- `SameSite=Lax`
- `Path=/`
- `AUTH_COOKIE_SECURE=true` 时增加 `Secure`

用户禁用、角色修改、密码修改或密码重置都会提升 `auth_version` 或撤销 Session，使旧登录立即失效。

## CSRF

所有有副作用的：

```text
POST / PUT / PATCH / DELETE
```

都必须同时通过 Session、Role/Scope 和 CSRF 校验。服务端接受 `X-CSRF-Token` Header 或表单 `_csrf`。

共享 `static/js/auth-client.js` 会为同源 `fetch` / XHR 自动加入 `X-CSRF-Token`，因此网易云、QQ、Bilibili和播放页不需要各自实现一套 CSRF 逻辑。

## 登录失败限速

默认窗口 600 秒：

- 同一用户名失败 5 次后限速；
- 同一来源 IP 失败 20 次后限速。

对应变量：

```env
AUTH_LOGIN_WINDOW_SECONDS=600
AUTH_LOGIN_USER_FAILURES=5
AUTH_LOGIN_IP_FAILURES=20
```

达到阈值时返回 HTTP `429`。成功登录会清理该用户名或来源 IP 的失败记录。

## 用户管理

管理员可在 `/users`：

- 创建 `admin` / `user`；
- 为普通用户设置 Scope；
- 启用或禁用账号；
- 修改角色；
- 重置为一次性临时密码；
- 删除用户。

管理 API：

- `GET /api/admin/users`
- `POST /api/admin/users`
- `PATCH /api/admin/users/<id>`
- `DELETE /api/admin/users/<id>`
- `POST /api/admin/users/<id>/reset-password`

系统禁止当前管理员自我降级、禁用或删除，并保证至少保留一个启用的管理员。

## 页面与 API 边界

未登录：

- 页面重定向到 `/login?next=...`；
- API 返回 `401`。

普通用户允许页面：

- `/`
- `/dashboard`
- `/library`
- `/change-password`

账号状态/歌单的只读 GET 仍允许普通用户调用，因为音乐库页面需要读取已连接平台的状态和收藏；写账号接口仍只允许管理员。

管理员页面包括 `/account`、`/status`、`/settings`、`/users` 和 `/monitor`。

## 安全响应头

统一响应处理会设置：

```text
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: same-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
```

登录、改密、用户管理和鉴权 API 使用 `Cache-Control: no-store`。

## 环境变量

```env
AUTH_DATABASE_PATH=./data/kook_music.db
AUTH_SESSION_IDLE_SECONDS=86400
AUTH_SESSION_ABSOLUTE_SECONDS=604800
AUTH_LOGIN_WINDOW_SECONDS=600
AUTH_LOGIN_USER_FAILURES=5
AUTH_LOGIN_IP_FAILURES=20
AUTH_COOKIE_SECURE=false
AUTH_TRUST_PROXY_HEADERS=false
```

公网 HTTPS 部署必须设置：

```env
AUTH_COOKIE_SECURE=true
```

只有受信任代理会覆盖并清洗客户端传入的 `X-Forwarded-For` 时，才设置：

```env
AUTH_TRUST_PROXY_HEADERS=true
```

## 审计

以下事件会进入 `audit_logs`：

- Bootstrap 管理员创建；
- 登录成功/失败/限速；
- 注销；
- 密码修改；
- 用户创建、修改、删除、密码重置；
- 已认证且成功的写 API。

审计数据本身也可能包含用户名、资源 ID、来源 IP 等敏感运维信息，不应公开暴露。

## 备份与恢复

控制面恢复必须同时考虑：

```text
.env
Cookie/
data/
```

其中 `data/kook_music.db` 保存 Web 用户、Scope 和审计；只恢复 Cookie 而不恢复数据库会丢失控制台身份与授权。备份前建议停止实例或使用 SQLite 一致性备份方式，避免只复制主 `.db` 而遗漏 WAL 中尚未 checkpoint 的事务。

## 公网部署要求

1. 只通过 HTTPS 反向代理暴露 Web 控制面；Flask 18473、网易云 18474、QQ 18475 不直接暴露公网。
2. Flask 建议只监听 `127.0.0.1`。
3. `.env` 设置 `AUTH_COOKIE_SECURE=true`。
4. `AUTH_TRUST_PROXY_HEADERS=true` 只用于受信任且会清洗 Forwarded Header 的代理。
5. `.env`、`Cookie/`、`data/` 放在持久磁盘并限制文件权限。
6. 发布前执行 `python scripts/check_secrets.py`；CI 同样扫描 tracked 文件和全部可达 Git 历史。
7. `/api/terminal/output` 仅供管理员读取运行日志增量；项目不提供远程 shell 命令执行接口。
