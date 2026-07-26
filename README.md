# KOOK音乐机器人 Web控制台

> **当前版本**: V2.7.5 | **发布日期**: 2026-07-26

### 版本历史

| 版本 | 日期 | 类型 | 说明 |
|------|------|------|------|
| **V2.7.5** | 2026-07-26 | 稳定性修复 | 重构 Windows 看门狗：以进程内单调时钟分别监测 Bot 事件循环和 KOOK 网关活动，增加 180 秒启动宽限、Web/网易云/QQ API 探针与单组件恢复；连续故障才执行完整重启，15 分钟最多 3 次并递增退避；重启前复用 `/脱离卡死` 清理播放会话并回收 Node 进程树；Python、`run.py`、Node/npm、`.env`、FFmpeg/ffprobe 和 Cookie 路径全部确定化，原位重启失败时可拉起替代进程；新增 12 项看门狗测试，总计 30 项 |
| **V2.7.4** | 2026-07-26 | 架构修复 | Windows 主线稳定性重构：同一语音频道严格限制为单一 `PlayHandler`，修复重复加入、停止竞态及“进入后马上退出”；播放状态统一加锁并提供只读快照；FFmpeg/ffprobe 子进程改为参数化启动、超时、身份校验与幂等回收；`/脱离卡死` 改为带频道栅栏的分阶段恢复；Bot/Web 心跳拆分并支持完整进程自愈；端口清理增加进程归属校验；应用工厂、日志轮转、前端频道状态及 QQ 歌单分页同步修复；新增 18 项稳定性测试 |
| **V2.7.3** | 2026-06-17 | 修复 | `/qqgd` 修复他人歌单导入失败：改用 `u6.y.qq.com` 签名 API（移植 GoMusic 方案），无需 cookie 支持任意公开歌单，支持分页（>30首）；修复 KOOK Markdown 链接 `[url](url)` 导致歌单 ID 提取错误（`/wygd` `/qqgd` `/bili歌单`）；修复 `/停止` 后残留 STOP 状态阻止下次自动播放 |
| **V2.7.2** | 2026-06-09 | 修复 | B站音频解码完整修复：`create_subprocess_exec` 替代 shell 避免 URL 中 `%` 被 cmd.exe 破坏；BV 号直解析跳过搜索；Session 预热绕过 -412 风控；解码失败快速跳过；UID 脱敏 |
| **V2.7.1** | 2026-06-09 | 修复 | B站二维码登录修复：QR API 域名修正为 `passport.bilibili.com`；服务端本地生成 QR 图片替代第三方 API；`/帮助` 指令新增 B站 四个指令 |
| **V2.7** | 2026-06-09 | 功能增强 | 新增 B站 (Bilibili) 平台支持：直接调用B站REST API（零外部依赖）、`/bili` `/bili歌单` `/bili我的歌单` `/bili当前账号` 指令、Web控制台B站搜索/歌单导入/账号管理（扫码登录+Cookie管理+收藏夹展示） |
| **V2.6.2** | 2026-06-09 | 修复 | 修复 `/脱离卡死` 因 `playlist_handle_status` 未导出导致 `AttributeError` 崩溃；修复 `正在播放通报` 因 `original_loop` 桥接缺失导致切歌通知永不触发（新增 `set_loop()` 在 bot 线程创建事件循环后建立跨线程事件调度通道） |
| **V2.6.1** | 2026-06-03 | 修复 | FFmpeg 子进程 stderr 管道改为 DEVNULL 消除缓冲区死锁；`/脱离卡死` 新增强制离开语音频道步骤（从根源切断 RTP 连接强制 FFmpeg 退出） |
| **V2.6** | 2026-06-03 | 功能增强 | 新增 `/随机播放` 指令（toggle 开关，开启时备份原序并打乱队列，关闭时恢复原序，自动联动 URL 预取） |
| **V2.5.1** | 2026-06-03 | 修复 | 修复 `/qqgd` 歌单解析路径（`cdlist[0]` 替代错误的 `data.detail`）；修复歌单歌曲字段映射（`mid`/`name` 替代 `songmid`/`songname`）；URL 改为查询参数传递 `disstid` |
| **V2.5** | 2026-06-03 | 功能增强 | 新增 `/wy我的歌单` `/qq我的歌单` 机器人指令；QQ音乐 Cookie 保活优化（多字段过期检测、2分钟缓存、前端有效期展示）；修复 QQ 歌单项字段映射（picurl/title/subtitle 解析） |
| **V2.4** | 2026-06-03 | 功能增强 | QQ音乐账号页面增强：新增头像/昵称展示、我的歌单网格（封面/歌曲数/播放数）、歌单统计；新增 `/api/qq/account/profile` 和 `/api/qq/account/playlists` 端点 |
| **V2.3.3** | 2026-06-03 | 修复 | QQ音乐扫码登录二维码显示及字段映射修复；asyncio 子进程管道泄漏修复（时长检测/main/push 三处补 finally 清理） |
| **V2.3.2** | 2026-06-02 | 修复 | `format_playlist_data` 普通文件分支补充缺失的 `duration` 字段，修复前端进度条恒 100% 的问题 |
| **V2.3.1** | 2026-06-01 | 修复 | `FFPROBE_PATH` 改为 `.env` 可配置项（去掉写死默认路径）；修复备用时长检测方法 `2>&1` 导致 stderr 管道空读的问题 |
| **V2.3** | 2026-05-29 | 功能增强 | 新增 `/脱离卡死` 指令（多级容错重置所有播放状态）；新增 `/版本信息` 指令（从 README 实时解析版本历史）；前端多频道状态隔离完善（API 补齐 `channel_id`、活跃频道状态标识、播放器频道名显示）；修复命令缺省参数导致 `ArgLenNotMatched` 崩溃 |
| **V2.2** | 2026-05-27 | 功能增强 | 重构会话键为 `channel_id`，支持跨服务器多频道独立播放；新增 `/单曲循环` 指令；修复 `run.py` 残留清理误杀其他 Node 应用（改为仅终止端口 3000/3200）；`PlayHandler` 补充 `QQ_PLAYLIST_SONG` 播放时实时解析 |
| **V2.1.1** | 2026-05-26 | 修复 | 修复白名单功能中替换 `bot.command` 导致 khl.py `Command.handle()` 调用链断裂的问题，改为仅包装 `bot.command.handle` 方法 |
| **V2.1** | 2026-05-26 | 功能增强 | 新增指令权限白名单：`.env` 中 `ALLOWGROUP`/`ALLOWCHANNEL`/`ALLOWUSER` 三个参数，支持按服务器/频道/用户三级过滤指令响应范围；多个白名单非空时取交集 |
| **V2.0** | 2026-05-19 | 重大更新 | 新增 QQ 音乐平台完整支持：集成 `qq-music-api` (Koa2 TypeScript, 端口3200)、新增 `/qq` `/qqgd` `/qq当前账号` 机器人指令、Web 控制台新增平台切换（网易云/QQ音乐）、账号管理页面新增 QQ 音乐扫码登录/Cookie 管理、`run.py` 并行启动双 API 服务 |
| **V1.4** | 2026-05-18 | 修复 | 修复 `shlex` 命令词法解析器未闭合引号导致全部命令崩溃；适配中文引号（`""''「」『』`→英文引号）；`/播放列表` 新增分页支持：`/播放列表 [页数]`（20首/页） |
| **V1.3** | 2026-05-16 | 功能增强 | 修复 Node API 端口抢占、启动卡死、asyncio 管道泄漏等问题；新增看门狗自愈机制；新增 `/清空列表` 命令；新增切歌主动通知；重写 `/wygd` 对齐 Web 控制台分页逻辑、支持歌单链接格式、解除50首限制；歌单导入改为批量预取URL（每批5首）；新增 `/播放第N首` 命令 |
| **V1.2** | 2026-05-15 | 初始版本 | 集成本地网易云音乐 API (NeteaseCloudMusicApi)；新增网易云账号管理页面 (`/account`)；新增 `/当前账号`、`/播放列表`、`/帮助` 机器人命令；完善全链路终端日志输出 |

