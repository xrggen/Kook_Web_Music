# 安全审计修复与加固基线

本文记录 `refactor/desktop-ui-v2` 分支在深度代码审计后形成的安全基线，说明发现了什么问题、风险如何产生、代码如何修复，以及部署或继续开发时必须保持的约束。本文不是版本流水账；后续实现变化时，应直接更新这里描述的当前机制。

适用平台：`windows/`、`Ubuntu/`。两端共享业务实现、模板、静态资源和测试，除明确的平台差异外必须保持一致。

## 修复结论

- 已取消 Web 与 KOOK Bot 的通用远程命令执行能力，`/cmd` 不再注册。
- 已修复播放资源鉴权中请求参数来源不一致、Guild/Channel 归属未验证等授权绕过。
- 已统一应用工厂与鉴权安装路径，避免部署半初始化 Flask 对象绕过统一 Middleware。
- 已收紧 Bot 默认授权、外部媒体源、第三方 HTTP 请求、歌单导入和队列资源边界。
- 已修复平台数据进入管理员页面时的 DOM XSS 风险，并增加 CSP、SRI、缓存与日志保护。
- 已将音乐平台凭据改为受控 Header/文件传递，增加递归响应脱敏和 POSIX 原子权限写入。
- 已将项目内 Node 环境完全收缩为系统 Node.js 20+ 与系统全局固定版本包。
- 默认端口调整为连续的非标准端口：Web `18473`、网易云 `18474`、QQ `18475`。

## 问题与修复矩阵

| 等级 | 问题 | 主要风险 | 当前修复 |
|---|---|---|---|
| P0 | Web/机器人曾存在通用命令执行入口 | 远程命令执行、主机完全失陷 | 删除通用执行能力和 `/cmd`；日志接口只读；子进程全部使用受控参数数组 |
| P1 | POST 鉴权可读取 Query，而业务读取 JSON | 守卫校验一个 Guild/Channel，业务操作另一个资源 | 统一提取资源 ID；重复参数、Query/JSON 冲突或格式异常直接拒绝 |
| P1 | Guild Scope 信任客户端声明的频道归属 | 持有 Guild A Scope 的用户可能控制 Guild B 频道 | 服务端查询频道真实 Guild；频道必须 `enabled=1`、`verified=1`，所属 Guild 也必须启用 |
| P1 | 普通用户页面/API 权限契约不一致 | `/library` 与账号只读能力发生功能回归 | User 可访问音乐库和最小账号状态/歌单 GET；账号写操作仍为 Admin only |
| P1 | 直接部署模块级 Flask 对象可能漏装鉴权 | `/api/debug` 等路由在错误入口下无统一保护 | 只通过 `create_app()`/`run.py` 创建完整应用；Blueprint 注册时统一安装 Auth Middleware |
| P1/P2 | 管理员禁用/删除检查存在并发窗口 | 两个并发操作可能移除最后一个启用管理员 | IAM 写操作使用 SQLite `BEGIN IMMEDIATE`，在同一写事务内检查并更新不变量 |
| P2 | 平台歌单数据以 HTML 字符串插入 DOM | 恶意歌名、封面或作者字段触发管理员 DOM XSS | 动态数据使用 DOM API、`textContent` 和属性赋值；外部图片 URL 经过协议校验；移除动态 inline handler |
| P2 | 歌单与请求缺少统一资源上限 | 大歌单、超大请求或并发导入耗尽内存/队列/线程 | 增加请求体、单次导入、队列、并发、分页、搜索结果和字段长度上限 |
| P2 | QQ Cookie 放入 URL Query | Cookie 进入代理、访问日志、异常对象或诊断系统 | Cookie 只放请求 Header；账号响应递归移除 credential/token/cookie 等字段 |
| P2 | Cookie/Credential 文件依赖默认 umask | Linux 上凭据可能对其他本机用户可读 | `secure_storage.py` 使用同目录临时文件、`fsync`、原子替换；POSIX 目录 `0700`、文件 `0600` |
| P2 | 第三方请求默认跟随重定向 | 凭据被重定向到非预期目标，扩大 SSRF/泄漏面 | 账号、搜索、取链、二维码和本地 API 请求统一 `allow_redirects=False` |
| P2 | 签名媒体 URL 和异常详情写入日志/API | Token、签名、路径或 Cookie 经日志接口泄漏 | 日志仅记录域名/资源安全标识或异常类型；读取日志前再次脱敏；外部错误返回固定消息 |
| P2/P3 | Bot 白名单为空时默认全开放 | 任意可见 KOOK 用户可控制播放与恢复命令 | 空白名单默认拒绝；只有显式 `BOT_ALLOW_UNRESTRICTED=true` 才开放 |
| P2/P3 | `/wy`、`/qq` 接受任意 HTTP(S) 直链 | 主机被用于内网探测或下载超大资源 | Bot 命令只接受搜索词；播放器拒绝非 HTTP(S)、内嵌凭据、本机/保留地址和明显内网主机 |
| P2/P3 | 登录 `next` 对编码和反斜杠处理不足 | 浏览器规范化后形成开放重定向 | 有界解码，拒绝绝对 URL、双斜杠、反斜杠、控制字符和异常 URL |
| P2/P3 | KOOK/平台 API 返回结构被直接信任 | 异常类型、超长字段或恶意 URL进入队列/UI | 对 ID、文本、列表、URL、分页和响应类型进行白名单规一化并截断 |
| P2/P3 | 管理员禁用频道后同步可能重新启用 | 运维禁用状态被下一次 KOOK 同步覆盖 | 同步只更新真实归属、名称、类型与 `verified`，保留现有 `enabled` 状态 |
| 加固 | 第三方静态资源与敏感响应缓存边界不足 | CDN 资源被替换、用户数据被共享缓存 | 外部资源增加 SRI/crossorigin；统一 CSP 与安全头；API/鉴权响应使用 `private, no-store` |

