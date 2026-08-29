# Web UI

## 页面模型

控制台采用桌面音乐客户端布局，桌面与移动端共用 Jinja 模板、API 和业务状态。

桌面结构：

```text
左侧导航 | 主工作区 | 播放队列
              底部全局播放器
```

移动端在 `max-width: 820px` 下切换为顶部上下文、单主视图、迷你播放器、底部导航和 Bottom Sheet。队列、服务器选择和展开播放器复用原有 DOM，不创建第二份状态。

Web 鉴权页面同样为 Windows/Ubuntu 共享实现，不维护第二套平台模板。

## 页面职责

- `/login`：本地账号登录。
- `/change-password`：首次登录或密码重置后的强制改密。
- 播放：服务器、语音频道、搜索、队列和播放控制。
- 音乐库：三平台用户歌单。
- 账号：网易云、QQ 音乐与 Bilibili 登录态；Admin only。
- 系统状态：健康、日志和运行信息；Admin only。
- 设置：当前浏览器的主题、密度和减少动画；Admin only。
- `/users`：用户、角色、启用状态和 playback Scope 管理；Admin only。

普通用户只看到播放与音乐库等允许入口；管理员看到完整导航。导航隐藏只用于 UX，后端 Auth Middleware 仍是最终权限边界。

## 首次登录体验

Bootstrap 管理员以及被管理员重置密码的用户具有 `must_change_password=1`。

登录成功后：

```text
/login
  ↓
/change-password
  ↓
新密码通过策略校验
  ↓
旧 Session 撤销 + 新 Session
  ↓
/dashboard
```

在改密完成前，不能通过手工输入其他控制面 URL 绕过流程。

## 用户管理 UI

`/users` 仅管理员可见，用于：

- 创建 Admin/User；
- 显示一次性临时密码；
- 修改角色；
- 启用/禁用账号；
- 编辑普通用户 Scope；
- 重置密码；
- 删除用户。

Scope 文本格式：

```text
*
guild:<KOOK_GUILD_ID>
channel:<KOOK_GUILD_ID>/<KOOK_CHANNEL_ID>
```

临时密码只在创建/重置成功时展示一次。前端不得写入 LocalStorage、日志或 URL。

## 前端资源

| 文件 | 职责 |
|---|---|
| `style.css` | 基础样式与 Bootstrap 兼容 |
| `app.css` | 应用壳、导航和共享组件 |
| `auth.css` | 登录、改密与用户管理 |
| `dashboard.css` | 播放页桌面布局 |
| `theme.css` | 深浅色变量与覆盖 |
| `mobile.css` / `mobile-polish.css` | 移动布局、触控和视觉细节 |
| `theme-init.js` | 页面绘制前应用主题和移动资源 |
| `auth-client.js` | 同源请求 CSRF 注入与鉴权前端辅助 |
| `app-ui.js` | 主题、密度、减少动画与健康灯 |
| `mobile-ui.js` | 移动导航、Sheet、播放器与视口行为 |
| `dashboard.js` | 搜索、频道、队列和播放业务 |
| `dashboard-ui.js` | 播放页界面增强 |
| `users.js` | 用户管理 |
| `account.js` / `qq_account.js` / `bili_account.js` | 账号交互 |
| `library.js` / `status.js` / `settings.js` | 对应页面业务 |

## CSRF 前端约束

服务端要求所有 POST/PUT/PATCH/DELETE 通过 CSRF。

共享 `auth-client.js` 会为同源 fetch/XHR 自动加入：

```text
X-CSRF-Token
```

因此新增业务页面时应复用全局请求层，不复制一套 Cookie/Token 读取逻辑。

禁止：

- 把 Session Cookie 暴露给 JS；
- 把 CSRF Token 写入日志；
- 把临时密码写入 LocalStorage；
- 把账号 Cookie/Credential 返回页面；
- 为绕过错误而关闭服务端 CSRF。

## 浏览器偏好

- `kook.ui.theme`：dark、light、system。
- `kook.ui.density`：comfortable、compact。
- `kook.ui.reducedMotion`：减少动画。

偏好只保存在当前浏览器，不写入服务端 `.env` 或 SQLite 用户配置。主题初始化同时设置 Bootstrap `data-bs-theme`、`color-scheme` 和移动浏览器 `theme-color`。

## 错误状态

前端应正确处理鉴权状态：

- `401`：Session 失效，进入登录流程。
- `403`：没有 Role/Scope 或 CSRF 失败，不应假装操作成功。
- `428`：跳转/提示首次改密。
- `429`：登录失败限速，避免高频自动重试。

业务错误仍按原 API 的 `success` / `error` 处理。

## 实现约束

- 不新增独立 `mobile.html` 或复制 `dashboard.js`。
- 登录/改密/用户管理在 Windows/Ubuntu 保持共享。
- 外部文本默认使用 `textContent`。
- 触控目标优先达到 44 CSS px。
- 弹层处理 Escape、点击外部、背景滚动与 safe area。
- 处理软键盘造成的 Visual Viewport 变化。
- 搜索和频道切换使用请求序列或上下文校验。
- UI 隐藏不能替代服务端权限。
- 临时密码等一次性敏感信息显示后不持久化。

界面变更至少覆盖桌面/移动、深色/浅色、窄屏、横屏、软键盘、队列 Sheet、展开播放器、登录、首次改密和管理员/普通用户导航差异。