### V2.7.4–V2.7.5 稳定性设计

- **单频道单处理器**：`Player.join()` 与 `add_music()` 共用受锁保护的处理器注册表，停止期间的新请求会等待旧处理器完成清理，避免重复 RTP 会话和旧线程误删新队列。
- **安全连接与资源回收**：加入频道不再预先无条件离开；只有首次加入失败时才清理残留会话并重试。KOOK 请求复用带超时的 `aiohttp.ClientSession`，FFmpeg/ffprobe 在正常结束、异常和取消路径都会回收。
- **紧急恢复分级升级**：`/脱离卡死` 先锁定恢复中的频道并线程安全地取消播放任务，并发请求 KOOK 脱离和等待处理器退出；超时后终止该处理器登记的 FFmpeg/ffprobe，最后隔离仍卡住的旧处理器，并在解除频道栅栏前再次确认 KOOK 脱离。所有权校验保证旧线程迟到退出时不会清理新会话，未获 KOOK 确认的频道会保留为下一次恢复目标。
- **并发状态边界**：播放线程、Bot 命令和 Web API 通过同一可重入锁修改状态，对外查询使用深拷贝快照；歌单预取采用“锁内取标记、锁外联网、锁内回填”。
- **Windows 自愈与进程治理**：进程内单调时钟分别记录 Bot 事件循环与 KOOK 网关活动，Web、网易云 API、QQ API 使用独立 HTTP/进程探针。外部 API 连续异常时先单独拉起；完整重启前复用紧急播放恢复并回收 Node 进程树，15 分钟重启预算最多 3 次，避免永久重启风暴。3000/3200 端口仍只清理工作目录属于本项目 API 的进程。
- **可迁移部署**：启动和重启固定使用绝对 Python、`run.py`、Node/npm 与 `windows` 工作目录；显式加载 `windows/.env`。FFmpeg、ffprobe 与 Cookie 的相对配置一律相对于 `windows` 解析，无效的旧媒体工具路径会回退到随包二进制；运行日志统一写入可轮转的 `windows/debug.log`。
- **验证**：`windows/tests/test_stability.py` 18 项加 `windows/tests/test_watchdog.py` 12 项，共 30 项测试，覆盖播放并发与停止竞态、紧急恢复、媒体进程身份校验、状态快照、QQ 分页，以及启动宽限、网关失联与兼容降级、连续故障复位、配置错误阻断、组件恢复、重启预算、替代进程和路径确定性。

