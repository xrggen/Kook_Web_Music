# 架构与运行机制

## 系统边界

项目由两个可独立部署的平台目录、一个共享系统 Node 环境和外部平台组成。

```text
Web 浏览器
    │
    ├─> Flask Auth Middleware
    │      ├─> SQLite: users / sessions / scopes / audit
    │      └─> Role + Scope + CSRF
    │
    ├─> Flask 页面 / HTTP API ─────────┐
    │                                  │
KOOK Gateway ─> KOOK Bot 命令 ─────────┤
                                       ├─> 网易云适配器 ─> 127.0.0.1:18474
                                       ├─> QQ 适配器 ───> 127.0.0.1:18475
                                       └─> Bilibili 适配器 ─> 公网 REST / DASH
                                                 │
                                                 ▼
                                      channel_id 播放会话
                                                 │
                                    FFmpeg 解码 → PCM → Opus/RTP
                                                 │
                                                 ▼
                                          KOOK 语音频道
```

Web 控制面持久化和实时播放状态刻意分离：

- SQLite 保存用户、Session、授权 Scope、登录尝试和审计；
- `kookvoice` 内存状态保存队列、当前播放、循环模式和 `PlayHandler`；
- 不把每帧/每秒播放状态写入 SQLite。

`windows/` 与 `Ubuntu/` 都包含完整 Python 应用。共享业务实现保持一致，平台差异集中在 FFmpeg 来源、系统服务和部署命令。

## 启动生命周期

`run.py` 是唯一启动入口，按以下顺序工作：

1. 将工作目录固定到当前平台目录并加载该目录的 `.env`。
2. 从主机 PATH 解析项目目录外的 `node` 和 `npm`，校验 Node.js 20+。
3. 通过 `npm root --global` 定位两个固定版本的全局 Node 包。
4. 拒绝仓库内残留的 `node_modules` 或自带 Node 工具链。
5. 启动网易云 API（18474）和 QQ 音乐 API（18475），输出写入平台目录日志。
6. 创建 Flask 应用与 KOOK Bot 线程。
7. 注册业务 Blueprint；`api.py` 的 `record_once` 安装统一 Web Auth Middleware 并初始化 SQLite。
8. 启动健康状态采集和 watchdog。
9. 按 `HOST`、`PORT`、`DEBUG` 启动 Web 服务。

所有 Node 子进程共用系统 Node 环境。Python 不执行 `npm install`、不构建 Node API，也不会回退到仓库内运行时。Bilibili 不需要本地 Node 服务。

## 组件职责

| 组件 | 职责 |
|---|---|
| `app.py` | Flask 应用、KOOK Bot、命令、Bot 事件循环 |
| `auth.py` | Web 身份、Session、CSRF、Role/Scope、SQLite IAM 与审计 |
| `api.py` | `/api/stats` 与 Auth Middleware 安装点 |
| `routes.py` | 页面、频道、播放、状态和运维路由 |
| `account_api.py` | 网易云账号与公共账号页面 |
| `qq_account_api.py` | QQ 登录、资料、歌单与手工续期 |
| `bili_account_api.py` | Bilibili 登录、资料和收藏夹 |
| `utils.py` / `qq_utils.py` / `bili_utils.py` | 平台搜索、取链和歌单适配 |
| `qq_credential.py` | QQ 凭据迁移、刷新、锁和原子写入 |
| `kookvoice/` | 语音会话、播放线程、FFmpeg 与 RTP |
| `runtime_health.py` | Bot、事件循环、网关和 supervisor 状态 |
| `service_watchdog.py` / `run.py` | 故障判定、组件修复和受限重启 |

## Web 控制面数据

默认 SQLite：

```text
data/kook_music.db
```

主要实体：

```text
users
 ├─ sessions
 ├─ user_scopes ── guilds ── channels
 └─ audit_logs

login_attempts
schema_migrations
```

数据库负责控制面身份与授权，不参与音频数据通路。

Admin 隐式拥有全局 Scope；User 固定拥有播放 Permission，再通过 Global/Guild/Channel Scope 限定资源。完整模型见 [authentication.md](authentication.md)。

## 会话与并发

### Web Session

