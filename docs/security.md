# 安全边界

## 默认威胁模型

项目现在具备本地账号、SQLite Session、Role/Scope、CSRF 和登录失败限速，因此 Web 控制面不再是“任何能访问端口的人都天然获得全部权限”。

但它仍然是单实例自托管控制服务，而不是面向不受信任多租户的 SaaS。控制台可以控制 KOOK 语音频道、修改队列、管理音乐账号、读取/清空日志、执行进程清理，并仍保留 Web shell 命令入口。因此生产部署必须同时依赖应用鉴权、最小网络暴露、TLS、主机权限和秘密管理。

鉴权实现详见 [authentication.md](authentication.md)。

## 网络暴露

推荐生产配置：

```env
HOST=127.0.0.1
AUTH_COOKIE_SECURE=true
DEBUG=False
```

由受信任的 HTTPS 反向代理暴露 Web。网易云 3000 与 QQ 3200 只允许本机 Python 应用访问，不应映射公网。

不要把 Flask 开发服务器、3000、3200 直接暴露到互联网。若需要跨公网访问，应同时使用：

- HTTPS；
- 应用内账号鉴权；
- 主机防火墙；
- 最小暴露端口；
- 可选 VPN / 零信任接入层。

如果启用：

```env
AUTH_TRUST_PROXY_HEADERS=true
```

前置代理必须覆盖并清洗客户端传入的 `X-Forwarded-For`。否则攻击者可伪造来源 IP，影响登录限速和审计记录。

## Web 身份安全

当前控制面使用：

- PBKDF2-HMAC-SHA256 密码 Hash；
- 服务端 Session；
- Session Token / CSRF Token 数据库 Hash；
- `HttpOnly` Session Cookie；
- `SameSite=Lax`；
- 写请求 CSRF；
- Role + playback Scope；
- 登录失败限速；
- `auth_version` 驱动的 Session 失效；
- 首次登录强制改密。

Bootstrap 管理员用户名为 `gen`，初始明文密码不进入 Git。不要把初始密码写入文档、Issue、日志、截图或部署脚本。

建议首次部署后：

1. 立即完成 `gen` 强制改密；
2. 创建第二个管理员作为恢复路径；
3. 普通用户只给必要 Guild/Channel Scope；
4. 禁用不再使用的账号；
5. 定期检查 `audit_logs`。

## 凭据与运行数据

敏感文件包括：

```text
.env
Cookie/cookie.txt
Cookie/qq_cookie.txt
Cookie/qq_credential.json
Cookie/bili_cookie.txt
data/kook_music.db
*.db-wal
*.db-shm
日志
二维码
session
证书
私钥
```

其中 SQLite 数据库虽然不直接保存明文 Session Token 或密码，但包含用户、Scope、IP、审计事件和 Hash，也必须按敏感运行数据保护。

要求：

- 由 Git 忽略并限制文件系统权限；
- 备份时进入加密或受控存储；
- 不在日志、截图、Issue 和普通 API 响应中输出完整秘密值；
- 泄漏后立即轮换对应 Token/Cookie/密码；
- QQ refresh token、refresh key、musickey、access token 按登录凭据处理；
- 不把 SQLite 数据库上传到公开问题单。

## 仓库秘密扫描

仓库根目录执行：

```bash
python scripts/check_secrets.py
```

CI 使用完整 Git 历史检出，并扫描：

- tracked 文件；
- 全部可达 Git Blob；
- Commit Message；
- 敏感文件路径；
- 私钥、平台 Token、JWT、Authorization、真实秘密赋值等模式。

扫描不会打印匹配值，只打印类型与位置。

第三方依赖作者邮箱、历史示例值和 lockfile 高熵串属于隐私/启发式告警，不等于真实凭据。任何真正的 secret finding 都会令 CI 失败。

若真实秘密曾进入 Git：

1. 先立即轮换/撤销凭据；
2. 再清理当前树；
3. 按团队流程重写历史；
4. 通知所有持有旧 clone 的协作者重新同步。

“从最新提交删除”不能让已泄漏秘密重新安全。