---

一个功能完整的KOOK音乐机器人Web控制台，支持三大音乐平台（网易云 / QQ音乐 / B站）搜索与播放、歌单导入、远程控制、系统监控等功能。通过现代化Web界面管理KOOK服务器中的音乐播放，无需在聊天框输入命令。

## 项目架构

```
Kook_Web_Music/
├── windows/                          # Windows平台版本（主要开发目标）
│   ├── run.py                        # 应用入口，自动启动Node API服务 + Flask
│   ├── app.py                        # Flask应用核心 + 全部KOOK机器人命令
│   ├── config.py                     # 配置文件（Token、FFmpeg、API地址、ACL）
│   ├── runtime_health.py              # 线程安全的事件循环/KOOK网关健康状态
│   ├── service_watchdog.py            # 无副作用的看门狗判定器
│   ├── routes.py                     # Web API路由（服务器/频道/播放控制/系统监控）
│   ├── utils.py                      # 网易云工具（搜索/URL/歌单/标记模式）
│   ├── qq_utils.py                   # QQ音乐工具（搜索/URL/歌单/Cookie验证）
│   ├── bili_utils.py                 # B站工具（搜索/BV解析/DASH音频/收藏夹/扫码登录）
│   ├── account_api.py                # 网易云账号管理路由（扫码/手机/验证码登录）
│   ├── qq_account_api.py             # QQ音乐账号管理路由（扫码/Cookie管理）
│   ├── bili_account_api.py           # B站账号管理路由（扫码/SESSDATA管理）
│   ├── kookvoice/                    # 语音推流核心模块
│   │   ├── kookvoice.py              # Player / PlayHandler / 事件系统 / FFmpeg管道
│   │   ├── requestor.py              # KOOK语音API封装（加入/离开/保活）
│   │   └── __init__.py               # 包初始化
│   ├── Cookie/
│   │   ├── cookie.txt                # 网易云Cookie
│   │   ├── qq_cookie.txt             # QQ音乐Cookie
│   │   └── bili_cookie.txt           # B站SESSDATA
│   ├── templates/
│   │   ├── index.html                # 首页
│   │   ├── dashboard.html            # 音乐控制台（平台切换/搜索/播放控制）
│   │   └── account.html              # 账号管理（三平台登录/状态/歌单）
│   ├── static/
│   │   ├── css/style.css             # 全局样式
│   │   └── js/
│   │       ├── main.js               # 首页JS
│   │       ├── dashboard.js          # 控制台交互逻辑（三平台支持）
│   │       └── account.js            # 账号管理交互逻辑
│   ├── cookie_login.py               # 网易云扫码登录脚本
│   ├── cookie_login_captcha.py        # 网易云手机验证码登录脚本
│   ├── save_cookie.py                 # 手动保存Cookie脚本
│   ├── create_env.py                  # .env文件创建脚本
│   ├── tests/test_stability.py         # 播放并发、停止竞态与QQ分页稳定性测试
│   ├── tests/test_watchdog.py          # 看门狗判定、重启预算与路径测试
│   ├── NeteaseCloudMusicApi/          # 本地网易云API（Node.js Express, 端口3000）
│   ├── qq-music-api/                  # 本地QQ音乐API（Koa2 TypeScript, 端口3200）
│   └── ffmpeg/                        # FFmpeg工具（bin/ffmpeg.exe + ffprobe.exe）
├── Ubuntu/                           # Ubuntu平台版本（功能与Windows对等）
│   ├── run.py                        # 应用入口（同Windows结构）
│   ├── app.py                        # Flask应用核心 + 全部KOOK机器人命令
│   ├── config.py                     # 配置文件
│   ├── routes.py                     # Web API路由
│   ├── utils.py                      # 工具函数
│   ├── qq_utils.py                   # QQ音乐工具
│   ├── bili_utils.py                 # B站工具
│   ├── account_api.py                # 网易云账号管理路由
│   ├── qq_account_api.py             # QQ音乐账号管理路由
│   ├── bili_account_api.py           # B站账号管理路由
│   ├── kookvoice/                    # 语音推流核心（同Windows）
│   ├── Cookie/                       # Cookie存储
│   ├── templates/                    # 前端模板（含monitor.html系统监控）
│   │   ├── index.html / dashboard.html / account.html
│   │   ├── monitor.html              # 系统监控面板（Ubuntu独有）
│   │   └── test.html                 # 测试页面
│   ├── static/
│   │   ├── css/style.css
│   │   └── js/ (main.js / dashboard.js / account.js / monitor.js)
│   ├── api.py                        # API Blueprint（统计数据）
│   ├── .env.example / .env.example.bak
│   ├── requirements.txt              # Python依赖（含psutil）
│   └── Ubuntu运行教程.md              # Ubuntu部署教程
├── CLAUDE.md                         # AI辅助开发参考文档
├── DESCRIPTION.md                    # 项目简要描述
├── LICENSE                           # MIT许可证
└── README.md                         # 项目说明（本文件）
```

