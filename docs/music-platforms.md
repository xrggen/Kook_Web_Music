# 音乐平台接入与账号凭据

## 1. 三平台不是同一种接入方式

| 平台 | 搜索/数据入口 | 账号凭据 | 本地服务 |
|---|---|---|---|
| 网易云 | 本地 NeteaseCloudMusicApi | `cookie.txt` | Node，默认 3000 |
| QQ 音乐 | 本地 qq-music-api + Python 直连签名接口 | `qq_cookie.txt` + `qq_credential.json` | Node，默认 3200 |
| Bilibili | Python 直接调用 Bilibili REST/DASH | `bili_cookie.txt`（主要为 SESSDATA） | 无 |

不要为了代码形式统一而强行把三者改成同一种代理层。应以稳定性、协议生命周期和维护成本为优先。

## 2. 网易云音乐

### 搜索与播放

`utils.py` 负责主要搜索、歌单和播放 URL 解析。大歌单使用延迟标记，降低一次性请求数量。

### 登录

支持：

- Web 扫码。
- 手机验证码。
- 手工 Cookie。

凭据继续保存在服务端 Cookie 文件，不写入浏览器 localStorage。

## 3. QQ 音乐

### 搜索与播放

QQ 音乐同时使用本地 `qq-music-api` 和部分 Python 侧签名 API。公开歌单等场景可能不依赖登录 Cookie；会员/个人数据和部分取链能力则依赖账号状态。

### Credential Manager

当前登录生命周期不再只是静态保存 Cookie。

核心文件：

```text
qq_cookie.txt       兼容现有播放/搜索代码的 Cookie 串
qq_credential.json  Credential 生命周期数据
```

Credential 中可能包含：

- uin / musicid
- qqmusic_key / qm_keyst / musickey
- refresh_token
- refresh_key
- access_token
- openid / unionid
- login_type
- expiry / refresh metadata

### 自动续期原则

1. 旧 `qq_cookie.txt` 可自动迁移。
2. 有完整 refresh 凭据时优先走 refresh-token 路线。
3. 仅有 musickey 时使用兼容刷新 fallback。
4. 刷新成功必须原子写回新的 Credential 与兼容 Cookie。
5. 刷新使用锁，避免多个请求同时刷新同一账号。
6. 单次刷新失败不立即退出登录；旧凭据仍有效时继续使用。
7. 不再把短寿命 access token 的过期等同于整个 QQ 音乐登录态失效。

账号页面可通过 `POST /api/qq/account/refresh` 手工触发续期，用于排障；正常运行由后台机制处理。

### 风控边界

自动续期不能承诺永久登录。以下情况仍可能要求重新扫码：

- 服务端撤销 refresh token。
- 账号或设备风控。
- QQ 音乐协议升级。
- 登录频率/设备数量限制。

## 4. Bilibili

### 直连架构

`bili_utils.py` 直接使用 Bilibili 公网接口，不依赖本地 Node API。

主要能力：

- 二维码登录。
- SESSDATA 保存/验证。
- 账号资料。
- 收藏夹。
- 搜索、BV 直解析、分 P。
- DASH 音频播放 URL。

### Session 预热

共享 requests Session 会访问 Bilibili 首页/API 获取设备 Cookie（例如 buvid 类标识），用于降低匿名直连接口触发 `-412` 风控的概率。

### 媒体注意事项

Bilibili DASH 音频 URL 可能带复杂查询参数。媒体进程必须使用参数数组创建，避免 shell 对 URL 中 `%`、`&` 等字符进行二次解释。

## 5. 统一展示元数据

Web 队列展示应优先使用显式元数据：

- `title` / `artist`
- 兼容旧 KOOK 命令的 `音乐名字` 等字段

网络播放 URL 不能作为歌曲标题的 fallback。缺失元数据时显示“未知歌曲/未知歌手”，避免把哈希、URL 尾部或签名参数暴露到 UI。

## 6. 凭据文件安全

所有 Cookie/Credential 文件都属于敏感信息：

- 不提交到 Git。
- 不记录到公开日志。
- 不通过前端返回完整 Cookie。
- 不在问题单、截图或文档中粘贴真实值。

详细边界见 [security.md](security.md)。
