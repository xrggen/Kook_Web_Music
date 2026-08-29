# Web 页面与 HTTP API

本文描述当前 Web 层的职责边界。具体字段以代码为准；新增或修改接口时应同步更新此文档。

## 1. 页面路由

| 路径 | 作用 |
|---|---|
| `/` | 进入应用控制台体验 |
| `/dashboard` | 播放控制台 |
| `/library` | 三平台音乐库 |
| `/account` | 三平台账号中心 |
| `/status` | 运行状态 |
| `/settings` | 浏览器端界面偏好 |

## 2. 服务器与频道

- `GET /api/guilds` — 获取 Bot 可见服务器。
- `GET /api/channels?guild_id=...` — 获取服务器下可用语音频道。
- `GET /api/channels/active?guild_id=...` — 查询活跃播放频道。
- `POST /api/join` — 加入指定语音频道。
- `POST /api/leave` — 离开指定语音频道。

播放会话主键是 `channel_id`，调用方不应只依赖 guild 级状态。

## 3. 搜索与入队

- `GET /api/search?keyword=...&platform=wy|qq|bili`
- `POST /api/playlist/add`
- `POST /api/play` — 兼容旧版单曲入口。
- `POST /api/playlist` — 导入歌单。

Bilibili 搜索还支持 BV 号直解析语义；平台差异由后端适配层处理，前端不应自己拼播放 URL。

## 4. 播放控制

- `POST /api/pause`
- `POST /api/resume`
- `POST /api/skip`
- `POST /api/stop`
- `POST /api/seek`
- `POST /api/playlist/repeat`
- `GET /api/playlist/current?guild_id=...&channel_id=...`
- `POST /api/remove`
- `POST /api/clear`
- `POST /api/playlist/promote`

### 顶歌

`POST /api/playlist/promote` 将等待队列中指定索引的歌曲移动到队首，也就是“下一首”，不会打断当前正在播放的歌曲。

请求核心字段：

```json
{
  "channel_id": "...",
  "index": 2
}
```

前端可能同时发送 `guild_id` 作为上下文，但当前队列操作核心以 `channel_id` 为准。

## 5. 网易云账号

常用接口：

- `GET /api/account/status`
- 扫码创建/轮询相关接口
- 手机验证码登录接口
- `POST /api/account/cookie`
- `POST /api/account/logout`

## 6. QQ 音乐账号

常用接口：

- `GET /api/qq/account/status`
- `POST /api/qq/account/qr/create`
- `POST /api/qq/account/qr/check`
- `GET /api/qq/account/profile`
- `GET /api/qq/account/playlists`
- `POST /api/qq/account/cookie`
- `POST /api/qq/account/refresh`
- `POST /api/qq/account/logout`

`/refresh` 是运维/排障入口，日常续期由 Credential Manager 自动完成。

## 7. Bilibili 账号

- `GET /api/bili/account/status`
- `POST /api/bili/account/qr/create`
- `POST /api/bili/account/qr/check`
- `GET /api/bili/account/profile`
- `GET /api/bili/account/playlists`
- `POST /api/bili/account/cookie`
- `POST /api/bili/account/logout`

这些 Flask 路由内部直接调用 Bilibili 公网 API，不经过本地 Node 服务。

## 8. 状态与运维

- `GET /api/debug` — Bot/loop/gateway/队列等轻量运行信息。
- 其他系统状态、日志、清理和兼容运维接口位于现有 routes/api 模块。

前端“系统状态”页优先使用轻量健康数据，不应为了刷新一个状态灯频繁拉取大日志。

## 9. 前端调用约束

1. 异步搜索/切换频道要防止旧请求晚到覆盖新状态。
2. 用户输入或平台返回的歌曲名使用 `textContent` 等安全方式写 DOM。
3. 不在浏览器保存音乐平台 Cookie。
4. 播放 URL、签名参数、完整 Cookie 不应出现在普通 UI 或成功消息中。
5. 移动端与桌面端复用同一个 API，不建立 `/api/mobile/*` 分叉。

## 10. 安全提示

当前 Web API 的访问控制边界与部署方式强相关。不要因为“仅是控制台 API”就默认可安全暴露公网。特别是账号、运维和终端类接口需要额外注意，详见 [security.md](security.md)。
