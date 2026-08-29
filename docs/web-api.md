# Web 页面与 HTTP API

## 页面

| 路径 | 作用 |
|---|---|
| `/` | 应用入口 |
| `/dashboard` | 播放控制台 |
| `/library` | 三平台音乐库 |
| `/account` | 三平台账号中心 |
| `/status` | 运行状态与日志 |
| `/settings` | 浏览器端 UI 偏好 |
| `/monitor` | Ubuntu 监控页；Windows 返回 404 |

桌面与移动端使用同一组页面和 API，不提供 `/api/mobile/*` 分支。

## 服务器与频道

- `GET /api/guilds`：Bot 可见服务器。
- `GET /api/channels?guild_id=...`：服务器中的语音频道。
- `GET /api/channels/active?guild_id=...`：活跃播放频道。
- `POST /api/join`：加入语音频道。
- `POST /api/leave`：离开语音频道。

播放状态以 `channel_id` 为主键。涉及控制或队列的请求应携带明确频道上下文。

## 搜索、歌单与播放

- `GET /api/search?keyword=...&platform=wy|qq|bili`
- `POST /api/play`
- `POST /api/playlist/add`
- `POST /api/playlist`
- `GET /api/playlist/current?guild_id=...&channel_id=...`
- `POST /api/playlist/promote`
- `POST /api/remove`
- `POST /api/clear`
- `POST /api/playlist/repeat`

控制接口：

- `POST /api/pause`
- `POST /api/resume`
- `POST /api/skip`
- `POST /api/stop`
- `POST /api/seek`

`/api/playlist/promote` 将等待队列中的指定索引移到下一首，不打断当前歌曲。

## 网易云账号

- `GET /api/account/status`
- `GET /api/account/detail`
- `GET /api/account/level`
- `GET /api/account/subcount`
- `GET /api/account/playlists`
- `POST /api/account/qr/key`
- `POST /api/account/qr/create`
- `POST /api/account/qr/check`
- `POST /api/account/cellphone/captcha`
- `POST /api/account/cellphone/verify`
- `POST /api/account/cellphone/login`
- `POST /api/account/signin`
- `POST /api/account/cookie`
- `POST /api/account/logout`

## QQ 音乐账号

- `GET /api/qq/account/status`
- `POST /api/qq/account/qr/create`
- `POST /api/qq/account/qr/check`
- `GET /api/qq/account/profile`
- `GET /api/qq/account/playlists`
- `POST /api/qq/account/cookie`
- `POST /api/qq/account/refresh`
- `POST /api/qq/account/logout`

`/refresh` 是手工续期入口；后台 Credential Manager 负责日常检查。

## Bilibili 账号

- `GET /api/bili/account/status`
- `POST /api/bili/account/qr/create`
- `POST /api/bili/account/qr/check`
- `GET /api/bili/account/profile`
- `GET /api/bili/account/playlists`
- `POST /api/bili/account/cookie`
- `POST /api/bili/account/logout`

这些路由由 Python 直接调用 Bilibili 公网 API。

## 状态与运维

- `GET /api/stats`：播放数量与组件摘要。
- `GET /api/system/status`：主机、进程和播放统计。
- `GET /api/debug`：Bot、事件循环、网关和队列摘要。
- `GET /api/logs`：按类型读取日志。
- `POST /api/logs/clear`：清空指定日志。
- `POST /api/system/cleanup`：进程内清理。
- `POST /api/system/cleanup/config`：调整清理阈值。
- `GET /api/terminal/output`：读取运行日志增量。
- `POST /api/terminal/command`：执行受首命令名单限制的 shell 字符串。
- `POST /api/cache/test`：兼容探针；未启用音频缓存时返回成功说明。

终端命令、日志清理和账号退出属于高风险写操作。当前 Web 层没有完整的多用户认证边界，不得直接暴露公网，详见 [security.md](security.md)。

## 请求与响应约束

1. 具体 JSON 字段以路由实现为准；调用方必须同时检查 HTTP 状态与 `success`、`code`、`error`。
2. 异步搜索、服务器和频道切换必须丢弃过期响应，避免旧结果覆盖新上下文。
3. 用户输入和平台文本通过 `textContent` 等安全方式写入 DOM。
4. Cookie、Credential 和完整签名播放 URL不得返回普通 UI。
5. 修改现有字段时同步更新 Web、Bot 调用点和本文。
