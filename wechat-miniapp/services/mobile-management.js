'use strict'

const { PLATFORMS, text, platformView, coverUrl } = require('../utils/mobile-model')
const DATA = {
  accountPlatform: 0, account: null, accountState: 'idle', accountError: '', accountDetailsError: '', accountMode: 'qr', accountQr: '', qrStatus: '', accountInputNonce: 0,
  users: [], createUsername: '', createRole: 0, createScopes: '', roles: ['普通用户', '管理员'],
  temporaryPassword: '', temporaryPasswordUser: '', runtime: null, systemMetrics: [], logs: [], logType: 'app', logsLoaded: false,
}
function safeMessage(value) {
  return text(value, 4000).replace(/-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----/gi, '[私钥已隐藏]')
    .replace(/\bBearer\s+\S+/gi, 'Bearer [已隐藏]')
    .replace(/((?:cookie|csrf|password|token|credential|secret|signature|ticket)\s*[:=]\s*)[^\s,;]+/gi, '$1[已隐藏]')
    .replace(/(?:https?|wss?|rtmp):\/\/[^\s"']+/gi, '[地址已隐藏]')
}
function age(value) { const seconds = Number(value); return !Number.isFinite(seconds) || seconds < 0 ? '暂无数据' : seconds < 2 ? '刚刚' : seconds < 60 ? `${Math.round(seconds)} 秒前` : `${Math.floor(seconds / 60)} 分钟前` }
function runtimeView(body) {
  const bot = body.bot_state === 'running' || /运行中/.test(text(body.bot_status)), loop = Number(body.bot_loop_heartbeat_age), gateway = Number(body.kook_gateway_heartbeat_age)
  const healthy = bot && body.token_valid === true && body.ffmpeg_path === true && loop >= 0 && loop <= 120 &&
    (!body.kook_gateway_probe_available || gateway >= 0 && gateway <= 150)
  return { tone: healthy ? 'ok' : bot ? 'warn' : 'bad', title: healthy ? '运行状态正常' : bot ? '运行中，部分项目需要关注' : 'Bot 运行状态异常',
    copy: healthy ? 'Bot、事件循环与媒体依赖均可用。' : '请根据下方心跳、网关与依赖状态定位异常。',
    refreshedAt: new Date().toLocaleTimeString(),
    metrics: [{ label: '活跃频道', value: Number(body.active_guilds) || 0 }, { label: '正在播放', value: Number(body.playing_songs) || 0 },
      { label: '等待播放', value: Number(body.queued_songs) || 0 }, { label: 'Bot 状态', value: ({ running: '运行中', starting: '启动中', failed: '异常', configuration_error: '配置异常' })[body.bot_state] || text(body.bot_status, 50) || '未知' }],
    rows: [{ label: '事件循环心跳', value: age(body.bot_loop_heartbeat_age) }, { label: 'Gateway 心跳', value: body.kook_gateway_probe_available ? age(body.kook_gateway_heartbeat_age) : '未启用探针' },
      { label: 'Bot Token', value: body.token_valid === true ? '已配置' : '未配置' }, { label: 'FFmpeg', value: body.ffmpeg_path === true ? '可用' : '不可用' }] }
}
function userRows(rows) {
  return (Array.isArray(rows) ? rows : []).filter(row => row && Number.isSafeInteger(Number(row.id)) && Number(row.id) > 0 && ['admin', 'user'].includes(row.role)).slice(0, 500)
    .map(row => ({ id: Number(row.id), username: text(row.username, 32), role: row.role, roleIndex: row.role === 'admin' ? 1 : 0,
      enabled: row.enabled === true || row.enabled === 1, scopes: text(row.scopes, 4096),
      loginLabel: row.must_change_password ? '首次／重置密码待修改' : row.last_login_at ? `最近登录 ${new Date(Number(row.last_login_at) * 1000).toLocaleString()}` : '尚未登录' }))
}
const methods = {
  isAdmin() { return this.data.phase === 'console' && this.data.user?.role === 'admin' && !this.data.user.must_change_password },
  requireAdmin() { if (this.isAdmin()) return true; this.setView({ error: '此页面仅管理员可用' }); return false },
  clearManagement() {
    this.stopQr(); this.accountSecrets = {}; this.adminSequence = (this.adminSequence || 0) + 1
    this.setView({ ...DATA, users: [], logs: [], systemMetrics: [], accountInputNonce: (this.data.accountInputNonce || 0) + 1 })
  },
  stopQr() {
    this.qrSequence = (this.qrSequence || 0) + 1
    this.api?.cancelPlatformQr?.()
    if (this.qrTimer != null) this.cancelDelay(this.qrTimer)
    this.qrTimer = null; this.qrDeadline = 0
    if (!this.disposed) this.setView({ accountQr: '', qrStatus: '' })
  },
  chooseAccountPlatform(event) {
    const index = Number(event.currentTarget.dataset.index)
    if (!this.requireAdmin() || this.data.busy || !PLATFORMS[index]) return
    this.stopQr(); this.accountSecrets = {}; this.setView({ accountPlatform: index, account: null, accountState: 'idle', accountError: '', accountDetailsError: '', accountMode: 'qr', accountInputNonce: this.data.accountInputNonce + 1 })
    return this.refreshAccount()
  },
  async readAccount(epoch) {
    const platform = PLATFORMS[this.data.accountPlatform].id, sequence = this.adminSequence = (this.adminSequence || 0) + 1
    const current = () => this.current(epoch) && this.isAdmin() && sequence === this.adminSequence && PLATFORMS[this.data.accountPlatform].id === platform
    this.setView({ accountState: 'loading', accountError: '', accountDetailsError: '' })
    let status
    try { status = await this.api.platformStatus(platform) }
    catch (failure) {
      if (!current()) return
      if (['UNAUTHORIZED', 'PASSWORD_REQUIRED', 'FORBIDDEN'].includes(failure?.code)) throw failure
      this.setView({ accountState: 'error', accountError: safeMessage(failure?.message || '暂时无法读取音乐账号状态').slice(0, 220) })
      return
    }
    if (!current()) return
    const view = platformView(platform, status)
    const account = { ...view, avatar: coverUrl(status.face || status.data?.profile?.avatarUrl, platform), stats: [] }
    this.setView({ account, accountState: 'ready' })
    if (view.connected) {
      const actions = platform === 'wy' ? ['detail', 'level', 'subcount'] : ['profile']
      const results = await Promise.allSettled(actions.map(action => this.api.account(platform, action, action === 'detail' ? { uid: view.uid } : undefined)))
      if (!current()) return
      const authFailure = results.find(result => result.status === 'rejected' && ['UNAUTHORIZED', 'PASSWORD_REQUIRED', 'FORBIDDEN'].includes(result.reason?.code))
      if (authFailure) throw authFailure.reason
      const detail = results[0]?.status === 'fulfilled' ? results[0].value : {}
      const profile = detail.profile || detail.data?.profile || detail
      account.accountName = text(profile.nickname || profile.uname || profile.name) || account.accountName
      account.avatar = coverUrl(profile.avatarUrl || profile.avatar || profile.face, platform) || account.avatar
      account.stats = platform === 'wy' ? [{ label: '等级', value: text(results[1]?.value?.data?.level, 30) || '—' },
        { label: '歌单', value: text(results[2]?.value?.createdPlaylistCount, 30) || '—' }, { label: '关注', value: Number(profile.follows) || 0 }] :
        [{ label: platform === 'qq' ? 'QQ 号' : 'UID', value: account.uid }, { label: '等级', value: Number(profile.level) || '—' }]
      this.setView({ accountDetailsError: results.some(result => result.status === 'rejected') ? '账号已连接，部分资料暂未读取，可稍后刷新。' : '' })
    }
    if (current()) this.setView({ account })
  },
  refreshAccount() { if (this.requireAdmin()) return this.run(epoch => this.readAccount(epoch)) },
  chooseAccountMode(event) { if (!this.requireAdmin() || this.data.busy) return; const mode = event.currentTarget.dataset.mode;
    if (!['qr', 'cookie', 'phone'].includes(mode) || mode === 'phone' && this.data.accountPlatform !== 0) return
    this.stopQr(); this.accountSecrets = {}; this.setView({ accountMode: mode, accountInputNonce: this.data.accountInputNonce + 1 }) },
  setAccountSecret(event) { if (!this.isAdmin()) return; const field = event.currentTarget.dataset.field;
    if (['cookie', 'phone', 'captcha', 'countrycode'].includes(field)) this.accountSecrets[field] = String(event.detail.value || '').slice(0, field === 'cookie' ? 16384 : 32) },
  createQr() {
    if (!this.requireAdmin()) return
    this.stopQr()
    return this.run(async epoch => {
      const platform = PLATFORMS[this.data.accountPlatform].id, sequence = this.qrSequence
      const qr = await this.api.createPlatformQr(platform)
      if (!this.current(epoch) || sequence !== this.qrSequence || this.data.tab !== 'account') return
      const image = qr.image.startsWith('data:image/') ? qr.image : 'data:image/png;base64,' + qr.image
      if (!/^data:image\/(?:png|jpeg);base64,[A-Za-z0-9+/=\r\n]+$/.test(image) || image.length > 1500000) throw new Error('二维码图片无效，请重新生成')
      this.setView({ accountQr: image, qrStatus: '请使用对应音乐平台扫码并确认' }); this.qrDeadline = Date.now() + 180000
      this.scheduleQr(platform, epoch, sequence)
    })
  },
  scheduleQr(platform, epoch, sequence) {
    this.qrTimer = this.delay(async () => {
      this.qrTimer = null
      if (!this.current(epoch) || !this.isAdmin() || this.data.tab !== 'account' || sequence !== this.qrSequence) return
      if (Date.now() >= this.qrDeadline) { this.stopQr(); this.setView({ qrStatus: '二维码已过期，请刷新' }); return }
      if (this.data.busy) { this.scheduleQr(platform, epoch, sequence); return }
      try {
        const result = await this.api.checkPlatformQr(platform)
        if (!this.current(epoch) || sequence !== this.qrSequence) return
        this.setView({ qrStatus: result.message })
        if (result.status === 'success') { this.stopQr(); this.setView({ message: '音乐账号已连接' }); this.libraryLoaded = false; await this.refreshAccount(); return }
        if (result.status === 'expired') { this.stopQr(); this.setView({ qrStatus: result.message }); return }
        this.scheduleQr(platform, epoch, sequence)
      } catch (failure) { if (this.current(epoch) && sequence === this.qrSequence) { this.stopQr(); this.handleError(failure) } }
    }, 2500)
  },
  accountAction(event) {
    if (!this.requireAdmin()) return
    const action = event.currentTarget.dataset.action, platform = PLATFORMS[this.data.accountPlatform].id
    if (!['cookie', 'logout', 'refresh', 'signin', 'captcha', 'cellphone'].includes(action)) return
    if (action === 'cookie' && !this.accountSecrets.cookie?.trim()) { this.setView({ error: '请填写音乐平台 Cookie' }); return }
    if (['captcha', 'cellphone'].includes(action) && !/^\d{5,15}$/.test(this.accountSecrets.phone || '')) { this.setView({ error: '请填写有效手机号' }); return }
    if (action === 'cellphone' && !/^\d{4,8}$/.test(this.accountSecrets.captcha || '')) { this.setView({ error: '请填写验证码' }); return }
    const fields = action === 'cookie' ? { cookie: this.accountSecrets.cookie.trim() } : ['captcha', 'cellphone'].includes(action) ?
      { phone: this.accountSecrets.phone, captcha: this.accountSecrets.captcha || '', countrycode: this.accountSecrets.countrycode || '86' } : {}
    const operation = () => this.run(async epoch => {
      await this.api.account(platform, action, fields)
      if (!this.current(epoch) || !this.isAdmin()) return
      this.setView({ message: action === 'captcha' ? '验证码已发送' : '音乐账号操作已完成' }); this.libraryLoaded = false
      if (action !== 'captcha') { this.accountSecrets = {}; this.setView({ accountInputNonce: this.data.accountInputNonce + 1 }); await this.readAccount(epoch) }
    })
    if (['logout', 'cookie'].includes(action)) this.confirm(action === 'logout' ? '退出音乐账号' : '更新音乐账号', `确认${action === 'logout' ? '退出' : '更新'} ${PLATFORMS[this.data.accountPlatform].name} 的服务端登录状态？`, operation)
    else return operation()
  },
  async readUsers(epoch) { const body = await this.api.users(); if (this.current(epoch) && this.isAdmin()) this.setView({ users: userRows(body.users) }) },
  refreshUsers() { if (this.requireAdmin()) return this.run(epoch => this.readUsers(epoch)) },
  setCreateField(event) { if (!this.isAdmin()) return; const field = event.currentTarget.dataset.field;
    if (['createUsername', 'createScopes'].includes(field)) this.setView({ [field]: text(event.detail.value, field === 'createUsername' ? 32 : 4096) }) },
  chooseCreateRole(event) { const role = Number(event.detail.value); if (this.isAdmin() && [0, 1].includes(role)) this.setView({ createRole: role }) },
  editUser(event) {
    if (!this.isAdmin() || this.data.busy) return
    const id = Number(event.currentTarget.dataset.id), field = event.currentTarget.dataset.field
    const users = this.data.users.map(row => {
      if (row.id !== id) return row
      return field === 'role' ? { ...row, roleIndex: Number(event.detail.value) === 1 ? 1 : 0, role: Number(event.detail.value) === 1 ? 'admin' : 'user' } :
        field === 'enabled' ? { ...row, enabled: event.detail.value === true } : field === 'scopes' ? { ...row, scopes: text(event.detail.value, 4096) } : row
    }); this.setView({ users })
  },
  revealTemporary(body, username) {
    this.setView({ temporaryPassword: typeof body.temporary_password === 'string' ? body.temporary_password.slice(0, 128) : '', temporaryPasswordUser: username })
  },
  dismissTemporary() { this.setView({ temporaryPassword: '', temporaryPasswordUser: '' }) },
  createUser() {
    if (!this.requireAdmin()) return
    const data = { username: this.data.createUsername.trim(), role: this.data.createRole === 1 ? 'admin' : 'user', scopes: this.data.createScopes.trim() }
    if (!data.username || data.role === 'user' && !data.scopes) { this.setView({ error: '请填写用户名及普通用户的播放范围' }); return }
    return this.run(async epoch => {
      const body = await this.api.createUser(data)
      if (!this.current(epoch) || !this.isAdmin()) return
      this.revealTemporary(body, data.username); this.setView({ createUsername: '', createScopes: '', createRole: 0 }); await this.readUsers(epoch)
    })
  },
  userAction(event) {
    if (!this.requireAdmin() || this.data.busy) return
    const row = this.data.users.find(item => item.id === Number(event.currentTarget.dataset.id)), action = event.currentTarget.dataset.action
    if (!row || !['save', 'reset', 'remove'].includes(action)) return
    const payload = { role: row.role, enabled: row.enabled, scopes: row.scopes }
    this.confirm(({ save: '保存用户权限', reset: '重置用户密码', remove: '删除用户' })[action],
      action === 'remove' ? `永久删除 ${row.username}？` : action === 'reset' ? `重置 ${row.username} 的密码并注销其会话？` : `保存 ${row.username} 的角色、启用状态和播放范围？权限变化会使其旧会话失效。`,
      () => this.run(async epoch => {
        const body = action === 'save' ? await this.api.updateUser(row.id, payload) : action === 'reset' ? await this.api.resetUserPassword(row.id) : await this.api.removeUser(row.id)
        if (!this.current(epoch) || !this.isAdmin()) return
        if (row.id === Number(this.data.user.id)) {
          // A successful self change revokes the current session. Keep a self-reset
          // password visible once on the login screen instead of losing it to a 401 reload.
          this.api.forgetSession?.(); this.resetResources({ phase: 'login', user: null })
          if (action === 'reset') this.revealTemporary(body, row.username)
          else this.setView({ message: '当前账号已更新，请重新登录' })
          return
        }
        if (action === 'reset') this.revealTemporary(body, row.username)
        this.setView({ message: '用户操作已完成' }); await this.readUsers(epoch)
      }))
  },
  async readRuntime(epoch) {
    const body = await this.api.runtimeStatus()
    if (!this.current(epoch) || !this.isAdmin()) return
    this.setView({ runtime: runtimeView(body) })
    const system = await this.api.systemStatus()
    if (this.current(epoch) && this.isAdmin()) this.setView({ systemMetrics: [
      { label: 'CPU', value: `${Math.round(Number(system.system?.cpu_percent) || 0)}%` },
      { label: '内存', value: `${Math.round(Number(system.system?.memory?.percent) || 0)}%` },
      { label: '进程运行', value: `${Math.floor((Number(system.process?.uptime) || 0) / 60)} 分钟` },
    ] })
  },
  refreshRuntime() { if (this.requireAdmin()) return this.run(epoch => this.readRuntime(epoch)) },
  async readLogs(epoch) {
    const type = this.data.logType, body = await this.api.logs(type)
    if (this.current(epoch) && this.isAdmin() && type === this.data.logType) this.setView({ logsLoaded: true,
      logs: (Array.isArray(body.logs) ? body.logs : []).slice(-200).map((row, index) => ({ id: index, timestamp: text(row.timestamp, 80), level: ['error', 'warning', 'debug'].includes(row.level) ? row.level : 'info', message: safeMessage(row.message) })) })
  },
  refreshLogs() { if (this.requireAdmin()) return this.run(epoch => this.readLogs(epoch)) },
  chooseLogType(event) { const type = event.currentTarget.dataset.type; if (this.isAdmin() && !this.data.busy && ['app', 'debug'].includes(type)) { this.setView({ logType: type, logs: [], logsLoaded: false }); this.refreshLogs() } },
  clearLogs() { if (!this.requireAdmin()) return; const type = this.data.logType;
    this.confirm('清空服务端日志', `确认清空 ${type} 日志文件？`, () => this.run(async epoch => { await this.api.clearLogs(type); if (this.current(epoch)) await this.readLogs(epoch) })) },
}
module.exports = { DATA, methods, safeMessage, runtimeView, userRows }
