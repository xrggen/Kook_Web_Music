# CLAUDE.md — KOOK Web Music Bot

## Project Overview

A multi-platform music bot for KOOK (开黑啦) with a Flask web console. Integrates three music platforms — **NetEase Cloud Music (网易云)**, **QQ Music**, and **Bilibili (B站)** — and streams audio to KOOK voice channels via FFmpeg/RTP.

**Current version**: V2.7.3 (2026-06-17)

## Architecture

```
Kook_Web_Music/
├── windows/                   # Windows platform (primary dev target)
│   ├── run.py                 # Entry point — starts API services + Flask app
│   ├── app.py                 # Flask app core + KOOK bot commands (1300+ lines)
│   ├── config.py              # All config: BOT_TOKEN, FFmpeg paths, API URLs, ACL
│   ├── routes.py              # Flask route registration (guilds, channels, playback)
│   ├── utils.py               # NetEase: search, get_url, playlist (marker pattern)
│   ├── qq_utils.py            # QQ Music: search, get_url, playlist, cookie
│   ├── bili_utils.py          # Bilibili: search, BVid, DASH audio, favorites
│   ├── account_api.py         # NetEase account routes (QR login, phone auth)
│   ├── qq_account_api.py      # QQ Music account routes (QR login, cookie mgmt)
│   ├── bili_account_api.py    # Bilibili account routes (QR login, SESSDATA)
│   ├── cookie_login.py        # Standalone NetEase QR login script
│   ├── kookvoice/             # Voice streaming core
│   │   ├── __init__.py         # Package re-exports
│   │   ├── kookvoice.py       # Player, PlayHandler (FFmpeg pipeline), Status enum
│   │   └── requestor.py       # KOOK voice API (join/leave/keep-alive) via aiohttp
│   ├── NeteaseCloudMusicApi/  # Local Node.js Express API (port 3000)
│   ├── qq-music-api/          # Local Node.js Koa2 TypeScript API (port 3200)
│   ├── ffmpeg/                # Bundled FFmpeg binaries (bin/ffmpeg.exe)
│   ├── Cookie/                # Cookie storage (.txt files per platform)
│   ├── templates/             # Jinja2: index.html, dashboard.html, account.html
│   └── static/                # css/style.css, js/main.js, js/dashboard.js
└── Ubuntu/                    # Ubuntu platform (similar structure, extra monitor page)
```

## Key Technical Details

### Playback Pipeline
1. User invokes `/wy` / `/qq` / `/bili` → search via platform API
2. URL obtained → `Player.add_music(url, extra)` → appended to `play_list[channel_id]`
3. `PlayHandler` (per-channel thread) runs `push()` coroutine:
   - **Decoder**: `ffmpeg -reconnect ... -i <url> -acodec pcm_s16le -f wav -` → stdout pipe
   - **Encoder**: `ffmpeg -f wav -i - -acodec libopus -f tee [f=rtp:...]rtp://ip:port` → stdin pipe
   - Audio data read from decoder stdout in 96KB (normal) or 384KB (B站) chunks → written to encoder stdin
4. Voice channel session maintained via KOOK REST API (`voice/join`, `voice/keep-alive` every 45s)

### Playlist Marker Pattern
Songs from playlists are stored as markers and lazily resolved to real URLs:
- **NetEase**: `PLAYLIST_SONG:<id>:<name>:<artist>` → resolved via `resolve_marker_batch()`
- **QQ Music**: `QQ_PLAYLIST_SONG:<songmid>:<name>:<artist>` → `resolve_qq_marker_batch()`
- **Bilibili**: `BILI_PLAYLIST_SONG:<bvid>:<page>:<name>:<artist>` → `resolve_bili_marker_batch()`

Batch resolution (5 at a time) via `refill_*_playlist_queue()` is called on song end and on shuffle toggle.

### Session Key Architecture (V2.2+)
The session key in `play_list` / `guild_status` is `channel_id` (voice channel ID), enabling per-channel independent playback. Earlier versions used `guild_id`, which limited to one session per server.

