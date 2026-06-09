# KOOK音乐机器人 Web控制台

> **当前版本**: V2.7.2 | **发布日期**: 2026-06-09

### 版本历史

| 版本 | 日期 | 类型 | 说明 |
|------|------|------|------|
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

---

一个功能完整的KOOK音乐机器人Web控制台，支持网易云音乐搜索与播放、歌单导入、远程控制、系统监控等功能。通过现代化Web界面管理KOOK服务器中的音乐播放，无需在聊天框输入命令。

## 项目架构

```
Kook_Web_Music/
├── ffmpeg.exe                        # Windows版FFmpeg可执行文件
├── windows/                          # Windows平台版本
│   ├── run.py                        # 应用入口
│   ├── app.py                        # Flask应用核心，包含KOOK机器人命令与Web路由
│   ├── config.py                     # 配置文件（Token、FFmpeg路径、API地址等）
│   ├── routes.py                     # API路由注册（服务器/频道管理、播放控制、播放列表CRUD）
│   ├── utils.py                      # 工具函数（网易云音乐搜索、URL获取、歌单获取、Cookie加载）
│   ├── qq_utils.py                   # QQ音乐工具函数（搜索、URL获取、歌单获取、Cookie加载）
│   ├── qq_account_api.py             # QQ音乐账号管理API路由
│   ├── kookvoice/                    # 语音推流核心模块
│   │   ├── kookvoice.py              # 播放器、播放状态管理、FFmpeg推流管道
│   │   ├── requestor.py              # KOOK语音API请求封装（加入/离开/保活）
│   │   └── __init__.py               # 包初始化
│   ├── Cookie/
│   │   └── cookie.txt                # 网易云Cookie（用于绕过VIP限制）
│   ├── templates/
│   │   ├── index.html                # 首页
│   │   └── dashboard.html            # 音乐控制台（服务器选择、搜索、播放控制）
│   ├── static/
│   │   ├── css/style.css             # 全局样式
│   │   └── js/
│   │       ├── main.js               # 首页JS
│   │       └── dashboard.js          # 控制台交互逻辑
│   ├── cookie_login.py               # 网易云扫码登录脚本
│   ├── cookie_login_captcha.py        # 网易云手机验证码登录脚本
│   ├── save_cookie.py                 # 手动保存Cookie脚本
│   ├── create_env.py                  # .env文件创建脚本
│   ├── NeteaseCloudMusicApi/          # 本地网易云音乐API（Node.js, 端口3000）
│   │   └── NeteaseCloudMusicApiBackup-main/
│   │       ├── app.js                 # 入口，启动Express服务
│   │       ├── server.js              # 自动注册module/下所有模块为路由
│   │       ├── module/                # API模块（cloudsearch/song_url/playlist_detail等）
│   │       └── util/                  # 请求封装与工具函数
│   ├── qq-music-api/                  # 本地QQ音乐API（Koa2 TypeScript, 端口3200）
│   │   ├── app.ts                     # 入口，启动Koa服务
│   │   ├── koaApp.ts                  # Koa实例 + 中间件
│   │   ├── routers/                   # API路由（59个端点）
│   │   ├── module/                    # API模块（search/song_url/playlist_detail等）
│   │   └── config/                    # 配置文件（user-info.json存Cookie）
│   └── ffmpeg/                        # FFmpeg工具
├── Ubuntu/                           # Ubuntu平台版本（功能更完整）
│   ├── run.py                        # 应用入口
│   ├── app.py                        # Flask应用核心（同Windows结构）
│   ├── api.py                        # API Blueprint（统计数据接口）
│   ├── config.py                     # 配置文件
│   ├── routes.py                     # API路由注册（额外包含系统监控、日志、终端路由）
│   ├── utils.py                      # 工具函数
│   ├── create_env.py                 # .env文件快速创建脚本
│   ├── save_cookie.py                # 手动保存Cookie工具（命令行粘贴）
│   ├── cookie_login.py               # 网易云扫码登录获取Cookie
│   ├── cookie_login_captcha.py       # 网易云手机验证码登录获取Cookie
│   ├── kookvoice/                    # 语音推流核心模块（同Windows）
│   ├── Cookie/
│   │   ├── cookie.txt                # 网易云Cookie文本格式
│   │   ├── cookies.json              # 网易云Cookie JSON格式
│   │   └── README.md                 # Cookie目录说明
│   ├── templates/
│   │   ├── index.html                # 首页（增加了系统监控入口）
│   │   ├── dashboard.html            # 音乐控制台（增加了系统监控快捷按钮）
│   │   ├── monitor.html              # 系统监控页面（CPU/内存/磁盘/网络图表、终端输出）
│   │   └── test.html                 # 测试页面
│   ├── static/
│   │   ├── css/style.css             # 全局样式
│   │   └── js/
│   │       ├── main.js               # 首页JS
│   │       ├── dashboard.js          # 控制台交互逻辑
│   │       └── monitor.js            # 监控页面逻辑（Chart.js图表、终端实时输出）
│   ├── .env.example                  # 环境变量模板
│   ├── requirements.txt              # Python依赖清单
│   ├── Ubuntu运行教程.md              # Ubuntu部署详细教程
│   └── venv/                         # Python虚拟环境（Python 3.11）
├── DESCRIPTION.md                    # 项目简要描述
├── LICENSE                           # MIT许可证
└── README.md                         # 项目说明（本文件）
```

