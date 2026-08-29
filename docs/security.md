# 安全边界与部署建议

## 1. 当前定位

该项目最初更接近自托管控制台，而不是面向公网的多租户 Web 产品。安全策略应以“可信网络内自托管”为默认假设，除非额外部署反向代理、认证和访问控制。

## 2. Web 暴露面

当前 Flask 可能默认监听 `0.0.0.0`。这意味着同一网络中的其他主机也可能访问 Web 控制台。

控制台包含：

- 服务器/频道控制。
- 播放队列操作。
- 音乐平台账号登录和 Cookie 管理。
- 运行状态/日志类接口。
- 历史兼容的运维/终端能力。

因此不要把端口 5000 直接映射到公网后假设“没有登录页面也没关系”。

## 3. 推荐网络部署

如果只在本机使用，优先：

```env
HOST=127.0.0.1
```

如果需要局域网访问：

- 使用主机防火墙限制来源网段。
- 不在访客 Wi-Fi 或不可信 VLAN 暴露。

如果确实需要远程公网访问：

- 放在带认证的反向代理/VPN/Zero Trust 隧道之后。
- 启用 TLS。
- 限制来源身份或 IP。
- 不直接裸露 Flask 开发服务器。

## 4. Cookie 与 Credential

敏感文件包括但不限于：

- `.env`
- `Cookie/cookie.txt`
- `Cookie/qq_cookie.txt`
- `Cookie/qq_credential.json`
- `Cookie/bili_cookie.txt`
- session/credential/secret 类 JSON

要求：

- Git 忽略。
- 备份时加密或放在受控存储。
- 日志不打印完整内容。
- Web API 不返回完整值。

## 5. QQ Credential Manager

refresh token、refresh key、musickey 与 access token 都应视为登录凭据。自动续期线程只能读取/写入服务端凭据文件。

续期失败日志应记录错误类别和必要状态，不应记录完整 refresh token 或新 Cookie。

## 6. 播放 URL

部分平台播放 URL 带签名、临时 token、设备或账号相关参数。日志和 UI 中不要完整输出这类 URL。

歌曲展示名称应来自显式 title/artist；网络 URL 不应成为标题 fallback。

## 7. Shell / 终端接口

任何接受用户输入并最终进入 shell 的接口都是高风险边界。即使做了首 token 白名单，也不能把“首命令合法”等同于“整条 shell 字符串安全”。

生产或公网部署建议：

- 禁用不必要的终端执行入口，或
- 改为 `shell=False` 的固定参数化命令映射，且
- 单独增加强认证和授权。

不要通过字符串黑名单尝试覆盖所有 shell 元字符和组合语法。

## 8. Bot 命令授权

KOOK 命令使用 `ALLOWGROUP`、`ALLOWCHANNEL`、`ALLOWUSER` 等白名单。多个白名单同时配置时按交集处理。

系统命令类能力使用独立授权，不应因为普通音乐命令可用就自动开放。

## 9. Node API

网易云/QQ 本地 API 默认只应作为本机内部依赖使用。不要单独把 3000/3200 端口暴露公网。

`run.py` 清理端口残留进程时必须校验进程工作目录归属，避免误杀同机其他 Node 服务。

## 10. 发布前检查

至少执行项目现有秘密扫描：

```bash
python scripts/check_secrets.py
```

人工确认：

- 无 `.env`。
- 无真实 Cookie/Credential。
- 无 Token、私钥。
- 无个人域名/内网地址泄漏。
- 无包含签名媒体 URL 的日志样例。

## 11. 仍需持续改进的安全方向

当前最重要的长期改进方向是为 Web 控制台建立明确的认证/授权边界，并收敛历史终端执行能力。此项属于运行时安全架构升级，不应仅靠 UI 隐藏按钮替代。
