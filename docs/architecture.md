# 运行时架构

## 1. 总览

KOOK Music 是一个 Windows/Ubuntu 双目录部署的 Flask + KOOK Bot + FFmpeg 音频推流应用。Windows 是共享运行时的权威主线，Ubuntu 对共享代码保持字节一致；平台差异通过路径解析、`sys.platform` 和系统依赖收敛。

核心链路：

```text
Web / KOOK 命令
        ↓
Flask routes / app.py
        ↓
平台适配层
├─ utils.py          网易云
├─ qq_utils.py       QQ 音乐
└─ bili_utils.py     Bilibili
        ↓
kookvoice.Player
        ↓
每个 channel_id 一个播放会话
        ↓
PlayHandler 后台线程 + 独立 asyncio loop
        ↓
FFmpeg 解码 → PCM → FFmpeg libopus 编码 → RTP → KOOK
```

## 2. 应用入口

`run.py` 负责：

1. 固定工作目录到当前平台目录。
2. 显式加载该目录下 `.env`。
3. 启动网易云本地 Node API（默认 3000）。
4. 启动 QQ 音乐本地 Node API（默认 3200）。
5. 创建 Flask 应用和 KOOK Bot 线程。
6. 启动运行健康状态与 watchdog。
7. 以 `HOST` / `PORT` 启动 Web 服务。

Bilibili 不启动额外本地 API 进程，Python 直接调用 Bilibili 公网 REST/DASH 接口。

## 3. 会话模型

播放状态以 `channel_id` 为主键，而不是 guild 级全局状态。这意味着同一 KOOK 服务器内多个语音频道可以拥有独立队列和播放状态。

共享状态由 `kookvoice.state_lock`（`threading.RLock`）保护。Web 查询使用状态快照，避免前端读取过程中与播放线程并发修改同一个可变对象。

同一频道严格限制为一个有效 `PlayHandler`。停止、卡死恢复和重新加入过程中通过处理器所有权检查避免“旧线程迟到退出”清理新会话。

## 4. 播放线程与事件循环

每个活跃语音频道的 `PlayHandler` 在 daemon thread 中运行，并拥有自己的 asyncio event loop。该线程负责当前歌曲的媒体进程生命周期和 RTP 推流。

KOOK Bot 自身有独立事件循环。`kookvoice.set_loop()` 建立播放线程向 Bot loop 调度通知的桥接，避免跨线程直接操作异步对象。

## 5. 媒体管道

当前播放流程使用两个 FFmpeg 角色：

- 解码端：网络 URL / 本地媒体 → 48 kHz 双声道 PCM。
- 编码端：PCM → Opus → RTP。

所有媒体子进程都应遵守“创建时登记、结束时等待、异常时幂等回收”的原则。Windows 端进程清理还会验证工作目录/进程归属，避免误杀其他 Node 或媒体进程。

## 6. 歌单延迟解析

大歌单导入不在加入队列时一次性解析所有播放 URL，而使用标记：

- `PLAYLIST_SONG:<id>:<name>:<artist>`
- `QQ_PLAYLIST_SONG:<songmid>:<name>:<artist>`
- `BILI_PLAYLIST_SONG:<bvid>:<page>:<name>:<artist>`

队列前若干首会预取，其余在接近播放或实际播放时解析。这是降低 API 突发请求和签名 URL 过期风险的重要机制。

## 7. Web 层

主要页面：

- `/dashboard` — 播放控制、搜索、服务器/频道、队列、播放器。
- `/library` — 三平台账号歌单聚合。
- `/account` — 网易云 / QQ / Bilibili 账号中心。
- `/status` — 运行健康状态。
- `/settings` — 浏览器端 UI 偏好。

`/` 当前进入新的应用式控制台体验，不再以旧营销首页为主入口。

## 8. 前端共享层

桌面与移动端复用同一套模板和后端业务状态：

- `app.css` — 应用壳和共享页面组件。
- `dashboard.css` — 播放页桌面布局。
- `theme.css` — 深色/浅色覆盖层。
- `mobile.css` — `<= 820px` 移动端布局层。
- `app-ui.js` — 主题/密度/减少动画与健康灯。
- `mobile-ui.js` — Bottom Sheet、移动播放器、移动导航行为。
- `dashboard.js` — 核心播放页业务，不因移动端复制一份。

## 9. Windows / Ubuntu 同步原则

`scripts/check_platform_sync.py` 定义共享文件清单。共享实现必须保持字节一致。允许存在的差异主要是：

- Windows 随包 FFmpeg vs Ubuntu 系统 FFmpeg。
- 平台部署说明和打包资产。
- 由代码内部平台判断处理的 OS 行为。

禁止为了修一个平台的问题直接长期分叉两份共享业务逻辑。
