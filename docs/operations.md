# 运维、健康检查与故障恢复

## 1. 日志

主要运行日志写入当前平台目录。Windows 主线使用可轮转 `debug.log`。本地 Node API 也各自写运行输出日志。

排障时优先按时间线查看：

1. Flask / Bot 主日志。
2. 网易云 API 输出。
3. QQ API 输出。
4. FFmpeg 失败上下文。
5. `/status` 或 `/api/debug` 的健康状态。

不要把包含 Cookie、Token、签名播放 URL 的完整日志直接贴到公开问题单。

## 2. 健康状态

`runtime_health.py` 记录至少包括：

- Bot 生命周期状态。
- Bot event loop heartbeat。
- KOOK gateway heartbeat / probe 可用性。
- supervisor ready 状态。

Web 状态页使用这些数据判断“在线 / 警告 / 异常”，而不是只看 Flask 端口是否能访问。

## 3. Watchdog

watchdog 的目标是分级恢复，而不是出现任何异常就整进程重启。

大致策略：

1. 启动宽限期内避免误判。
2. 连续检查 Bot loop、KOOK gateway、Web、本地网易云 API、QQ API。
3. 单个外部 API 连续异常时优先只修复该组件。
4. Bot/Web 持续异常或组件修复无效时才升级为完整重启。
5. 完整重启受时间窗和次数预算限制，避免重启风暴。

## 4. 播放卡死

`/脱离卡死` 使用分阶段恢复：

1. 对目标频道建立恢复栅栏。
2. 请求当前播放任务停止。
3. 请求 KOOK 脱离语音频道。
4. 等待 PlayHandler 正常退出。
5. 超时后回收该处理器登记的 FFmpeg/ffprobe。
6. 必要时隔离旧处理器。
7. 解除恢复栅栏前再次确认所有权，避免旧线程清理新会话。

不建议通过“杀掉所有 ffmpeg/node 进程”作为默认恢复手段。

## 5. 本地 Node API 故障

### 网易云 3000

检查：

- 目录是否存在。
- Node 是否在 PATH。
- `npm install` 是否完成。
- 端口是否被其他程序占用。
- API 日志是否立即退出。

如果本地 API 不可用，代码可能按配置回退到 `MUSIC_API_BASE`，但不应依赖未知公网代理作为长期生产方案。

### QQ 3200

检查：

- `package.json` 是否存在。
- `node_modules` 是否安装。
- `dist/app.js` 是否存在。
- `npm run build` 是否成功。
- 3200 端口是否属于本项目进程。

## 6. QQ 登录频繁失效

当前应先检查 Credential 生命周期，而不是直接让用户重新扫码：

1. `qq_cookie.txt` 是否存在。
2. `qq_credential.json` 是否已经迁移生成。
3. Credential 是否包含 refresh token / refresh key 或可兼容的 musickey。
4. 自动刷新日志是否成功写回新 Cookie。
5. 是否只是 access token 过期，而 musickey 仍有效。
6. 是否触发账号风控/设备限制。

必要时通过账号页面或 `POST /api/qq/account/refresh` 手工触发一次续期检查。

## 7. Bilibili -412 / 取链失败

优先检查：

- Session 预热是否成功。
- User-Agent / Referer 是否正常。
- SESSDATA 是否有效。
- 是否使用参数数组启动 FFmpeg。
- 是否使用正确的网络超时参数。

不要把 DASH URL 先交给 shell 再执行。

## 8. Web UI 状态异常

如果桌面正常、移动端异常：

- 确认 `theme-init.js` 已加载 `mobile.css`、`mobile-polish.css`、`mobile-ui.js`。
- 清除浏览器旧缓存或确认资源版本号。
- 检查宽度是否小于等于 820px。
- iOS 上检查 safe area 和 Visual Viewport。

如果主题跨页面丢失，检查 `kook.ui.theme` 和共享 `_app_sidebar.html` 中的早期初始化脚本。

## 9. 推荐故障记录格式

报告问题时至少保留：

- 平台：Windows/Ubuntu。
- 提交 SHA。
- 启动方式。
- 问题发生时间。
- 服务器/频道可用匿名代号，不贴真实敏感 ID。
- 最近 50~100 行相关日志（脱敏）。
- 问题是否可重复。
- `/status` 或 `/api/debug` 的关键状态。