## 具体实现

### 1. 统一身份与资源授权

`auth.py` 作为统一请求边界：

1. 非 GET 请求只接受结构正确的 JSON 对象。
2. `guild_id`、`channel_id` 等资源 ID 在进入业务路由前只规一化一次。
3. 同名 Query 参数重复、Query 与 JSON 同时存在但值不一致时返回 `400`，不再由守卫和业务分别选值。
4. Channel Scope 和 Guild Scope 都由数据库确认 `channel_id -> guild_id` 的真实关系，不信任客户端声明。
5. 已禁用 Guild/Channel 或尚未由 KOOK 同步验证的 Channel 不参与授权和可见列表。
6. 普通用户只能在 Role 允许且 Scope 匹配时读取或控制播放资源。

`sync_channel()` 在原子事务中修正频道所属 Guild，并将 KOOK 已确认频道标记为 `verified=1`；它不会把管理员手工禁用的频道重新启用。

登录回跳只允许当前站点内以 `/` 开头的相对路径。经过有限层 URL 解码后，只要出现 scheme、netloc、`//`、反斜杠或控制字符就回退 `/dashboard`。

### 2. 应用工厂与统一 Middleware

应用不再暴露一个只注册部分路由的模块级全局 Flask 实例。`run.py` 调用 `create_app()`，业务 Blueprint 完整注册后由 `api.py` 的 `record_once` 安装鉴权：

```text
create_app
  -> 注册页面/API
  -> register_auth
  -> before_request: Session / 改密 / CSRF / Role / Scope
  -> after_request: 过滤 / 审计 / CSP / no-store
```

部署入口固定为平台目录中的 `run.py`。不要使用 `app:app` 等绕过应用工厂的 WSGI 配置；若未来增加正式 WSGI 入口，它也必须显式调用 `create_app()`。

### 3. 取消通用命令执行

- Web 不提供接收任意命令、参数或脚本的接口。
- KOOK Bot 不注册 `/cmd`。
- `/api/terminal/output` 只读取已存在日志的增量，不执行命令、不创建子进程。
- FFmpeg、Node API 和受控清理继续需要子进程，但都以固定可执行文件和参数数组启动，不使用 `shell=True` 或 `os.system`。
- 清理端口前校验 PID、命令行、可执行文件和工作目录归属，不按进程名批量终止同机进程。