## Web 终端接口

`POST /api/terminal/command` 当前已经受：

- Admin Role；
- 有效 Session；
- CSRF；

保护，但底层仍然是：

```text
首命令名单 + shell=True + 完整字符串
```

这意味着首词白名单不能可靠阻止 shell 元字符、管道、重定向和组合语法。只要管理员 Session 被盗、浏览器环境被攻陷或将来鉴权出现绕过，该接口就是直接远程命令执行边界。

建议优先级 P0：

- 最优：删除 Web 命令执行能力；或
- 改为固定命令 ID → 固定参数数组；
- `subprocess.run(..., shell=False)`；
- 明确每个参数的类型和范围；
- 单独记录审计。

不要把“只在 UI 隐藏按钮”视为安全控制。

KOOK `/cmd` 也执行 shell 字符串，但额外受 `CMD_ALLOWUSER` 控制；该列表留空时无人可执行。不要把普通音乐命令权限自动扩展到 `/cmd`。

## Bot 授权

Web Role/Scope 与 Bot 白名单互不替代。

`ALLOWGROUP`、`ALLOWCHANNEL`、`ALLOWUSER` 分别限制 Bot 命令服务器、频道和用户；多个维度同时配置时按交集生效。

`CMD_ALLOWUSER` 是 `/cmd` 的独立强权限名单。

管理员应使用最小必要范围并定期清理失效 ID。

## CSRF 与前端边界

所有 Web 写请求要求 CSRF。前端 `auth-client.js` 自动为同源 fetch/XHR 注入 `X-CSRF-Token`。

安全要求：

- 不允许跨域页面读取 CSRF Cookie；
- 不把 CSRF Token 写入日志；
- 不把用户可控 HTML 直接插入 DOM；
- 外部文本优先用 `textContent`；
- 新增写 API 时不得跳过统一 Middleware。

当前安全头包括：

```text
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: same-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
```

## Socket.IO

当前 Socket.IO 在 connect 时校验 Session 和首次改密状态。

如果后续增加：

- 敏感播放控制事件；
- 用户私有状态；
- 按 Guild/Channel 房间广播；

必须在每个事件/加入房间时执行 Role/Scope 校验。只验证 connect 不足以实现资源级隔离。

## 进程与媒体

- 签名播放 URL 作为参数数组传给 FFmpeg，不经过 shell。
- 端口清理必须验证 PID、命令行和目录归属。
- 不批量结束同机所有 Node、Python 或 FFmpeg。
- Node API 使用系统全局运行代码，用户 Cookie 留在平台 `Cookie/`。
- 任何包含 Cookie、Token 或签名 URL 的异常信息都不得原样返回前端。

## 日志与审计

运行日志只记录排障所需错误类别、状态和脱敏上下文。

`audit_logs` 会记录认证、IAM 和成功写 API，但审计日志本身包含用户名、资源 ID、来源 IP 等安全上下文，因此只允许管理员或离线运维访问。

对外分享日志前删除：

- Token / Cookie；
- 用户名与内部账号信息；
- Guild/Channel ID；
- IP；
- 完整媒体 URL；
- 临时密码。

## 备份安全

需要保护的持久数据：

```text
.env
Cookie/
data/
```

数据库启用 WAL。在线直接只复制 `kook_music.db` 可能得到不完整快照；优先停止实例或使用 SQLite 一致性备份方式。

备份应加密并限制恢复权限。恢复数据库会同时恢复 Web 用户和 Scope，因此不能把数据库恢复文件当作普通配置包分发。

## 发布检查

仓库根目录至少执行：

```bash
python scripts/check_secrets.py
python scripts/check_platform_sync.py
python -m compileall windows Ubuntu
git status --short
```

并确认：

- `.env` 未跟踪；
- Cookie/Credential 未跟踪；
- `data/` / SQLite 未跟踪；
- 没有 Token、Cookie、私钥、证书、真实账号密码、内部地址或签名 URL；
- 新增 API 已明确 Role/Scope/CSRF 边界；
- Windows/Ubuntu 共享实现未分叉。
