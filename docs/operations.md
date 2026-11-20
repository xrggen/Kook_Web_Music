# 运维与故障恢复

## 启动基线

每次部署或升级后先确认：

```bash
node --version
npm root --global
```

Node.js 必须为 20+，全局模块目录必须位于项目外。启动日志还应显示两个 Node API 的全局包路径、FFmpeg 路径、Bot 状态和 Flask 监听地址。

同时确认：

- 平台目录可写 `data/`；
- `data/kook_music.db` 能正常打开/初始化；
- `.env` 中 `SECRET_KEY` 与 `AUTH_*` 配置正确；
- 公网 HTTPS 部署已设置 `AUTH_COOKIE_SECURE=true`。

### Cloud 显示 Edge 离线，但本地页面和 Bot 正常

先确认启动入口。`windows/run.py` 和 `Ubuntu/run.py` 启动单机模式，只有 `edge/run.py` 会启动出站 WSS Supervisor。

Windows 在仓库根目录运行 `start-edge.cmd` 或 `python edge/run.py`；Ubuntu 运行 `python3 edge/run.py`。切换入口前先停止旧进程，完整重启会清空内存播放队列。已有音乐 API 依赖、本地数据库和远端节点配置可以直接复用。

日志应同时出现 `Edge remote supervisor started` 和 `Edge relay connected`。Cloud 的 `/healthz` 应返回 `edge_connected: true`。Edge 的看门狗完整重启会保留 `edge/run.py` 入口和原启动参数。

若入口正确但仍离线，登录本地设置页检查远端节点状态、端口池和错误码。WSS 端口在未携带 Agent Token 时返回 `401`，说明 TLS 和 Relay 可达；这项检查不能证明 Agent 已成功认证。不要为恢复连接关闭 TLS 校验或删除配置数据库。

## 日志、审计与状态

平台目录中的主要运行日志：

- `debug.log`：Python、Flask、Bot、播放器和 watchdog。
- `netease_api_output.log`：网易云 Node API。
- `qq_api_output.log`：QQ 音乐 Node API。

SQLite `audit_logs` 记录：

- 登录成功/失败/限速；
- 注销；
- Bootstrap 管理员创建；
- 密码修改；
- 用户创建、修改、删除和密码重置；
- 已认证且成功的写 API。

审计数据包含用户名、来源 IP、资源 ID 等安全上下文，只能作为受控运维数据处理。

管理员状态入口：

- `/status`：可视化运行状态。
- `GET /api/stats`：播放与组件摘要。
- `GET /api/system/status`：主机和进程统计。
- `GET /api/debug`：Bot、loop、gateway 与队列摘要。

这些入口均要求 Admin Session；写操作还要求 CSRF。

排障按时间线关联主日志、Node API 日志、SQLite 审计和 FFmpeg 错误。对外分享前删除 Token、Cookie、用户名/IP、用户/频道 ID、临时密码和完整签名 URL。

## Cloud 在线但 KOOK 指令没有响应

Cloud 的 `edge_connected=true` 仅说明 Cloud/Edge 的出站 WSS 正常。KOOK Bot 使用另一条 WebSocket；须分别检查 KOOK 握手、心跳和消息入口。

固定版本 SDK 的网关接收器通过 `bot_gateway.py` 补充处理：收到服务端 `s=5` 后清除旧序号/待处理网关事件并重新获取网关；HELLO 非成功、6 秒内未收到 HELLO/PONG 时关闭旧连接重连；断开时取消旧心跳任务。只有成功握手后的有效事件/PONG 才刷新在线状态。该恢复不重建播放器、音乐 API 或 Cloud/Edge 服务。

管理员 `GET /api/debug` 中的 `kook_gateway` 包含事件数、消息入口数、白名单拒绝数及最近活动时间，不返回消息内容、账号 ID、Session 或网关 URL。排障时可在启动进程环境中设置 `KOOK_BOT_DIAGNOSTICS_PATH` 为共享 env 内的非敏感 JSON 路径；每次 Bot 心跳和文字消息入口会写入同类快照及白名单维度数量，不读取或复制凭据文件。