### 4. Node 运行时收缩

两个平台的 `run.py` 只接受系统 PATH 中、位于项目目录外的 Node.js 20+ 与 npm：

1. 通过 `node --version` 校验主机 Node。
2. 通过 `npm root --global` 查找全局包。
3. 网易云固定使用 `NeteaseCloudMusicApi@4.25.0`。
4. QQ 固定使用 `@sansenjian/qq-music-api@2.3.1`。
5. 项目内出现 `node_modules`、便携 Node 或 Node API 源码时拒绝启动。
6. Python 不执行 npm 安装、构建或运行时回退。

所有 Python 业务和两个 Node API 共用主机系统 Node 环境。音乐平台 Cookie 仍保存在各实例的 `Cookie/`，不会写入全局 npm 包目录。

### 5. 媒体与外部网络边界

播放器只接受：

- 已验证的内部延迟播放标记；
- 当前确实存在的本地文件；
- 无内嵌用户名/密码的 HTTP(S) URL。

URL 主机拒绝 `localhost`、常见本地域名后缀，以及回环、私有、链路本地、保留等非全局字面 IP。第三方 HTTP 请求设置超时且不跟随重定向。Bot 的 `/wy`、`/qq` 只把输入当搜索词，不再把 `http...` 直接交给 FFmpeg。

该检查不能代替主机网络策略。域名解析结果可能在请求期间变化，生产环境仍应通过防火墙、容器网络或 egress policy 禁止访问云元数据和内部管理网段。

### 6. 请求、队列与平台数据上限

默认边界：

| 项目 | 默认值 | 可配置范围 |
|---|---:|---:|
| Web 请求体 | 1 MiB | 64 KiB–16 MiB |
| 单次歌单导入 | 1000 首 | 1–10000 |
| 单频道待播队列 | 2000 首 | 1–10000 |
| 同时进行的 Web 歌单导入 | 2 | 1–32 |

网易云、QQ、Bilibili 适配器还分别限制搜索关键词、页码、分页大小、ID 长度、二维码 key、收藏夹/分 P 数量、元数据字段和媒体 URL 长度。第三方 JSON 必须先确认对象/数组类型，再按允许字段创建新的内部对象；不会把未经筛选的整段平台响应直接送入队列或前端。

### 7. 凭据存储与传递

凭据路径仍位于平台部署目录：

```text
Cookie/cookie.txt
Cookie/qq_cookie.txt
Cookie/qq_credential.json
Cookie/bili_cookie.txt
```

写入统一经过 `secure_storage.py`：同目录创建临时文件、限制权限、刷新到磁盘、原子替换目标。在 POSIX 上凭据目录收紧到 `0700`，文件收紧到 `0600`。Windows 依赖运行服务账号和目录 ACL。

QQ Cookie 通过 Header 发送给本机 QQ API，不再放进 URL Query。网易云与 Bilibili Cookie 也执行长度、控制字符和最小字段校验。账号 API 对外部响应递归删除 cookie、credential、refresh token/key、access token 等敏感键，异常响应不回显第三方请求对象。

### 8. 前端、响应头与日志

- 平台歌单、作者、封面、ID 和错误文本使用 `textContent`、`createElement` 和受控属性赋值。
- 动态数据不拼接进 `onclick`、`src`、`alt`、`title` 或 HTML 字符串。
- 外部图片只接受允许协议；无效值使用本地占位。
- Bootstrap、Bootstrap Icons 和 jQuery 等 CDN 资源配置 SRI 与 `crossorigin`。
- Auth Middleware 设置 CSP、`X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`、`Permissions-Policy`。
- API、登录、改密和管理响应使用 `Cache-Control: private, no-store`。
- 媒体日志不记录完整签名 URL；Node 子进程输出和管理员日志读取接口都会再次执行 secret/query 脱敏。

## 兼容性与部署影响

升级到该基线前必须注意：