## 功能特性

### 核心功能
- **网易云音乐搜索与播放** — 支持歌曲名/歌手搜索，返回结果一键添加到播放队列
- **歌单导入** — 支持网易云歌单ID或链接输入，自动解析并批量导入歌曲（最多50首）
- **Web控制台** — Bootstrap 5响应式界面，左侧服务器/频道选择，右侧搜索与播放控制
- **播放控制** — 播放、暂停、继续、跳过、停止、进度跳转
- **播放列表管理** — 查看当前队列、移除指定歌曲、清空列表
- **多服务器支持** — 机器人可同时在多个KOOK服务器中运行

### KOOK机器人命令
| 命令 | 功能 | 用法示例 |
|------|------|----------|
| `/ping` | 测试机器人连接 | `/ping` |
| `/加入` | 加入当前用户所在语音频道 | `/加入` |
| `/wy 歌曲名` | 搜索并播放网易云音乐 | `/wy 晴天` |
| `/wygd 歌单ID` | 导入并播放网易云歌单 | `/wygd 123456789` |
| `/qq 歌曲名` | 搜索并播放QQ音乐 | `/qq 晴天` |
| `/qqgd 歌单ID` | 导入并播放QQ音乐歌单 | `/qqgd 123456789` |
| `/暂停` | 暂停当前播放 | `/暂停` |
| `/继续` | 继续播放 | `/继续` |
| `/跳过` | 跳过当前歌曲 | `/跳过` |
| `/播放第N首` | 切到队列第N首歌 | `/播放第3首` |
| `/停止` | 停止播放 | `/停止` |
| `/清空列表` | 清空当前播放队列 | `/清空列表` |
| `/当前账号` | 查看当前登录的网易云账号信息（昵称/UID/VIP） | `/当前账号` |
| `/qq当前账号` | 查看当前登录的QQ音乐账号信息（QQ号/UIN） | `/qq当前账号` |
| `/播放列表 [页数]` | 查看当前服务器播放队列（20首/页） | `/播放列表` 或 `/播放列表 2` |
| `/帮助` | 显示所有可用指令及用法 | `/帮助` |

### Ubuntu版额外功能
- **系统监控面板** (`/monitor`) — CPU/内存/磁盘/网络使用率实时图表（Chart.js）、进程信息、音频缓存状态
- **终端实时输出** — Web端实时显示服务器日志输出，支持增量拉取
- **缓存管理** — 手动清理音频缓存、调整缓存清理阈值
- **日志查看** — Web端查看应用日志、支持清空操作
- **网易云Cookie登录** — 支持扫码登录和手机验证码登录，保存Cookie以提升音乐API稳定性

## 技术栈

| 层级 | 技术 |
|------|------|
| Web框架 | Flask 2.0 |
| 异步处理 | asyncio, threading |
| KOOK SDK | khl.py 0.3.17 |
| 语音推流 | FFmpeg (Opus编码 → RTP推流) |
| 前端UI | Bootstrap 5.3, Bootstrap Icons |
| 前端交互 | jQuery 3.6, Chart.js（监控页面） |
| 实时通信 | Socket.IO (flask-socketio 5.1) |
| 音乐数据 | 第三方网易云音乐API |
| 系统监控 | psutil（Ubuntu版） |

