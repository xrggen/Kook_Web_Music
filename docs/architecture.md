# 架构与运行机制

## 系统边界

项目由两个可独立部署的平台目录、一个共享系统 Node 环境和外部平台组成。

```text
Web 浏览器 ─┐
             ├─> Flask 路由 / KOOK Bot 命令
KOOK Gateway ┘              │
                            ├─> 网易云适配器 ─> 127.0.0.1:3000
                            ├─> QQ 适配器 ───> 127.0.0.1:3200
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

`windows/` 与 `Ubuntu/` 都包含完整 Python 应用。共享业务实现保持一致，平台差异集中在 FFmpeg 来源、系统服务和部署命令。

## 启动生命周期

`run.py` 是唯一启动入口，按以下顺序工作：

1. 将工作目录固定到当前平台目录并加载该目录的 `.env`。
2. 从主机 PATH 解析项目目录外的 `node` 和 `npm`，校验 Node.js 20+。
3. 通过 `npm root --global` 定位两个固定版本的全局 Node 包。
4. 拒绝仓库内残留的 `node_modules` 或自带 Node 工具链。
5. 启动网易云 API（3000）和 QQ 音乐 API（3200），输出写入平台目录日志。
6. 创建 Flask 应用与 KOOK Bot 线程。
7. 启动健康状态采集和 watchdog。
8. 按 `HOST`、`PORT`、`DEBUG` 启动 Web 服务。

所有 Node 子进程共用系统 Node 环境。Python 不执行 `npm install`、不构建 Node API，也不会回退到仓库内运行时。Bilibili 不需要本地 Node 服务。

## 组件职责

| 组件 | 职责 |
|---|---|
| `app.py` | Flask 应用、KOOK Bot、命令、Bot 事件循环 |
| `routes.py` | 页面、频道、播放、状态和运维路由 |
| `account_api.py` | 网易云账号与公共账号页面 |
| `qq_account_api.py` | QQ 登录、资料、歌单与手工续期 |
| `bili_account_api.py` | Bilibili 登录、资料和收藏夹 |
| `utils.py` / `qq_utils.py` / `bili_utils.py` | 平台搜索、取链和歌单适配 |
| `qq_credential.py` | QQ 凭据迁移、刷新、锁和原子写入 |
| `kookvoice/` | 语音会话、播放线程、FFmpeg 与 RTP |
| `runtime_health.py` | Bot、事件循环、网关和 supervisor 状态 |
| `service_watchdog.py` / `run.py` | 故障判定、组件修复和受限重启 |

## 会话与并发

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

## 登录态

所有凭据都保存在当前平台的 `Cookie/` 目录。Python 请求按次携带 QQ Cookie，不修改系统全局 npm 包的配置。

QQ 同时维护兼容 Cookie 和 Credential 元数据。后台定时检查凭据，在可刷新时原子写回；单次刷新失败不会立即删除仍可用的登录态。各文件及迁移方法见 [音乐平台文档](music-platforms.md)。

## 健康检查与恢复

运行状态区分 Flask 可达、Bot 生命周期、Bot loop heartbeat、KOOK gateway 活动和本地 API 可用性。watchdog 采用分级恢复：

1. 启动宽限期内不做激进处理。
2. 连续失败后先重启单个 Node API。
3. Bot/Web 持续异常时才请求完整进程重启。
4. 完整重启受时间窗、次数预算和退避限制。
5. 重启前先停止播放会话并回收本应用创建的子进程。

## Web 与 UI

桌面和移动端复用同一套页面、API 和业务状态。桌面使用导航、主工作区、队列和全局播放器；`max-width: 820px` 时切换为底部导航、迷你播放器和 Bottom Sheet。前端不维护单独的移动 API 或第二份播放状态。

## 平台一致性

`scripts/check_platform_sync.py` 定义共享文件清单。共享 Python、模板、静态资源和测试应保持字节一致。平台专属内容限于：

- Windows 随包 FFmpeg 与 Ubuntu 系统 FFmpeg。
- 平台服务管理、路径和安装命令。
- Ubuntu 专属 `/monitor` 页面；Windows 该路由返回 404。

任何长期业务分叉都应先收敛为共享实现或明确的平台适配点。