- KOOK 已成功握手但测试期间 `events_received`、`messages_received` 都不增加：继续检查开发者后台的消息过滤/订阅、机器人所在服务器与频道的可见权限，以及是否有别处启动的相同机器人连接。
- `messages_received` 与 `messages_denied` 一起增加：现有 Bot 白名单拒绝了消息。按授权范围由管理员配置，不通过放开所有用户来排障。
- 有消息且未被拒绝，但无回复：核对 `/ping` 的指令入口/处理输出、消息格式及 KOOK 发送消息权限/配额。

诊断快照是排障材料，按项目发布收尾流程保留当前必要证据；不要读取可能包含凭据的既有原始日志。

## Web 鉴权问题

### 无法登录

依次检查：

1. 用户名是否正确；Bootstrap 用户为 `gen`。
2. 账号是否被禁用。
3. 是否触发登录失败限速。
4. 系统时间是否异常。
5. `data/kook_music.db` 是否可读写。
6. 是否错误恢复了旧数据库。
7. 是否把反向代理来源 IP 配置错误，导致大量用户共享/伪造同一限速 IP。

不要通过删除数据库“修复”登录；这会删除全部用户、Scope 和审计数据。

### 登录后被要求改密

这是 `must_change_password=1` 的正常行为。Bootstrap 用户和管理员重置密码后的用户都必须先完成 `/change-password`。

### API 返回 401 / 403 / 428 / 429

- `401`：Session 缺失、过期、被撤销或账号失效。
- `403`：Role、Scope 或 CSRF 不通过。
- `428`：首次/重置后必须改密。
- `429`：登录失败限速。

### 修改用户后对方立即掉线

这是预期行为。角色、启用状态、密码变化会提升 `auth_version` 或撤销 Session，旧 Session 立即失效。

## SQLite 维护

默认数据库：

```text
data/kook_music.db
```

数据库启用 WAL；运行时可能存在：

```text
kook_music.db
kook_music.db-wal
kook_music.db-shm
```

不要只在在线状态复制主 `.db` 作为备份。推荐：

1. 停止实例；
2. 确认进程退出；
3. 备份整个 `data/`；
4. 再启动。

若必须在线备份，使用 SQLite 一致性备份机制。

数据库损坏或升级失败时，先保留原文件副本，再恢复最近已验证备份。不要执行未知来源的 SQLite 修复脚本直接覆盖生产库。

## Watchdog

watchdog 不以 Flask 端口单一判定健康，而分别观察 Bot 生命周期、事件循环 heartbeat、KOOK gateway 活动、Web 和两个本地 API。

两个 Node API 的启动检查和存活检查使用本地静态首页 `/`，不调用依赖上游平台的搜索、登录接口。搜索耗时或平台限流不代表本地 API 进程已失效。

恢复顺序：

1. 等待启动宽限期。
2. 连续失败达到阈值后修复单个 Node API。
3. 仅 Node API 故障时保持降级状态并按冷却时间继续单独修复，不中断机器人或正在播放的会话；Bot/Web 持续异常时才请求完整重启。
4. 完整重启受时间窗、次数预算和退避限制。
5. 重启前停止播放会话并回收本应用持有的子进程。

