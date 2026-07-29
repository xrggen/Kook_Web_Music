# 安全与隐私

## 凭据管理

- KOOK Bot Token、网易云/QQ/B站 Cookie、Flask `SECRET_KEY`、用户/频道白名单及登录会话只能保存在本机 `.env` 或 `Cookie` 运行目录中。
- Windows 使用 `python windows/create_env.py`，Ubuntu 使用 `python3 Ubuntu/create_env.py`。脚本不会回显 Token，并会自动生成随机 `SECRET_KEY`。
- `.env.example` 只提供空白模板，不得写入真实账号、频道、用户或服务器 ID。
- 不得提交日志、心跳、二维码、私钥、证书、会话数据库或任何 Cookie 文件。

## 发布前检查

在仓库根目录执行：

```bash
python scripts/check_secrets.py
git status --short
```

只有扫描通过、工作区内容经过人工复核后才能推送。若凭据曾进入任何提交，即使之后删除文件，也必须先轮换该凭据并重写 Git 历史。

## 历史重写后的推送

历史重写会改变全部提交 ID。若线上仓库已有旧历史，需要通知所有协作者停止提交，然后使用受保护的强制推送更新目标分支；其他克隆必须重新克隆，不能把旧提交合并回来。