### Bot Commands (22 total)
| Category | Commands |
|----------|----------|
| NetEase | `/wy`, `/wygd`, `/wy我的歌单`, `/当前账号` |
| QQ Music | `/qq`, `/qqgd`, `/qq我的歌单`, `/qq当前账号` |
| Bilibili | `/bili`, `/bili歌单`, `/bili我的歌单`, `/bili当前账号` |
| Control | `/加入`, `/暂停`, `/继续`, `/跳过`, `/停止`, `/单曲循环`, `/随机播放` |
| Queue | `/播放列表 [页]`, `/播放第N首`, `/清空列表` |
| System | `/脱离卡死`, `/版本信息`, `/帮助`, `/ping`, `/cmd` |

### ACK (Permission) System
Three-tier whitelist via `.env` — all empty = allow everyone; if multiple set, intersection applies:
- `ALLOWGROUP` — comma-separated guild IDs
- `ALLOWCHANNEL` — comma-separated channel IDs
- `ALLOWUSER` — comma-separated user IDs
- `CMD_ALLOWUSER` — `/cmd` command whitelist (empty = no one)

### Watchdog / Self-Healing
- Heartbeat written to `.heartbeat` every 30s by bot event loop + every HTTP request
- Watchdog thread monitors heartbeat; 3 consecutive misses (~135s) triggers alert
- If Flask is alive but bot thread stuck → log warning; if both dead → `os._exit(1)`

### Chinese Quote Normalization
`DefaultLexer.lex` is patched to normalize Chinese quotes (`""`, `''`, `「」`, `『』`) to ASCII before `shlex.split()`, with fallback to `str.split()` on `ValueError`.

### QQ Music Playlist Fetch (V2.7.3)
QQ Music playlist API uses `u6.y.qq.com/cgi-bin/musics.fcg` with a custom MD5-based signature algorithm (ported from GoMusic project). Key details:
- `_qqmusic_sign()` computes the `sign` query parameter from the request body
- Module/method: `music.srfDissInfo.aiDissInfo` / `uniform_get_Dissinfo`
- `g_tk=5381`, `uin=0` (anonymous, no cookie needed)
- Tries multiple `platform` values (`-1`, `android`, `iphone`, `h5`, etc.)
- Pagination: 30 songs per page, loops until all fetched
- Error detection: 108-byte response = invalid, try next platform

### Bilibili-Specific Optimizations
- **Session pre-warming**: Shared `requests.Session` visits bilibili.com + API nav to acquire `buvid3` device cookie (avoids -412 anti-crawl)
- **BVid direct parse**: `/bili BVxxxx [page]` skips search API entirely
- **`create_subprocess_exec`** (not shell) for FFmpeg decode to prevent `%` in URLs being mangled by `cmd.exe`
- **Chunk size 384KB** (4× normal) + **60s timeout** (2× normal) for DASH streams
- **API-provided duration** skips ffprobe (B站 .m4s has no duration header)

## Environment Variables (.env)
- `BOT_TOKEN` — KOOK bot token
- `FFMPEG_PATH` / `FFPROBE_PATH` — paths to FFmpeg/FFprobe binaries
- `MUSIC_API_BASE` — NetEase API (default `http://localhost:3000`)
- `QQ_MUSIC_API_BASE` — QQ Music API (default `http://localhost:3200`)
- `ALLOWGROUP` / `ALLOWCHANNEL` / `ALLOWUSER` / `CMD_ALLOWUSER` — ACL
- `SECRET_KEY` — Flask session secret
- `HOST` / `PORT` / `DEBUG` — Flask server config

## Dependencies
- **Python**: flask, flask-socketio, python-dotenv, requests, khl.py (KOOK SDK), qrcode, Pillow, psutil
- **Node.js**: NeteaseCloudMusicApi (Express, port 3000), qq-music-api (Koa2/TypeScript, port 3200)
- **External**: FFmpeg (bundled in `windows/ffmpeg/`)

## Development Notes
- Both `windows/` and `Ubuntu/` are platform variants with identical core logic (synced V2.7.3, 2026-06-17)
- `windows/` is the primary dev target; changes should be mirrored to `Ubuntu/` after validation
- `run.py` auto-starts Node.js APIs as subprocesses, kills port 3000/3200 before launch
- Cookie files are stored as plain text in `Cookie/` directory
- Bot commands support both direct URLs and search keywords
- The patched `_patched_handle` wraps `bot.command.handle` for ACL — NOT `bot.command` itself (fixed in V2.1.1)
- `set_loop(loop)` bridges the bot's event loop for cross-thread event dispatch (song start notifications)
