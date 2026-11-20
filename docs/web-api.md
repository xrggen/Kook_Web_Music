# Web 页面与 HTTP API

## 全局鉴权规则

除 `/login`、静态资源和 favicon 外，页面与 API 默认都受 Web 控制面鉴权保护。

未登录：

- 页面：重定向 `/login?next=...`；
- API：返回或拒绝为未认证状态。

首次登录尚未改密：

- 页面：重定向 `/change-password`；
- API：HTTP `428`，并返回 `must_change_password=true`。

写请求：

```text
POST / PUT / PATCH / DELETE
```

必须携带有效 Session 和 CSRF。浏览器端 `auth-client.js` 会自动给同源 fetch/XHR 注入 `X-CSRF-Token`。

角色：

- `admin`：全局控制面权限；
- `user`：`playback.read` + `playback.control`，再受 Global/Guild/Channel Scope 限制。

完整模型见 [authentication.md](authentication.md)。

## 鉴权页面

| 路径 | 方法 | 作用 |
|---|---|---|
| `/login` | GET/POST | 登录 |
| `/logout` | POST | 注销并撤销当前 Session |
| `/change-password` | GET/POST | 首次/主动修改密码 |
| `/users` | GET | 管理员用户管理 |

## 鉴权 API

### 微信原生控制页兼容（kook-wechat-v1）

复用原路由，不新增绕过鉴权的播放入口。`Content-Type: application/json`切换响应格式；旧HTML表单及其重定向保持兼容。

| 请求 | JSON body | 成功响应 |
| --- | --- | --- |
| `POST /login` | `username`, `password`（字符串） | `success`, `clientProtocol`, `csrfToken`, `user`，并设置原Session/CSRF Cookies |
| `POST /change-password` | `current_password`, `new_password`, `confirm_password` | 同上，轮换Session与CSRF，首次改密标识变为false |
| `POST /logout` | `{}` | `success: true`，撤销当前Session并清除Cookies |

`clientProtocol`固定`kook-wechat-v1`，`user`只包含`id/username/role/must_change_password`。Session Token不在JSON返回；CSRF Token只给当前客户端内存使用，不记日志。字段无效400、错误账号密码401、过多失败429；改密仍要求原密码、密码策略、Session及`X-CSRF-Token`。首次改密未完成时业务API仍428，Scope不足仍403。普通用户只允许注销自己的会话，不获得任何管理权限。

小程序必须检查协议与Cookie，不把旧HTML登录页当JSON成功。客户端显式携带Cookie，写操作同时携带CSRF；不依赖浏览器Cookie自动管理，不对网络不确定的写操作自动重试。登录/改密/注销响应禁止缓存。

### 微信关联接口

| 请求 | 参数与授权 | 成功响应 |
| --- | --- | --- |
| `POST /api/auth/wechat/login` | JSON `{"code":"…"}`；用户主动调用 `wx.login` 后取得；无需现有 KOOK Session | `success`, `clientProtocol: "kook-wechat-v1"`, `csrfToken`, `user`；沿用 Session/CSRF Cookie |
| `GET /api/auth/wechat/status` | 有效 KOOK Session；首次改密已完成 | `{"success":true,"bound":true}`，`bound` 表示当前 KOOK 账号是否有关联 |
| `POST /api/auth/wechat/bind` | JSON `{"code":"…"}`；有效 KOOK Session、`X-CSRF-Token`，首次改密已完成 | `{"success":true,"bound":true}`；相同关联重复提交成功，不覆盖不同关联 |
| `POST /api/auth/wechat/unbind` | JSON `{}`；有效 KOOK Session、`X-CSRF-Token`，首次改密已完成 | `{"success":true,"bound":false}`；未绑定时也返回成功 |

错误响应包含 `success: false`、`code`、`error`、`auth_required`：

| HTTP | `code` | 含义 |
| --- | --- | --- |
| 400 | `INVALID_REQUEST` / `WECHAT_CODE_INVALID` | 请求格式错误 / 微信凭证无效或不可用 |
| 401 | `AUTH_REQUIRED` / `WECHAT_NOT_LINKED` | 会话缺失或失效 / 当前微信没有可登录的关联账号 |
| 403 | `CSRF_FAILED` | 关联写操作的 CSRF 校验失败 |
| 409 | `WECHAT_BINDING_CONFLICT` | 当前 KOOK 账号已绑定另一微信，或此微信已绑定其他 KOOK 账号 |
| 428 | `PASSWORD_CHANGE_REQUIRED` | 需要先使用密码登录并完成首次改密 |
| 429 | `WECHAT_RATE_LIMITED` | 微信兑换限速 |
| 502 | `WECHAT_UPSTREAM_ERROR` | 微信服务响应失败 |
| 503 | `WECHAT_UNAVAILABLE` | 服务端未配置微信兑换 |

