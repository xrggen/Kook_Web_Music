# 登录态目录

该目录只保存当前 Windows 实例的服务端登录态：

- `cookie.txt`：网易云 Cookie。
- `qq_cookie.txt`：QQ 音乐兼容 Cookie。
- `qq_credential.json`：QQ 音乐刷新与到期元数据。
- `bili_cookie.txt`：Bilibili Cookie。

所有文件均为敏感信息，应由 Git 忽略。迁移时先停止源和目标实例，将 QQ 的两个文件成对复制；不要把 Cookie 写入系统全局 npm 包目录。