阈值由 [deployment.md](deployment.md#配置) 中的 `WATCHDOG_*` 环境变量控制。

watchdog 不修改 Web 用户、密码或 Scope。

## Node API

网易云 18474 异常时检查：

- `NeteaseCloudMusicApi@4.25.0` 是否全局安装。
- `npm root --global` 是否可读且位于项目外。
- `netease_api_output.log`。
- `MUSIC_API_PORT` 是否被占用；应用只会访问对应的 `127.0.0.1` 端口。

QQ 18475 异常时检查：

- `@sansenjian/qq-music-api@2.3.1` 是否全局安装。
- 全局包中的 `dist/app.js` 是否存在。
- `qq_api_output.log`。
- 项目内是否误放 `node_modules`，启动器会拒绝这种环境。

不要通过在项目中重新安装依赖来绕过故障。

## 端口冲突

Windows：

```powershell
Get-NetTCPConnection -State Listen -LocalPort 18473,18474,18475 |
  Select-Object LocalAddress,LocalPort,OwningProcess
Get-CimInstance Win32_Process -Filter "ProcessId=<PID>" |
  Select-Object ProcessId,ExecutablePath,CommandLine
```

Ubuntu：

```bash
ss -ltnp | grep -E ':(18473|18474|18475)\b'
ps -fp <PID>
```

优先正常停止旧实例。只能在命令行、工作目录和父子关系确认后终止 PID；不要批量结束全部 Node、Python 或 FFmpeg。

## 播放卡死

`/脱离卡死` 会对目标频道执行恢复栅栏、停止当前任务、请求 KOOK 离开、等待处理器退出、超时回收已登记媒体进程，并在解除栅栏前复核处理器所有权。

若仍失败，记录频道匿名标识、发生时间、当前歌曲元数据和相关日志，再重启实例。不要把“杀死所有 ffmpeg”作为首选方案。

## 账号问题

QQ 登录频繁失效：

1. 确认 `qq_cookie.txt` 与 `qq_credential.json` 属于同一账号。
2. 检查 Credential 是否具有可用 musickey 或 refresh 凭据。
3. 查看自动刷新日志。
4. 必要时由管理员调用 `POST /api/qq/account/refresh` 一次。
5. 只有凭据被撤销或触发风控时才重新扫码。

Bilibili 返回 `-412` 或取链失败时，检查 Session 预热、User-Agent/Referer、SESSDATA、网络和 FFmpeg 参数；不要用 shell 执行 DASH URL。

网易云登录异常时，先检查 18474 探针和 `Cookie/cookie.txt`，再由管理员从账号页重新验证。

## 备份与恢复

需要备份的持久运行数据：

```text
.env
Cookie/
data/
```

其中：

- `.env`：Bot Token、Secret Key、部署参数；
- `Cookie/`：三音乐平台登录态；
- `data/`：Web 用户、Session、Scope、登录尝试和审计。

日志可按运维策略轮转，不作为账号恢复依据。

恢复顺序：

1. 停止目标实例；
2. 部署代码和系统依赖；
3. 恢复 `.env`；
4. 恢复 `Cookie/`；
5. 恢复 `data/`；
6. 限制文件权限；
7. 启动；
8. 验证 Admin 登录、普通用户 Scope、三音乐平台和播放。

数据库恢复会恢复旧 Session。由于 Session 具有过期时间和 `auth_version`，通常仍会按当前数据判断有效性；若备份暴露或恢复环境变化较大，建议在数据库层撤销现有 Session 或通过密码/角色变化使旧 Session 失效。

## 安全事件

如果怀疑 Web Session、管理员密码或音乐平台凭据泄漏：

- 管理员密码：立即修改；
- 用户 Session：禁用/修改角色/重置密码可使其失效；
- Bot Token：从 KOOK 侧轮换；
- QQ/Bilibili/网易云凭据：从对应平台或本地账号管理重新登录/撤销；
- 数据库泄漏：视为用户、Scope、IP、Hash 与审计数据泄漏，轮换管理员密码并评估所有 Session。

## 问题记录

问题单至少包含平台、提交 SHA、启动方式、发生时间、复现步骤、脱敏后的最近日志和管理员可见的 `/api/debug` 摘要。

不要附：

- 真实 Token/Cookie；
- SQLite 数据库；
- 管理员密码或临时密码；
- Session/CSRF；
- 完整媒体 URL。

## 打包/发布后的 env 历史清理

打包验证或授权发布及验收完成后，执行 [项目收尾流程](release-workflow.md#4-env-历史清理末尾必做) 的末尾必做阶段，并读取 `C:\Users\Administrator\Desktop\VibeCoding\env\configs\workflows\post-release-env-cleanup.md`。仅处理本项目、自己会话的过时项；保留运行目录、当前交付、共享依赖和必要回滚集。凭据及认证目录不读取、不哈希、不备份、不清理。

handoff 与回执记录删除路径、文件数、逻辑大小、保留项及理由；没有符合条件的项时记录“已检查，无可清理历史项”。