这些接口的响应禁止缓存。登录凭证为一次性输入，重试由用户再次主动触发并获取新凭证。绑定和解绑不需要再次输入密码，也不签发、轮换或清除当前 Session/CSRF Cookie。解绑后，后续微信登录返回 `401 WECHAT_NOT_LINKED`；改密或管理员重置密码则同时解绑并撤销旧会话。普通退出只撤销当前会话。

完整原生移动端复用下文音乐库、音乐账号、健康/日志和用户管理路由。播放/控制面登录仍检查`success:true`，音乐平台接口按其原有`code:200`检查，网易云手机号登录另兼容原网页的`code:803`，`/api/debug`按`status:success`检查；扫码检查使用各平台现有等待/已扫码/成功/过期状态。仅网易云`GET /api/account/status`另接受`{data:{code:200,account,profile}}`，内外层明确错误和非2xx HTTP均不可当成功；其他路由不接受内层code替代。`GET /api/account/detail`必须传入状态所给的数字`uid`查询参数。不得为兼容不同响应格式放宽所有接口的成功条件。日志只使用后端支持的`app`（`debug`为同一文件的兼容别名）。管理员调用均保持原Role与CSRF；普通用户只调用获允许的音乐库读取接口。

- `GET /api/auth/session`：当前会话用户、角色和首次改密状态。
- `GET /api/admin/users`：用户列表，Admin only。
- `POST /api/admin/users`：创建用户，Admin only。
- `PATCH /api/admin/users/<id>`：修改角色、启用状态和 Scope，Admin only。
- `DELETE /api/admin/users/<id>`：删除用户，Admin only。
- `POST /api/admin/users/<id>/reset-password`：生成一次性临时密码，Admin only。

管理员创建/重置密码时，临时密码只在当次 JSON 响应中返回，不进入数据库明文、日志或文档。

## 页面

| 路径 | 作用 | 最低角色 |
|---|---|---|
| `/` | 应用入口 | User |
| `/dashboard` | 播放控制台 | User |
| `/library` | 三平台音乐库 | User |
| `/account` | 三平台账号中心 | Admin |
| `/status` | 运行状态与日志 | Admin |
| `/settings` | 浏览器端 UI 偏好 | Admin |
| `/users` | 用户/角色/Scope 管理 | Admin |
| `/monitor` | Ubuntu 监控页；Windows 返回 404 | Admin |

桌面与移动端使用同一组页面和 API，不提供 `/api/mobile/*` 分支。

普通用户访问管理员页面时由后端返回 `403`；导航隐藏只是 UX，不是安全边界。

## 服务器与频道

- `GET /api/guilds`：Bot 可见且当前用户 Scope 可见的服务器。
- `GET /api/channels?guild_id=...`：当前用户在该服务器可见的语音频道。
- `GET /api/channels/active?guild_id=...`：Scope 内活跃播放频道。
- `POST /api/join`：加入语音频道。
- `POST /api/leave`：离开语音频道。

播放状态以 `channel_id` 为主键。涉及控制或队列的请求应携带明确 `guild_id` / `channel_id`，以便 Scope 精确校验。

## 搜索、歌单与播放

读取：

- `GET /api/search?keyword=...&platform=wy|qq|bili`
- `GET /api/playlist/current?guild_id=...&channel_id=...`

写操作：

- `POST /api/play`
- `POST /api/playlist/add`
- `POST /api/playlist`
- `POST /api/playlist/promote`
- `POST /api/remove`
- `POST /api/clear`
- `POST /api/playlist/repeat`
- `POST /api/pause`
- `POST /api/resume`
- `POST /api/skip`
- `POST /api/stop`
- `POST /api/seek`

`/api/playlist/promote` 将等待队列中的指定索引移到下一首，不打断当前歌曲。

普通用户可以调用这些播放 API，但必须处于授权 Scope；管理员不受 playback Scope 限制。

