# 安全边界

## 默认威胁模型

项目按可信网络内的单实例自托管控制台设计，不是具备完整身份认证、租户隔离和细粒度授权的公网产品。Flask 可监听 `0.0.0.0`，但这不代表控制台适合裸露到互联网。

控制台能够控制语音频道、修改队列、管理音乐账号、读取/清空日志、执行清理操作，并保留 shell 命令入口。任何能访问 Web 端口的主体都应视为可能获得高权限。

## 网络暴露

本机使用建议：

```env
HOST=127.0.0.1
```

局域网访问应使用主机防火墙限制来源。远程访问必须放在带 TLS 和身份认证的反向代理、VPN 或零信任访问层之后。

3000 和 3200 仅供本机 Python 应用访问，不应映射公网。不要直接使用 Flask 开发服务器承载无保护的公网流量。

## 凭据

敏感文件包括：

- `.env`
- `Cookie/cookie.txt`
- `Cookie/qq_cookie.txt`
- `Cookie/qq_credential.json`
- `Cookie/bili_cookie.txt`
- 日志、二维码、session、证书和私钥

要求：

- 由 Git 忽略并限制文件权限。
- 备份时加密或进入受控秘密存储。
- 不在日志、截图、问题单和普通 API 响应中输出完整值。
- 泄漏后立即轮换对应 Token/Cookie，而不只是删除文件。
- QQ refresh token、refresh key、musickey 和 access token 均按登录凭据处理。

## Web 终端接口

`POST /api/terminal/command` 只检查首个命令名，但随后使用 `shell=True` 执行完整字符串。首词白名单不能阻止 shell 元字符、管道、重定向或组合语法，因此该接口属于远程命令执行边界。

安全部署应禁用或在反向代理层阻断该路由；如果业务必须保留，应改为 `shell=False` 的固定命令与参数映射，并增加独立认证和授权。仅在 UI 中隐藏按钮不构成安全控制。

KOOK `/cmd` 同样执行 shell 字符串，但额外受 `CMD_ALLOWUSER` 控制。该名单留空时无人可执行；不要将普通音乐命令权限自动扩展到 `/cmd`。

## Bot 授权

`ALLOWGROUP`、`ALLOWCHANNEL`、`ALLOWUSER` 分别限制服务器、频道和用户；配置多个维度时按交集生效。管理员应使用最小必要范围，并定期清理失效 ID。

## 进程与媒体

- 签名播放 URL 作为参数数组传给 FFmpeg，不经过 shell。
- 端口清理必须验证 PID、命令行和目录归属。
- 不批量结束同机所有 Node、Python 或 FFmpeg。
- Node API 使用系统全局只读运行代码，用户 Cookie 留在平台 `Cookie/`。

## 日志与错误

日志只记录排障所需的错误类别、状态和脱敏上下文。歌曲标题应来自显式元数据，不能用网络 URL 回退。对外分享日志前删除 Token、Cookie、用户/频道标识和完整媒体 URL。

## 发布检查

在仓库根目录执行：

```bash
python scripts/check_secrets.py
git status --short
```

人工确认没有 `.env`、Cookie/Credential、Token、私钥、证书、内部地址、真实账号或签名 URL。若敏感信息曾进入提交，先轮换凭据，再按团队流程清理 Git 记录并协调所有协作者。
