# Web UI

## 页面模型

控制台采用桌面音乐客户端布局，桌面与移动端共用 Jinja 模板、API 和业务状态。

桌面结构：

```text
左侧导航 | 主工作区 | 播放队列
              底部全局播放器
```

移动端在 `max-width: 820px` 下切换为顶部上下文、单主视图、迷你播放器、底部导航和 Bottom Sheet。队列、服务器选择和展开播放器复用原有 DOM，不创建第二份状态。

## 页面职责

- 播放：服务器、语音频道、搜索、队列和播放控制。
- 音乐库：三平台用户歌单。
- 账号：网易云、QQ 音乐与 Bilibili 登录态。
- 系统状态：健康、日志和运行信息。
- 设置：当前浏览器的主题、密度和减少动画。

## 前端资源

| 文件 | 职责 |
|---|---|
| `style.css` | 基础样式与 Bootstrap 兼容 |
| `app.css` | 应用壳、导航和共享组件 |
| `dashboard.css` | 播放页桌面布局 |
| `theme.css` | 深浅色变量与覆盖 |
| `mobile.css` / `mobile-polish.css` | 移动布局、触控和视觉细节 |
| `theme-init.js` | 页面绘制前应用主题和移动资源 |
| `app-ui.js` | 主题、密度、减少动画与健康灯 |
| `mobile-ui.js` | 移动导航、Sheet、播放器与视口行为 |
| `dashboard.js` | 搜索、频道、队列和播放业务 |
| `dashboard-ui.js` | 播放页界面增强 |
| `account.js` / `qq_account.js` / `bili_account.js` | 账号交互 |
| `library.js` / `status.js` / `settings.js` | 对应页面业务 |

## 浏览器偏好

- `kook.ui.theme`：dark、light、system。
- `kook.ui.density`：comfortable、compact。
- `kook.ui.reducedMotion`：减少动画。

偏好只保存在当前浏览器，不写入服务端 `.env`。主题初始化同时设置 Bootstrap `data-bs-theme`、`color-scheme` 和移动浏览器 `theme-color`。

## 实现约束

- 不新增独立 `mobile.html` 或复制 `dashboard.js`。
- 外部文本默认使用 `textContent`。
- 触控目标优先达到 44 CSS px。
- 弹层处理 Escape、点击外部、背景滚动与 safe area。
- 处理软键盘造成的 Visual Viewport 变化。
- 搜索和频道切换使用请求序列或上下文校验。

界面变更至少覆盖桌面/移动、深色/浅色、窄屏、横屏、软键盘、队列 Sheet 和展开播放器。