## 音乐账号的权限边界

音乐账号写操作只允许管理员。普通用户为了构建 `/library`，允许读取少量账号状态/资料/歌单接口，但这些接口不得返回 Cookie、Credential、Refresh Token 或完整签名媒体 URL。

### 网易云

普通用户可读：

- `GET /api/account/status`
- `GET /api/account/playlists`

管理员账号管理：

- `GET /api/account/detail`
- `GET /api/account/level`
- `GET /api/account/subcount`
- `POST /api/account/qr/key`
- `POST /api/account/qr/create`
- `POST /api/account/qr/check`
- `POST /api/account/cellphone/captcha`
- `POST /api/account/cellphone/verify`
- `POST /api/account/cellphone/login`
- `POST /api/account/signin`
- `POST /api/account/cookie`
- `POST /api/account/logout`

### QQ 音乐

普通用户可读：

- `GET /api/qq/account/status`
- `GET /api/qq/account/profile`
- `GET /api/qq/account/playlists`

管理员账号管理：

- `POST /api/qq/account/qr/create`
- `POST /api/qq/account/qr/check`
- `POST /api/qq/account/cookie`
- `POST /api/qq/account/refresh`
- `POST /api/qq/account/logout`

`/refresh` 是手工续期入口；后台 Credential Manager 负责日常检查。

### Bilibili

普通用户可读：

- `GET /api/bili/account/status`
- `GET /api/bili/account/profile`
- `GET /api/bili/account/playlists`

管理员账号管理：

- `POST /api/bili/account/qr/create`
- `POST /api/bili/account/qr/check`
- `POST /api/bili/account/cookie`
- `POST /api/bili/account/logout`

这些路由由 Python 直接调用 Bilibili 公网 API。

## 状态与运维

以下均为 Admin only：

- `GET /api/stats`：播放数量与组件摘要。
- `GET /api/system/status`：主机、进程和播放统计。
- `GET /api/debug`：Bot、事件循环、网关和队列摘要。
- `GET /api/logs`：读取日志。
- `POST /api/logs/clear`：清空日志。
- `POST /api/system/cleanup`：进程内清理。
- `POST /api/system/cleanup/config`：调整清理阈值。
- `GET /api/terminal/output`：读取运行日志增量；该接口不执行命令。
- `POST /api/cache/test`：兼容探针。

项目不提供远程 shell 或任意命令执行接口。

## 常见鉴权状态码

| HTTP | 含义 |
|---:|---|
| `401` | 未登录 / Session 无效 |
| `403` | Role、Scope 或 CSRF 不允许 |
| `428` | 首次登录必须先修改密码 |
| `429` | 登录失败次数达到限速阈值 |

业务 API 仍可能返回其他 4xx/5xx。调用方必须同时检查 HTTP 状态与 JSON 中的 `success`、`code`、`error`。

## 审计

成功的已认证写 API 会写入 `audit_logs`，记录动作、Domain、用户、资源上下文和来源 IP。IAM 与认证事件也单独记录。

不得把 Token、Cookie、临时密码、Credential 或完整媒体 URL放入审计 metadata。

## 请求与响应约束

1. 具体 JSON 字段以路由实现为准；调用方必须同时检查 HTTP 状态与业务字段。
2. 新增写 API 必须经过统一 Auth Middleware，不得通过临时白名单绕过 CSRF。
3. 新增播放 API 必须明确它需要的 `guild_id` / `channel_id`，否则 Scope 无法精确表达资源。
4. 异步搜索、服务器和频道切换必须丢弃过期响应，避免旧结果覆盖新上下文。
5. 用户输入和平台文本通过 `textContent` 等安全方式写入 DOM。
6. Cookie、Credential、Session Token、CSRF Token、临时密码和完整签名播放 URL不得返回普通 UI。
7. 修改现有字段、路径或权限边界时，同步更新 Web、Bot 调用点、`authentication.md`、`security.md` 和本文。
8. 写请求中的 `guild_id` / `channel_id` 应只在 JSON 中提供一次；重复 Query 或 Query/JSON 冲突会返回 `400`。
9. 搜索、分页、账号、歌单和队列接口均有长度/数量上限；调用方必须处理 `400`、`409`、`413`、`429` 或被安全截断的结果。
10. 第三方平台响应不是内部契约；服务端只返回规一化后的允许字段，不保证透传平台原始 JSON。