## 功能特性

### 核心功能
- **三平台音乐支持** — 网易云音乐 / QQ音乐 / B站，统一界面一键切换
- **歌曲搜索与播放** — 支持歌曲名/歌手/BV号搜索，结果一键添加到播放队列
- **歌单导入** — 支持歌单ID或链接输入，自动解析并批量导入（无歌曲数上限）
- **Web控制台** — Bootstrap 5 响应式界面，服务器/频道选择，搜索与播放控制
- **播放控制** — 播放 / 暂停 / 继续 / 跳过 / 停止 / 进度跳转 / 单曲循环 / 随机播放
- **播放列表管理** — 分页查看队列（20首/页）、跳转指定序号、移除歌曲、清空列表
- **多频道独立播放** — 以语音频道为会话单位，同一服务器多频道互不干扰
- **账号管理** — 三平台统一账号页面，二维码扫码登录、Cookie管理、Cookie保活检测、我的歌单展示
- **权限管控** — 服务器/频道/用户三级白名单，CMD指令独立授权

### 全部KOOK机器人命令（23个）

| 分类 | 命令 | 功能 |
|------|------|------|
| **网易云** | `/wy 歌曲名` | 搜索并播放网易云音乐 |
| | `/wygd 歌单ID/链接` | 导入网易云歌单 |
| | `/wy我的歌单` | 列出我的网易云歌单 |
| | `/当前账号` | 查看登录的网易云账号信息 |
| **QQ音乐** | `/qq 歌曲名` | 搜索并播放QQ音乐 |
| | `/qqgd 歌单ID/链接` | 导入QQ音乐歌单 |
| | `/qq我的歌单` | 列出我的QQ音乐歌单 |
| | `/qq当前账号` | 查看登录的QQ音乐账号信息（含Cookie有效期） |
| **B站** | `/bili 关键词 [分P]` | 搜索或BV号直解析播放B站音频 |
| | `/bili歌单 收藏夹ID` | 导入B站收藏夹 |
| | `/bili我的歌单` | 列出我的B站收藏夹 |
| | `/bili当前账号` | 查看登录的B站账号信息 |
| **播放控制** | `/加入` | 加入当前用户所在语音频道 |
| | `/暂停` / `/继续` | 暂停 / 继续播放 |
| | `/跳过` / `/停止` | 跳过当前歌曲 / 停止播放 |
| | `/单曲循环` / `/随机播放` | 切换播放模式 |
| | `/播放第N首` | 切到队列第N首歌 |
| | `/清空列表` | 清空播放队列 |
| | `/脱离卡死` | 分阶段恢复播放会话（取消任务 → KOOK脱离 → 媒体进程终止 → 旧处理器隔离） |
| **查询** | `/播放列表 [页数]` | 分页查看播放队列（20首/页） |
| | `/版本信息` | 查看当前版本与历史版本 |
| | `/帮助` | 显示所有可用指令 |
| **系统** | `/ping` | 测试机器人连接 |
| | `/cmd 命令` | 远程执行CMD命令（CMD_ALLOWUSER管控） |

