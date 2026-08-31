# 安全与隐私

本项目默认用于可信网络内自托管。Web 控制台包含账号管理、日志、播放控制和进程清理，不能在没有额外认证的情况下直接暴露公网。项目不提供远程 shell 命令执行能力。

## 基本要求

- 本机使用设置 `HOST=127.0.0.1`。
- 远程访问使用 TLS、身份认证和受限来源的反向代理、VPN 或零信任访问层。
- 不公开 18474、18475 端口；Web 端口 18473 也应置于认证和 TLS 代理之后。
- `.env`、`Cookie/`、日志、二维码、Token、证书和私钥不得提交 Git。
- 凭据泄漏后立即轮换。
- `/api/terminal/output` 仅提供管理员读取运行日志增量；项目不提供远程命令执行接口。

## 发布检查

```bash
python scripts/check_secrets.py
git status --short
```

完整威胁模型、凭据边界和命令执行风险见 [docs/security.md](docs/security.md)。深度审计发现、逐项修法、兼容性变化和验证证据见 [安全审计修复与加固基线](docs/security-hardening.md)。
