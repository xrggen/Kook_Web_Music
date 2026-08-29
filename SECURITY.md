# 安全与隐私

本项目默认用于可信网络内自托管。Web 控制台包含账号管理、日志、播放控制和 shell 命令入口，不能在没有额外认证的情况下直接暴露公网。

## 基本要求

- 本机使用设置 `HOST=127.0.0.1`。
- 远程访问使用 TLS、身份认证和受限来源的反向代理、VPN 或零信任访问层。
- 不公开 3000、3200 端口。
- `.env`、`Cookie/`、日志、二维码、Token、证书和私钥不得提交 Git。
- 凭据泄漏后立即轮换。
- 生产环境应禁用或拦截 `POST /api/terminal/command`。

## 发布检查

```bash
python scripts/check_secrets.py
git status --short
```

完整威胁模型、凭据边界和命令执行风险见 [docs/security.md](docs/security.md)。