## 技术栈

| 层级 | 技术 |
|------|------|
| Web框架 | Flask 2.0 |
| 异步处理 | asyncio, threading |
| KOOK SDK | khl.py 0.3.17 |
| 语音推流 | FFmpeg (解码→PCM管道→Opus编码→RTP推流) |
| 前端UI | Bootstrap 5.3, Bootstrap Icons |
| 前端交互 | jQuery 3.6, Chart.js（监控页面） |
| 实时通信 | Socket.IO (flask-socketio 5.1) |
| 音乐数据 | 本地 Node API (NeteaseCloudMusicApi + qq-music-api) + B站公开REST API |
| 系统与进程治理 | psutil（媒体进程身份校验、Windows端口治理与系统监控） |

## 快速开始

### 环境要求
- Python 3.8+
- Node.js 12+（用于本地音乐API：网易云 + QQ音乐）
- FFmpeg（Windows版已内置，Ubuntu需 `apt install ffmpeg`）
- KOOK机器人Token（在[KOOK开发者平台](https://developer.kookapp.cn/)创建应用获取）

### Windows 部署

```bash
# 1. 进入Windows目录
cd windows

# 2. 安装Python依赖
pip install -r requirements.txt

# 3. 安装Node.js依赖（网易云API）
cd NeteaseCloudMusicApi/NeteaseCloudMusicApiBackup-main
npm install
cd ../..

# 4. 安装QQ音乐API依赖
cd qq-music-api
npm install && npm run build
cd ..

# 5. 创建并编辑.env配置文件
python create_env.py
# 编辑.env，填入BOT_TOKEN=你的Token

# 6. 启动应用（自动拉起API → 端口3000/3200，Flask → 端口5000）
python run.py

# 7. 访问控制台: http://localhost:5000
```

### Ubuntu 部署

```bash
# 1. 安装系统依赖
sudo apt update && sudo apt install python3 python3-pip ffmpeg -y

# 2. 进入项目目录
cd Ubuntu

# 3. 创建虚拟环境并安装依赖
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. 配置环境变量
python3 create_env.py
# 编辑.env文件，填入BOT_TOKEN

# 5. 启动应用
python run.py

# 6. 访问控制台: http://localhost:5000
#    系统监控: http://localhost:5000/monitor
```

### 配置Cookie（可选，推荐）

```bash
# 网易云：扫码登录（生成本地二维码图片）
python cookie_login.py

# 网易云：手机验证码登录
python cookie_login_captcha.py

# 手动粘贴Cookie
python save_cookie.py "你的Cookie字符串"

# QQ音乐 / B站：通过Web控制台 /account 页面扫码登录更方便
```

## 配置说明

### 环境变量 / .env

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `BOT_TOKEN` | KOOK机器人Token（必需） | — |
| `FFMPEG_PATH` | FFmpeg可执行文件路径 | Windows: `ffmpeg/bin/ffmpeg.exe`<br>Ubuntu: `/usr/bin/ffmpeg` |
| `FFPROBE_PATH` | FFprobe可执行文件路径（可选） | 空（使用备用时长检测） |
| `MUSIC_API_BASE` | 网易云音乐API地址 | `http://localhost:3000` |
| `QQ_MUSIC_API_BASE` | QQ音乐API地址 | `http://localhost:3200` |
| `QQ_COOKIE_PATH` | QQ音乐Cookie文件路径 | `Cookie/qq_cookie.txt` |
| `BILI_COOKIE_PATH` | B站Cookie文件路径 | `Cookie/bili_cookie.txt` |
| `BACKUP_MUSIC_API` | 网易云备用API | `https://api.music.liuzhijin.cn` |
| `SECRET_KEY` | Flask session密钥 | `change_this_to_a_random_string` |
| `HOST` / `PORT` | Flask监听地址/端口 | `0.0.0.0` / `5000` |
| `DEBUG` | 调试模式 | `False` |
| `ALLOWGROUP` | 服务器ID白名单（逗号分隔） | 空（不限制） |
| `ALLOWCHANNEL` | 频道ID白名单（逗号分隔） | 空（不限制） |
| `ALLOWUSER` | 用户ID白名单（逗号分隔） | 空（不限制） |
| `CMD_ALLOWUSER` | CMD指令用户白名单 | 空（全员无权限） |
| `WATCHDOG_STARTUP_GRACE` | 启动宽限秒数 | `180` |
| `WATCHDOG_LOOP_TIMEOUT` / `WATCHDOG_GATEWAY_TIMEOUT` | Bot事件循环 / KOOK网关超时秒数 | `90` / `90` |
| `WATCHDOG_INTERVAL` / `WATCHDOG_FAILURES` | 检查间隔 / 连续故障阈值 | `15` / `3` |
| `WATCHDOG_REPAIR_COOLDOWN` | 外部API单独恢复冷却秒数 | `60` |
| `WATCHDOG_RESTART_WINDOW` / `WATCHDOG_MAX_RESTARTS` | 完整重启预算时间窗 / 次数 | `900` / `3` |

Windows 版中，`.env` 固定从 `windows/.env` 加载；`FFMPEG_PATH`、`FFPROBE_PATH`、`QQ_COOKIE_PATH`、`BILI_COOKIE_PATH` 的相对路径均以 `windows` 目录为基准，不受启动快捷方式或看门狗重启时的当前目录影响。

### 权限白名单

| 配置场景 | ALLOWGROUP | ALLOWCHANNEL | ALLOWUSER | 效果 |
|----------|:---------:|:-----------:|:--------:|------|
| 全开放（默认） | 空 | 空 | 空 | 所有用户/频道/服务器均可使用 |
| 按服务器限制 | `g1,g2` | 空 | 空 | 仅服务器 g1、g2 可用 |
| 按频道限制 | 空 | `c1,c2` | 空 | 仅频道 c1、c2 可用 |
| 按用户限制 | 空 | 空 | `u1,u2` | 仅用户 u1、u2 可用 |
| 三者全设 | `g1` | `c1` | `u1` | u1 在 g1 的 c1 内才可用 |

- 多个白名单非空时取**交集**（必须同时满足）
- 被拒绝的指令静默忽略，不回复提示
- `/cmd` 独立通过 `CMD_ALLOWUSER` 管控，留空则全员无权限

### 机器人权限要求

在KOOK开发者平台配置机器人时需开启：发送消息 / 管理频道 / 连接语音频道 / 发送语音消息

## Web API接口

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/guilds` | 获取服务器列表 |
| GET | `/api/channels?guild_id=` | 获取语音频道列表 |
| GET | `/api/channels/active?guild_id=` | 获取活跃频道播放状态 |
| POST | `/api/join` | 加入语音频道 |
| POST | `/api/leave` | 离开语音频道 |
| GET | `/api/search?keyword=&platform=` | 搜索音乐（platform: wy/qq/bili） |
| POST | `/api/play` | 添加歌曲到队列（支持三平台） |
| POST | `/api/playlist` | 导入歌单（支持三平台） |
| POST | `/api/pause` / `/api/resume` / `/api/skip` / `/api/stop` | 播放控制 |
| POST | `/api/seek` | 跳转到指定位置 |
| GET | `/api/playlist/current?guild_id=&channel_id=` | 获取当前播放列表 |
| POST | `/api/remove` / `/api/clear` | 移除歌曲 / 清空列表 |
| GET | `/api/debug` | 调试信息 |
| GET | `/api/system/status` | 系统状态（CPU/内存/磁盘/网络/进程） |
| GET | `/api/logs?type=&lines=` | 获取应用日志 |
| POST | `/api/logs/clear` | 清空日志 |
| POST | `/api/system/cleanup` | 手动清理缓存 |
| GET | `/api/terminal/output` | 终端实时输出 |
| POST | `/api/terminal/command` | 执行安全终端命令 |

### 账号API

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/account/status` | 网易云登录状态 |
| POST | `/api/account/qr/key` / `/api/account/qr/create` / `/api/account/qr/check` | 网易云扫码登录流程 |
| POST | `/api/account/cellphone/login` | 网易云手机验证码登录 |
| POST | `/api/account/cookie` | 手动保存网易云Cookie |
| POST | `/api/account/logout` | 退出网易云登录 |
| GET | `/api/qq/account/status` | QQ音乐登录状态（含Cookie有效期） |
| POST | `/api/qq/account/qr/create` / `/api/qq/account/qr/check` | QQ音乐扫码登录流程 |
| POST | `/api/qq/account/cookie` | 手动保存QQ音乐Cookie |
| POST | `/api/qq/account/logout` | 退出QQ音乐登录 |
| GET | `/api/qq/account/playlists` | QQ音乐我的歌单 |
| GET | `/api/bili/account/status` | B站登录状态 |
| POST | `/api/bili/account/qr/create` / `/api/bili/account/qr/check` | B站扫码登录流程 |
| POST | `/api/bili/account/cookie` | 手动保存B站Cookie (SESSDATA) |
| POST | `/api/bili/account/logout` | 退出B站登录 |
| GET | `/api/bili/account/playlists` | B站收藏夹列表 |

## 核心工作原理

### 音乐播放流程
1. 用户通过Web界面或KOOK命令发起播放请求
2. 对应平台的 `*_utils.py` 调用API搜索歌曲、获取播放URL
3. `kookvoice.Player` 管理播放队列，以语音频道ID为会话键
4. `PlayHandler` 线程负责音频推流——两个FFmpeg进程串联：
   - **解码进程**：下载音频 → 解码为PCM WAV → stdout管道
   - **编码进程**：stdin读取WAV → Opus编码 → RTP推流到KOOK语音服务器
   - B站音频特殊优化：`create_subprocess_exec` 传参（避免URL编码被shell破坏）、384KB chunk、60s超时、API已知时长跳过ffprobe
5. `VoiceRequestor` 通过KOOK REST API管理语音频道连接与45秒保活
6. 播放状态实时更新到Web前端

### 歌单标记模式
歌单导入时不直接获取URL（避免大量API请求），而是生成标记存入队列，在播放时或切换模式时延迟解析：
- 网易云：`PLAYLIST_SONG:<id>:<name>:<artist>`
- QQ音乐：`QQ_PLAYLIST_SONG:<songmid>:<name>:<artist>`
- B站：`BILI_PLAYLIST_SONG:<bvid>:<page>:<name>:<artist>`
- 批量预取前5首URL，其余播放时实时解析

### Cookie机制
- 三平台Cookie分别存储在 `Cookie/cookie.txt`、`qq_cookie.txt`、`bili_cookie.txt`
- 所有API请求自动附带Cookie，提升API稳定性和访问范围
- QQ音乐Cookie含多字段过期检测（2分钟缓存）；B站通过 `/x/web-interface/nav` 验证

### 看门狗自愈
- Bot 事件循环每30秒更新内存心跳，并尽力写入 `.bot_heartbeat`；KOOK WebSocket 数据包（含 Pong）独立更新网关活动，Flask 请求使用 `.web_heartbeat`
- 启动完成后保留180秒宽限；随后同时检查事件循环、KOOK网关、Web、网易云 API 与 QQ API，健康恢复会清零连续故障计数
- 外部 API 连续异常优先单独重启；仍未恢复或 Bot/Web 持续异常时，连续3次检查后执行完整重启
- 完整重启先执行播放会话紧急清理，再回收 Node 进程树；重启命令使用绝对 Python 和 `run.py`，工作目录固定为 `windows`
- 15分钟内最多自动重启3次，延迟依次为0/30/120秒；超过预算后保留进程与日志供人工检查

## Windows版与Ubuntu版差异

| 方面 | Windows | Ubuntu |
|------|---------|--------|
| FFmpeg | 内置 `ffmpeg.exe` | 系统安装 `/usr/bin/ffmpeg` |
| B站支持 | 完整 | 完整（V2.7.2同步） |
| 三平台命令 | 全部23个 | 全部23个 |
| 系统监控页面 | 无 | 有（monitor.html + Chart.js） |
| 终端实时输出 | 无 | 有 |
| 账号管理 | 完整（三平台扫码/Cookie） | 完整（三平台扫码/Cookie） |
| .env配置 | 通过config.py | 通过.env + config.py |
| 虚拟环境 | 无 | 有（venv/） |

## 许可证

项目原有框架及所使用的开源组件归原作者所有。更新后框架及差异代码遵循 [MIT License](LICENSE)，版权归 xrggen 所有。

## 致谢

- [KOOK官方API](https://developer.kookapp.cn/) — 机器人开发平台
- [khl.py](https://github.com/TWT233/khl.py) — KOOK Python SDK
- [NeteaseCloudMusicApi](https://github.com/Binaryify/NeteaseCloudMusicApi) — 网易云音乐API
- [qq-music-api](https://github.com/jsososo/qq-music-api) — QQ音乐API
- [B站开放API](https://api.bilibili.com) — B站视频/音频数据
- [Flask](https://flask.palletsprojects.com/) — Web框架
- [Bootstrap](https://getbootstrap.com/) — 前端UI框架
