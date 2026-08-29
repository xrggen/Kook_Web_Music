# 运维与故障恢复

## 启动基线

每次部署或升级后先确认：

```bash
node --version
npm root --global
```

Node.js 必须为 20+，全局模块目录必须位于项目外。启动日志还应显示两个 Node API 的全局包路径、FFmpeg 路径、Bot 状态和 Flask 监听地址。

## 日志与状态

平台目录中的主要文件：

- `debug.log`：Python、Flask、Bot、播放器和 watchdog。
- `netease_api_output.log`：网易云 Node API。
- `qq_api_output.log`：QQ 音乐 Node API。

状态入口：

- `/status`：可视化运行状态。
- `GET /api/stats`：播放与组件摘要。
- `GET /api/system/status`：主机和进程统计。
- `GET /api/debug`：Bot、loop、gateway 与队列摘要。

排障按时间线关联主日志、Node API 日志和 FFmpeg 错误。对外分享前删除 Token、Cookie、用户/频道 ID 和完整签名 URL。

## Watchdog

watchdog 不以 Flask 端口单一判定健康，而分别观察 Bot 生命周期、事件循环 heartbeat、KOOK gateway 活动、Web 和两个本地 API。

恢复顺序：

1. 等待启动宽限期。
2. 连续失败达到阈值后修复单个 Node API。
3. 组件修复无效或 Bot/Web 持续异常时请求完整重启。
4. 完整重启受时间窗、次数预算和退避限制。
5. 重启前停止播放会话并回收本应用持有的子进程。

阈值由 [部署文档](deployment.md#配置) 中的 `WATCHDOG_*` 环境变量控制。

## Node API

网易云 3000 异常时检查：

- `NeteaseCloudMusicApi@4.25.0` 是否全局安装。
- `npm root --global` 是否可读且位于项目外。
- `netease_api_output.log`。
- `MUSIC_API_BASE` 是否被错误覆盖。

QQ 3200 异常时检查：

- `@sansenjian/qq-music-api@2.3.1` 是否全局安装。
- 全局包中的 `dist/app.js` 是否存在。
- `qq_api_output.log`。
- 项目内是否误放 `node_modules`，启动器会拒绝这种环境。

不要通过在项目中重新安装依赖来绕过故障。

## 端口冲突

Windows：

```powershell
Get-NetTCPConnection -State Listen -LocalPort 3000,3200,5000 |
  Select-Object LocalAddress,LocalPort,OwningProcess
Get-CimInstance Win32_Process -Filter "ProcessId=<PID>" |
  Select-Object ProcessId,ExecutablePath,CommandLine
```

Ubuntu：

```bash
ss -ltnp | grep -E ':(3000|3200|5000)\b'
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
4. 必要时调用 `POST /api/qq/account/refresh` 一次。
5. 只有凭据被撤销或触发风控时才重新扫码。

Bilibili 返回 `-412` 或取链失败时，检查 Session 预热、User-Agent/Referer、SESSDATA、网络和 FFmpeg 参数；不要用 shell 执行 DASH URL。

网易云登录异常时，先检查 3000 探针和 `Cookie/cookie.txt`，再从账号页重新验证。

## 备份与恢复

需要备份的运行数据只有当前平台的 `.env` 与 `Cookie/`。日志可按运维策略轮转，不作为账号恢复依据。

恢复时先部署代码和系统依赖，再恢复配置与凭据，最后启动并执行 [部署验证](deployment.md#启动与验证)。

## 问题记录

问题单至少包含平台、提交 SHA、启动方式、发生时间、复现步骤、脱敏后的最近日志和 `/api/debug` 摘要。不要附真实凭据或完整媒体 URL。