Web Session 是数据库 Session，不等同于 KOOK 播放会话。浏览器持有随机 Session Token，数据库只保存 Hash。用户禁用、角色变化和密码变化会使旧 Session 失效。

### 播放会话

播放状态以 `channel_id` 为主键。同一 KOOK 服务器内的不同语音频道可以拥有独立队列、循环模式和播放处理器。

每个活跃频道最多有一个有效 `PlayHandler`。共享状态由 `kookvoice.state_lock` 保护，Web 查询读取快照；公网请求和媒体 I/O 在锁外执行。处理器退出或卡死恢复时会再次校验所有权，避免旧线程清理后创建的新会话。

每个 `PlayHandler` 在独立 daemon thread 中运行，并拥有自己的 asyncio event loop。KOOK Bot 使用另一事件循环；`kookvoice.set_loop()` 提供跨线程通知桥接。

## 播放与歌单

媒体链路分为两个进程角色：

1. 解码进程将网络或本地媒体转换为 48 kHz 双声道 PCM。
2. 编码进程将 PCM 编码为 Opus，并通过 RTP 推送到 KOOK。

子进程使用参数数组创建，不将签名 URL 交给 shell。进程在创建时登记，在完成、取消、超时和异常路径中幂等回收。

歌单不会在导入时解析全部临时播放 URL，而使用延迟标记：

- `PLAYLIST_SONG:<id>:<name>:<artist>`
- `QQ_PLAYLIST_SONG:<songmid>:<name>:<artist>`
- `BILI_PLAYLIST_SONG:<bvid>:<page>:<name>:<artist>`

队列前部按批次预取，其余歌曲接近播放时再解析，以减少突发 API 请求和临时 URL 过期。

## 音乐平台登录态

音乐平台凭据保存在当前平台的 `Cookie/` 目录，与 Web 用户 SQLite 分离。Python 请求按次携带 QQ Cookie，不修改系统全局 npm 包的配置。

QQ 同时维护兼容 Cookie 和 Credential 元数据。后台定时检查凭据，在可刷新时原子写回；单次刷新失败不会立即删除仍可用的登录态。各文件及迁移方法见 [music-platforms.md](music-platforms.md)。

## Web 请求链路

典型页面/API：

```text
HTTP Request
   ↓
Auth before_request
   ├─ 未登录 -> login / 401
   ├─ must_change_password -> change-password / 428
   ├─ CSRF 校验（写请求）
   └─ Role + Scope
   ↓
原业务 Route
   ↓
Auth after_request
   ├─ Guild/Channel 返回过滤
   ├─ 成功写请求审计
   └─ 安全响应头
   ↓
HTTP Response
```

这种设计把鉴权放在统一边界，尽量不侵入 FFmpeg、队列和 Bot 核心。

## 健康检查与恢复

运行状态区分 Flask 可达、Bot 生命周期、Bot loop heartbeat、KOOK gateway 活动和本地 API 可用性。watchdog 采用分级恢复：

1. 启动宽限期内不做激进处理。
2. 连续失败后先重启单个 Node API。
3. Bot/Web 持续异常时才请求完整进程重启。
4. 完整重启受时间窗、次数预算和退避限制。
5. 重启前先停止播放会话并回收本应用创建的子进程。

watchdog 不负责重置 Web 用户或 SQLite。

## Web 与 UI

桌面和移动端复用同一套页面、API 和业务状态。登录、强制改密、用户管理也为共享模板。

普通用户导航只展示允许页面；管理员可看到账号、系统、设置和用户管理入口。但 UI 隐藏不是安全控制，真正边界由服务端 Auth Middleware 实施。

## 平台一致性

`scripts/check_platform_sync.py` 定义共享文件清单。共享 Python、Auth、模板、静态资源和测试应保持字节一致。平台专属内容限于：

- Windows 随包 FFmpeg 与 Ubuntu 系统 FFmpeg。
- 平台服务管理、路径和安装命令。
- Ubuntu 专属 `/monitor` 页面；Windows 该路由返回 404。

任何长期业务分叉都应先收敛为共享实现或明确的平台适配点。

深度审计后形成的授权、进程、外部网络、凭据、前端和资源上限基线见 [security-hardening.md](security-hardening.md)。架构调整不得绕过其中定义的统一应用工厂、系统 Node、无通用 shell 和双平台同步约束。