## 快速开始

### 环境要求
- Python 3.8+
- Node.js 12+（用于本地音乐API）
- FFmpeg（Windows版已内置 `ffmpeg.exe`，Ubuntu需通过 `apt install ffmpeg` 安装）
- KOOK机器人Token（在[KOOK开发者平台](https://developer.kookapp.cn/)创建应用获取）

### Windows 部署

```bash
# 1. 进入Windows目录
cd windows

# 2. 安装Python依赖
pip install -r requirements.txt

# 3. 安装Node.js依赖（本地音乐API）
cd NeteaseCloudMusicApi/NeteaseCloudMusicApiBackup-main
npm install
cd ../..

# 3b. 安装QQ音乐API依赖
cd qq-music-api
npm install
cd ..

# 4. 创建.env配置文件
python create_env.py

# 5. 编辑.env，填入KOOK机器人Token
# BOT_TOKEN=你的Token

# 6. 启动应用（自动拉起本地音乐API → 端口3000，Flask应用 → 端口5000）
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

### 使用Cookie（可选，推荐）

为提升网易云音乐API的稳定性和访问范围，建议配置网易云Cookie：

```bash
cd Ubuntu

# 方法一：扫码登录（会生成本地二维码图片或链接）
python cookie_login.py

# 方法二：手机验证码登录
python cookie_login_captcha.py

# 方法三：手动粘贴Cookie字符串
python save_cookie.py "你的Cookie字符串"
```

## 配置说明

### 环境变量 / config.py

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `BOT_TOKEN` | KOOK机器人Token（必需） | — |
| `FFMPEG_PATH` | FFmpeg可执行文件路径 | Windows: `./ffmpeg/bin/ffmpeg.exe`<br>Ubuntu: `/usr/bin/ffmpeg` |
| `FFPROBE_PATH` | FFprobe可执行文件路径 | Windows: `./ffmpeg/bin/ffprobe.exe`<br>Ubuntu: `/usr/bin/ffprobe` |
| `MUSIC_API_BASE` | 网易云音乐API地址 | `http://localhost:3000` |
| `QQ_MUSIC_API_BASE` | QQ音乐API地址 | `http://localhost:3200` |
| `BACKUP_MUSIC_API` | 备用音乐API地址 | 空（可选） |
| `SECRET_KEY` | Flask session密钥 | 随机字符串（必改） |
| `HOST` | Flask监听地址 | `0.0.0.0` |
| `PORT` | Flask监听端口 | `5000` |
| `DEBUG` | 调试模式开关 | `False` (Windows) / `True` (Ubuntu dev) |
| `ALLOWGROUP` | 服务器ID白名单（逗号分隔） | 空（不限制） |
| `ALLOWCHANNEL` | 频道ID白名单（逗号分隔） | 空（不限制） |
| `ALLOWUSER` | 用户ID白名单（逗号分隔） | 空（不限制） |

### 权限白名单

支持通过 `.env` 中的三个参数限制机器人指令的响应范围，全部留空时不启用权限过滤（默认行为，向后兼容）。

| 配置场景 | ALLOWGROUP | ALLOWCHANNEL | ALLOWUSER | 效果 |
|----------|:---------:|:-----------:|:--------:|------|
| 全开放（默认） | 空 | 空 | 空 | 所有用户/频道/服务器均可使用 |
| 按服务器限制 | `g1,g2` | 空 | 空 | 仅服务器 g1、g2 内的所有频道和用户可用 |
| 按频道限制 | 空 | `c1,c2` | 空 | 仅频道 c1、c2 内的所有用户可用 |
| 按用户限制 | 空 | 空 | `u1,u2` | 仅用户 u1、u2 可用（任意频道/服务器） |
| 服务器+用户 | `g1` | 空 | `u1` | 用户 u1 在服务器 g1 内才可用 |
| 三者全设 | `g1` | `c1` | `u1` | 仅用户 u1 在服务器 g1 的频道 c1 内才可用 |

- 多个白名单非空时取**交集**（必须同时满足）
- 用户为最小控制单元：ALLOWUSER 优先级最高
- 被拒绝的指令静默忽略，不回复提示

### 机器人权限要求

在KOOK开发者平台配置机器人时，确保开启以下权限：
- 发送消息
- 管理频道
- 连接语音频道
- 发送语音消息

## API接口

Web控制台通过RESTful API与后端通信：

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/guilds` | 获取机器人可访问的服务器列表 |
| GET | `/api/channels?guild_id=` | 获取指定服务器的语音频道列表 |
| POST | `/api/join` | 机器人加入指定语音频道 |
| POST | `/api/leave` | 机器人离开当前语音频道 |
| GET | `/api/search?keyword=` | 搜索网易云音乐 |
| POST | `/api/play` | 添加歌曲到播放队列 |
| POST | `/api/playlist` | 导入网易云歌单 |
| POST | `/api/pause` | 暂停播放 |
| POST | `/api/resume` | 继续播放 |
| POST | `/api/skip` | 跳过当前歌曲 |
| POST | `/api/stop` | 停止播放 |
| POST | `/api/seek` | 跳转到指定播放位置 |
| GET | `/api/playlist/current?guild_id=` | 获取当前播放列表 |
| POST | `/api/remove` | 从播放列表移除指定歌曲 |
| POST | `/api/clear` | 清空播放列表 |
| GET | `/api/debug` | 调试信息（Windows版） |
| GET | `/api/system/status` | 系统状态信息（Ubuntu版） |
| GET | `/api/logs` | 获取应用日志（Ubuntu版） |
| POST | `/api/logs/clear` | 清空日志（Ubuntu版） |
| POST | `/api/system/cleanup` | 手动清理缓存（Ubuntu版） |
| GET | `/api/terminal/output` | 终端实时输出（Ubuntu版） |

## 核心工作原理

### 音乐播放流程
1. 用户通过Web界面或KOOK命令发起播放请求
2. `utils.py` 调用本地 Node.js API（`http://localhost:3000`）搜索歌曲、获取播放URL
3. `kookvoice.Player` 管理播放队列，每个服务器维护独立的播放状态
4. `PlayHandler` 线程负责实际的音频推流——启动两个FFmpeg进程：
   - **解码进程**：下载音频 → 解码为WAV → 输出到stdout
   - **编码进程**：读取stdin的WAV → 编码为Opus → 通过RTP推流到KOOK语音服务器
5. `VoiceRequestor` 通过KOOK API管理语音频道连接与保活
6. 播放状态实时更新到Web前端

### 本地API进程管理
- `run.py` 启动时自动拉起 `NeteaseCloudMusicApi`（Node.js Express, 端口3000）
- 通过 `atexit` 和 `signal` 双重机制确保进程退出时自动终止API服务
- 若API目录不存在则跳过启动，使用 `.env` 中配置的 `MUSIC_API_BASE`

### Cookie机制
- Cookie存储在 `Cookie/cookie.txt`，被 `utils.load_cookie_header()` 加载
- 所有音乐API请求自动附带Cookie头，用于绕过网易云的访客限制
- 通过 `cookie_login.py`（扫码）或 `cookie_login_captcha.py`（验证码）自动获取

## Windows版与Ubuntu版差异

| 方面 | Windows | Ubuntu |
|------|---------|--------|
| FFmpeg | 内置 `ffmpeg.exe` | 系统安装 `/usr/bin/ffmpeg` |
| 系统监控 | 无 | 有（monitor页面，psutil） |
| 日志Web查看 | 无 | 有 |
| 终端实时输出 | 无 | 有 |
| Cookie登录工具 | 无 | 有（3个脚本） |
| API Blueprint | 无 | 有（api.py） |
| 缓存管理界面 | 无 | 有 |
| .env支持 | 通过config.py | 通过.env + config.py |
| 虚拟环境 | 无 | 有（venv/） |

## 许可证

项目原有框架及所使用的开源组件归原作者所有。更新后框架及差异代码遵循 [MIT License](LICENSE)，版权归 xrggen 所有。

## 致谢

- [KOOK官方API](https://developer.kookapp.cn/) — 机器人开发平台
- [khl.py](https://github.com/TWT233/khl.py) — KOOK Python SDK
- [NeteaseCloudMusicApi](https://github.com/Binaryify/NeteaseCloudMusicApi) — 网易云音乐API
- [Flask](https://flask.palletsprojects.com/) — Web框架
- [Bootstrap](https://getbootstrap.com/) — 前端UI框架
