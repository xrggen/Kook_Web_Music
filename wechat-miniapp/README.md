# 微信小程序控制台

这是 KOOK Web Music 的微信原生模块，可以搜索、导入歌单、管理队列和查看播放状态。管理员还可管理音乐账号、查看运行状态及维护用户。权限由 Cloud 按角色和频道 Scope 校验。

## 集成与验证

1. 按 [Cloud / Edge 部署](../docs/cloud-edge-deployment.md)启动后端。修改 [config.js](config.js) 的 HTTPS 地址，使其指向你的 Cloud。在宿主小程序设置同一 HTTPS 请求域名和端口。
2. 宿主构建器读取 [tool.json](tool.json)，将模块装配到主包的 `kook/`，并注册页面 `kook/pages/console/console`。把组装好的宿主项目导入微信开发者工具。
3. 从仓库根目录运行模拟网络回归。用目标环境的微信客户端验收账号密码登录、绑定和免密登录。

```bash
node --test wechat-tests/kook-native.test.js wechat-tests/kook-mobile.test.js
```

## 交互及数据边界

首次使用控制台账号密码登录，并完成首次改密。用户可在“我的”中主动绑定微信，下次显式选择“微信免密登录”。解除绑定后，后续免密登录需要重新绑定。相关流程和错误码见 [Web API](../docs/web-api.md#微信关联接口)。

小程序保留用户名和界面偏好。密码、Session、CSRF 及扫码参数仅用于当前运行，后台暂停轮询。写操作超时后先刷新状态确认结果。微信 AppSecret 由 Cloud 配置，宿主包内只需要公开的小程序信息和 API 地址。