1. `/cmd` 已删除，任何依赖通用远程命令的自动化都必须改为明确、受鉴权的管理动作。
2. Bot 三类白名单都为空时不再开放。确需全开放必须显式设置 `BOT_ALLOW_UNRESTRICTED=true`，且只适合受信任 KOOK 环境。
3. 任意媒体直链不再作为 `/wy`、`/qq` 输入；播放器也会拒绝本机、私有或保留目标。
4. POST 的 Query/JSON 资源 ID 冲突现在返回 `400`；调用方应只在 JSON 中发送一次资源 ID。
5. 管理员禁用的 Guild/Channel 不会因 KOOK 同步恢复，需由管理员显式重新启用。
6. 超过资源上限的请求、搜索、分页、歌单或队列会被拒绝或截断。
7. 部署主机必须预装系统 Node.js 20+ 和两个固定全局包；仓库内 Node 环境不再受支持。
8. 默认端口为 `18473`–`18475`。升级现有实例时逐项合并 `.env`，同步修改反向代理、防火墙和健康探针。
9. Linux 运行账号必须拥有 `Cookie/` 和 `data/`；首次安全写入可能收紧目录权限，多个 Unix 用户共享同一实例目录的方式不再受支持。

## 主要代码位置

| 区域 | Windows/Ubuntu 共享文件 |
|---|---|
| Auth、Scope、CSRF、应用工厂 | `auth.py`、`api.py`、`app.py` |
| Web 路由与资源限制 | `routes.py`、`config.py` |
| 播放器、媒体 URL、进程安全 | `kookvoice/kookvoice.py`、`kookvoice/requestor.py` |
| 网易云适配与账号 | `utils.py`、`account_api.py`、`cookie_login*.py` |
| QQ 适配与 Credential | `qq_utils.py`、`qq_account_api.py`、`qq_credential.py` |
| Bilibili 适配与账号 | `bili_utils.py`、`bili_account_api.py` |
| 原子凭据写入 | `secure_storage.py` |
| 启动、系统 Node、日志、端口 | `run.py`、`.env.example` |
| DOM 安全 | `static/js/account.js`、`qq_account.js`、`bili_account.js` |
| UI 权限边界与安全资源 | `templates/`、`static/js/users.js` |
| 回归测试 | `tests/test_auth.py`、`test_stability.py`、`test_watchdog.py`、`test_security_regressions.py` |

## 验证基线

2026-08-31 由独立 `luna_worker` 在当前工作树执行，验证过程未修改文件：

| 验证 | 结果 |
|---|---|
| `python -m compileall -q windows Ubuntu` | 通过 |
| Windows unittest | 57/57 通过 |
| Ubuntu unittest | 57/57 通过 |
| `python scripts/check_platform_sync.py` | 通过 |
| `git diff --check` | 通过 |

合计 114 个单元测试全部通过。该结果证明当前自动化覆盖下未发现回归，不等同于第三方平台在线可用性、生产渗透测试或 Git 全历史秘密扫描结论。

发布前仍需在受控 CI 中运行 `scripts/check_secrets.py`。若全历史扫描报告真实 secret finding，应先轮换凭据，再按团队流程处理 Git 历史；不得在普通构建日志中回显命中值。

## 后续维护约束

1. 新 API 默认受统一 Auth Middleware 保护；写请求必须有 CSRF，普通用户能力必须声明 Role 和 Scope。
2. 不得恢复通用 shell、`/cmd`、`shell=True`、`os.system` 或由用户提供任意可执行参数的接口。
3. 新增平台字段时先规一化，再进入队列、日志或 DOM。
4. 新增公网请求必须有固定目标边界、超时、禁止非预期重定向并避免携带秘密进入 URL。
5. 修改共享代码时同时更新 Windows/Ubuntu，并通过平台一致性检查。
6. 文档、测试和实现必须在同一提交中更新；验证结果写明执行环境和未覆盖边界。

关联文档：[架构](architecture.md)、[鉴权](authentication.md)、[Web API](web-api.md)、[部署](deployment.md)、[安全边界](security.md)、[运维](operations.md)。
