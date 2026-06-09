# KOOK音乐机器人 Web控制台 (Windows)

> **当前版本**: V2.7.2 | **发布日期**: 2026-06-09

### 版本历史

| 版本 | 日期 | 类型 | 说明 |
|------|------|------|------|
| **V2.7.2** | 2026-06-09 | 修复 | B站音频解码完整修复：解码器改用 `create_subprocess_exec`（参数列表）消除 Windows cmd.exe 对 URL 中 `%` 编码字符的变量展开破坏；新增 BV 号直解析路径（`/bili BVxxxx` 跳过搜索 API 避免 -412 风控）；新增共享 `requests.Session` 双域名预热获取 `buvid3` 设备 Cookie；解码失败快速跳过不再干等；`/bili当前账号` UID 脱敏 |
| **V2.7.1** | 2026-06-09 | 修复 | B站二维码登录修复：QR API 域名从 `api.bilibili.com` 修正为 `passport.bilibili.com`（generate/poll 端点位于 passport 子域）；服务端本地生成 QR 图片（`qrcode`+`Pillow`）替代第三方 QR API，消除前端对外部服务的依赖；`/帮助` 指令新增 B站 四个指令 |
| **V2.7** | 2026-06-09 | 功能增强 | 新增 B站 (Bilibili) 平台支持：新增 `bili_utils.py`（直接调用B站REST API，零外部依赖）、`/bili` `/bili歌单` `/bili我的歌单` `/bili当前账号` 机器人指令、Web 控制台新增 B站平台切换、账号管理页面新增 B站扫码登录/Cookie管理/收藏夹展示、PlayHandler 新增 `BILI_PLAYLIST_SONG` 标记懒加载解析与队列预填充 |
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
| **V1.3** | 2026-05-16 | 功能增强 | 修复 Node API 端口抢占、启动卡死、asyncio 管道泄漏等问题；新增看门狗自愈机制；新增 `/清空列表` 命令；新增切歌主动通知；重写 `/wygd` 对齐 Web 控制台分页逻辑、支持完整歌单链接、解除50首限制；歌单导入改为批量预取URL（每批5首）；新增 `/播放第N首` 命令 |
| **V1.2** | 2026-05-15 | 初始版本 | 集成本地网易云音乐 API (NeteaseCloudMusicApi)；新增网易云账号管理页面；新增 `/当前账号`、`/播放列表`、`/帮助` 命令；完善全链路终端日志输出 |

---

基于Flask的KOOK音乐机器人Web控制台，通过Web界面控制KOOK音乐机器人播放网易云音乐。

## 项目结构

```
windows/
├── run.py                            # 应用入口（同步拉起本地音乐API + Flask应用）
├── app.py                            # Flask应用核心 + KOOK机器人命令处理
├── api.py                            # API Blueprint（统计信息）
├── config.py                         # 配置文件
├── routes.py                         # API路由注册
├── utils.py                          # 工具函数（音乐搜索/歌单获取/Cookie加载）
├── cookie_login.py                   # 网易云扫码登录脚本
├── cookie_login_captcha.py           # 网易云手机验证码登录脚本
├── save_cookie.py                    # 手动保存Cookie脚本
├── create_env.py                     # .env文件创建脚本
├── kookvoice/                        # 语音推流核心模块
│   ├── kookvoice.py                  # 播放器/播放状态管理/FFmpeg管道
│   ├── requestor.py                  # KOOK语音API封装
│   └── __init__.py
├── NeteaseCloudMusicApi/             # 本地网易云音乐API（Node.js）
│   └── NeteaseCloudMusicApiBackup-main/
│       ├── app.js                    # 入口
│       ├── server.js                 # Express服务（自动加载module/下所有路由）
│       ├── module/                   # API模块（cloudsearch/song_url/playlist_* 等）
│       ├── util/                     # 工具函数
│       └── package.json              # Node.js依赖声明
├── Cookie/                           # 网易云Cookie存储
│   └── cookie.txt                    # Cookie文本格式（自动用于API请求）
├── templates/
│   ├── index.html                    # 首页
│   └── dashboard.html                # 控制台页面
├── static/
│   ├── css/style.css                 # 全局样式
│   └── js/
│       ├── main.js                   # 首页JS
│       └── dashboard.js              # 控制台交互逻辑
├── ffmpeg/                           # FFmpeg二进制文件
├── ffmpeg.exe                        # Windows FFmpeg可执行文件
└── requirements.txt                  # Python依赖
```

## 快速开始

### 1. 安装依赖

```bash
# Python依赖
pip install -r requirements.txt

# Node.js依赖（本地音乐API）
cd NeteaseCloudMusicApi/NeteaseCloudMusicApiBackup-main
npm install
cd ../..

# QQ音乐API依赖
cd qq-music-api
npm install
cd ..
```

