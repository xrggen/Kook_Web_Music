# Repository Guide

## Project

KOOK Web Music is a self-hosted Flask and KOOK Bot application for NetEase Cloud Music, QQ Music, and Bilibili. Audio is decoded and encoded with FFmpeg, then streamed to KOOK voice channels over RTP.

The repository has two deployable platform directories:

- `windows/`: Windows runtime, including bundled FFmpeg.
- `Ubuntu/`: Ubuntu runtime, using system FFmpeg and an optional monitor page.

Shared Python, templates, static assets, configuration templates, and tests must remain synchronized.

## Runtime

`run.py` is the only application entry point. It loads the platform `.env`, resolves system Node.js 20+ and npm outside the repository, locates global npm packages through `npm root --global`, starts the two local music APIs, then starts Flask, the KOOK Bot, health tracking, and the watchdog.

Required global packages:

```bash
npm install --global NeteaseCloudMusicApi@4.25.0 @sansenjian/qq-music-api@2.3.1
```

Do not add a repository-local Node runtime, API source copy, package manager cache, or `node_modules`. Account cookies belong only in the platform `Cookie/` directory.

## Architecture

Core modules:

- `app.py`: Flask app, KOOK Bot commands, Bot event loop.
- `routes.py`: pages, channel/playback APIs, status, logs, and operations.
- `account_api.py`, `qq_account_api.py`, `bili_account_api.py`: account routes.
- `utils.py`, `qq_utils.py`, `bili_utils.py`: platform adapters.
- `qq_credential.py`: QQ credential migration and refresh.
- `kookvoice/`: channel sessions, playback threads, FFmpeg, RTP.
- `runtime_health.py` and `service_watchdog.py`: health and recovery.

Playback sessions are keyed by `channel_id`. Shared state changes require `kookvoice.state_lock` and handler ownership checks. Network and media I/O must run outside the lock.

Playlist URLs are resolved lazily from `PLAYLIST_SONG`, `QQ_PLAYLIST_SONG`, and `BILI_PLAYLIST_SONG` markers. Media subprocesses use argument arrays, never shell-interpreted URLs.

## Platform parity

Run:

```bash
python scripts/check_platform_sync.py
```

When changing a shared file, update both platform copies in the same task. Keep OS differences in path/media resolution, deployment files, or explicit platform branches.

## Security

- Never read, print, or commit real `.env`, Cookie, token, credential, or signed media URL values.
- Remote shell execution and the KOOK `/cmd` command are intentionally removed.
- Keep ports 18474/18475 bound to localhost; do not expose the Web port 18473 without an authenticated TLS proxy.
- Validate process ownership before stopping port occupants.

Run `python scripts/check_secrets.py` before publishing.

## Documentation

The root README is the user entry point. `docs/architecture.md` and `docs/deployment.md` are the canonical architecture and deployment references. Platform guides contain only platform-specific steps. Documentation describes current behavior and does not maintain a duplicated changelog.
