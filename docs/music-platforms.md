# 音乐平台与账号凭据

## 接入总览

| 平台 | 数据与播放入口 | 登录态 | 本地服务 |
|---|---|---|---|
| 网易云音乐 | Python 适配器调用 NeteaseCloudMusicApi | `Cookie/cookie.txt` | 系统 Node，全局包，3000 |
| QQ 音乐 | qq-music-api 与 Python 签名接口 | `qq_cookie.txt` + `qq_credential.json` | 系统 Node，全局包，3200 |
| Bilibili | Python 直连 REST 与 DASH | `Cookie/bili_cookie.txt` | 无 |

三平台共用搜索、队列和播放器模型，但保留各自的协议与凭据生命周期。系统全局 Node 包只提供 API 运行代码，不保存项目用户 Cookie。

## 网易云音乐

`utils.py` 负责搜索、歌单和播放 URL 解析。支持 Web 扫码、手机验证码和手工 Cookie 登录，账号接口写入当前平台的 `Cookie/cookie.txt`。

歌单条目先以 `PLAYLIST_SONG` 标记入队，接近播放时按批次解析 URL，避免一次性请求全部歌曲。

本地 API 默认由 `run.py` 在 3000 端口启动。启动失败时可使用 `MUSIC_API_BASE` 指定的地址，但生产环境不应依赖来源不明的公网代理。

## QQ 音乐

`qq_utils.py` 负责搜索、公开歌单、播放取链和用户歌单；`qq_account_api.py` 负责登录与账号接口；`qq_credential.py` 管理登录态续期。

两个凭据文件组成同一账号状态：

- `qq_cookie.txt`：兼容搜索、播放和已有调用点的 Cookie 串。
- `qq_credential.json`：uin、musickey、refresh token/key、access token、到期与刷新元数据。

凭据机制遵循以下规则：

1. 只有 `qq_cookie.txt` 时可以自动迁移出 Credential 元数据。
2. 完整 refresh 凭据优先使用 refresh-token 路线；仅有 musickey 时走兼容刷新。
3. 刷新过程使用进程内锁，成功后原子写回两个文件。
4. 单次刷新失败不会立即删除仍可用的 Cookie。
5. 短寿命 access token 到期不等于整个 QQ 登录态失效。
6. Python 在请求时携带 Cookie，不写入 `npm root --global` 下的包配置。

后台按照 `QQ_CREDENTIAL_*` 环境变量定时检查。`POST /api/qq/account/refresh` 只用于手工排障。账号撤销、设备风控或平台协议变化仍可能要求重新扫码。

## Bilibili

`bili_utils.py` 使用共享 requests Session 访问 Bilibili 首页和 API，获取必要的设备 Cookie，并支持：

- 二维码登录与 SESSDATA 验证。
- 用户资料和收藏夹。
- 搜索、BV 号直解析与分 P。
- DASH 音频 URL 解析。

Bilibili 不经过本地 Node 服务。带复杂查询参数的 DASH URL 必须作为参数数组传给 FFmpeg，不能先交给 shell 解释。

## 队列元数据

队列和 UI 优先使用显式的 `title`、`artist` 以及兼容字段。播放 URL 不作为标题回退，避免临时签名、账号参数或哈希出现在页面和日志中。

三平台的延迟标记只存在于队列内部：

- `PLAYLIST_SONG:<id>:<name>:<artist>`
- `QQ_PLAYLIST_SONG:<songmid>:<name>:<artist>`
- `BILI_PLAYLIST_SONG:<bvid>:<page>:<name>:<artist>`

## 迁移与安全

迁移账号时停止两边实例，并只复制对应 Cookie 文件。QQ 的两个文件应成对迁移；不要复制日志、二维码、`.env`、`node_modules` 或全局 npm 包配置。

所有凭据都必须：

- 由 Git 忽略。
- 只由服务端读取。
- 不写入浏览器 localStorage。
- 不返回完整值给前端。
- 不出现在公开日志、截图和问题单中。

完整安全边界见 [security.md](security.md)。