### 2. 配置

```bash
# 创建.env文件
python create_env.py

# 编辑.env，填入你的KOOK机器人Token
# BOT_TOKEN=你的Token
```

### 3. 启动

```bash
python run.py
```

启动时会自动：
1. 在后台拉起本地网易云音乐API服务（`localhost:3000`）
2. 初始化并启动Flask应用（`localhost:5000`）
3. 退出时自动停止API服务

### 4. 访问

- 控制台: `http://localhost:5000`
- 本地音乐API: `http://localhost:3000`

### 5. 账号管理

访问 `http://localhost:5000/account` 管理网易云账号：
- **扫码登录** / **手机验证码登录** / **Cookie手动输入**
- 查看账号信息（昵称/等级/VIP/收藏统计/我的歌单）
- 每日签到、退出登录

## 机器人命令

在KOOK频道中发送以下命令控制机器人：

| 命令 | 功能 | 用法 |
|------|------|------|
| `/ping` | 测试连接 | `/ping` |
| `/加入` | 加入你所在的语音频道 | `/加入` |
| `/wy 歌曲名` | 搜索并播放网易云音乐 | `/wy 晴天` |
| `/wygd 歌单ID` | 导入网易云歌单 | `/wygd 123456789` |
| `/qq 歌曲名` | 搜索并播放QQ音乐 | `/qq 晴天` |
| `/qqgd 歌单ID` | 导入QQ音乐歌单（支持 y.qq.com 链接） | `/qqgd 123456789` |
| `/暂停` | 暂停播放 | `/暂停` |
| `/继续` | 继续播放 | `/继续` |
| `/跳过` | 跳过当前歌曲 | `/跳过` |
| `/播放第N首` | 切到队列第N首歌 | `/播放第3首` |
| `/停止` | 停止播放 | `/停止` |
| `/清空列表` | 清空当前播放队列 | `/清空列表` |
| `/当前账号` | 查看当前登录的网易云账号（昵称/UID/VIP） | `/当前账号` |
| `/qq当前账号` | 查看当前登录的QQ音乐账号（QQ号/UIN） | `/qq当前账号` |
| `/bili 关键词` | 搜索并播放B站音频 | `/bili 春日影` |
| `/bili歌单 收藏夹ID` | 导入B站收藏夹 | `/bili歌单 123456789` |
| `/bili我的歌单` | 列出B站收藏夹 | `/bili我的歌单` |
| `/bili当前账号` | 查看当前登录的B站账号 | `/bili当前账号` |
| `/播放列表 [页数]` | 查看当前播放队列（20首/页） | `/播放列表` 或 `/播放列表 2` |
| `/帮助` | 显示所有可用指令及用法 | `/帮助` |

## 配置说明

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `BOT_TOKEN` | KOOK机器人Token | — |
| `MUSIC_API_BASE` | 网易云音乐API地址 | `http://localhost:3000` |
| `QQ_MUSIC_API_BASE` | QQ音乐API地址 | `http://localhost:3200` |
| `BILI_COOKIE_PATH` | B站Cookie存储路径 | `./Cookie/bili_cookie.txt` |
| `FFMPEG_PATH` | FFmpeg路径 | `./ffmpeg/bin/ffmpeg.exe` |
| `FFPROBE_PATH` | FFprobe路径 | `./ffmpeg/bin/ffprobe.exe` |
| `SECRET_KEY` | Flask密钥 | 随机字符串（必改） |
| `HOST` | 监听地址 | `0.0.0.0` |
| `PORT` | 监听端口 | `5000` |
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

## 架构说明

### 音乐播放流程
1. 用户通过Web界面或KOOK命令发起播放请求
2. Flask路由调用 `utils.py` 搜索/获取音乐URL
3. `utils.py` 通过本地 `http://localhost:3000` 调用网易云API
4. `kookvoice.Player` 管理播放队列，每个服务器独立维护状态
5. `PlayHandler` 线程通过 FFmpeg 双进程管道实现推流：
   - 解码进程：下载音频 → 解码为 WAV
   - 编码进程：WAV → Opus → RTP 推流到 KOOK 语音服务器

### 本地API自动管理
- `run.py` 启动时自动拉起两个本地API：
  - `NeteaseCloudMusicApi` (Node.js Express, 端口3000) — 网易云音乐
  - `qq-music-api` (Koa2 TypeScript, 端口3200) — QQ音乐
- 进程退出(Ctrl+C / 进程终止)时自动停止所有API服务
- 使用 `atexit` + `signal` 双重保障清理

## 许可证

项目原有框架及所使用的开源组件归原作者所有。更新后框架及差异代码遵循 [MIT License](LICENSE)，版权归 xrggen 所有。
