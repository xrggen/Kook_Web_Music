'use strict'

const { getKookClient } = require('../../services/kook-api')
const { DATA: MANAGEMENT_DATA, methods: management, safeMessage } = require('../../services/mobile-management')
const { layout } = require('../../utils/layout')
const { PLATFORMS, text, validId, duration, playlistRows, searchRows, extractPlaylistId, platformView, libraryRows, coverUrl } = require('../../utils/mobile-model')
const config = require('../../config')
const USERNAME_KEY = 'gen.kook.console.v1.username'
const PREFERENCES_KEY = 'gen.kook.console.v1.preferences'
const names = { join: '加入频道', leave: '离开频道', pause: '暂停', resume: '继续播放', skip: '下一首', stop: '停止播放',
  clear: '清空队列', remove: '移除歌曲', promote: '设为下一首', repeat: '切换列表循环', add: '添加歌曲', import: '导入歌单' }
const placeholders = kind => [{ id: '', name: `选择${kind}`, initial: '', icon: '' }]
function items(rows, kind) {
  return [...placeholders(kind), ...(Array.isArray(rows) ? rows : []).filter(row => row && validId(row.id)).slice(0, 500).map(row => ({
    id: text(row.id, 128), name: text(row.name, 160) || text(row.id), initial: (text(row.name) || '?').slice(0, 1).toUpperCase(), icon: coverUrl(row.icon, '') }))]
}
Page({
  data: { ...layout(), ...MANAGEMENT_DATA, uiRevision: 'mobile-port-v3-icons-brand', phase: 'login', username: '', user: null, busy: false, error: '', message: '', passwordInput: '',
    themeMode: 'light', resolvedTheme: 'light', compact: false, reducedMotion: false, keyboardOpen: false, keyboardHeight: 0,
    queueCount: 0, userCount: 0, songCount: 0, logCount: 0, guildCount: 1, channelCount: 1, wechatBound: null, authAction: '',
    tab: 'play', sheet: '', platforms: PLATFORMS, guilds: placeholders('服务器'), channels: placeholders('语音频道'), guildIndex: 0, channelIndex: 0,
    hasTarget: false, targetLabel: '选择播放目标', guildName: '选择 KOOK 服务器', channelName: '选择语音频道',
    connected: false, playbackState: 'idle', stateLabel: '尚未选择频道', currentSong: '未播放', currentArtist: '等待添加歌曲', queue: [],
    positionText: '00:00', durationText: '00:00', progressPercent: 0, isPlaying: false,
    platformLabels: PLATFORMS.map(row => row.name), platform: 0, keyword: '', playlistId: '', importName: '', songs: [], searchDone: false, repeat: false,
    libraryFilter: 'all', libraryPlatforms: PLATFORMS.map(row => ({ ...row, connected: false, label: '未读取', accountName: row.fullName })),
    libraryRows: [], libraryCount: 0, librarySummary: '汇总三个平台的歌单与收藏夹', libraryLoaded: false, serviceUrl: config.apiBaseUrl },
  ...management,
  setView(patch) {
    const fields = { queue: 'queueCount', users: 'userCount', songs: 'songCount', logs: 'logCount', guilds: 'guildCount', channels: 'channelCount', libraryRows: 'libraryCount' }
    const view = { ...patch }
    for (const [field, count] of Object.entries(fields)) if (Array.isArray(view[field])) view[count] = view[field].length
    this.setData(view)
  },
  onLoad() {
    this.api = getKookClient(wx); this.epoch = 0; this.disposed = false; this.foreground = true; this.passwords = {}; this.accountSecrets = {}; this.libraryItems = []
    try { const username = wx.getStorageSync(USERNAME_KEY); if (typeof username === 'string') this.setView({ username: username.slice(0, 128) }) } catch {}
    let preferences = {}
    try { preferences = wx.getStorageSync(PREFERENCES_KEY) || {} } catch {}
    this.setView({ ...layout(wx), themeMode: ['light', 'dark', 'system'].includes(preferences.theme) ? preferences.theme : 'light',
      compact: preferences.compact === true, reducedMotion: preferences.reducedMotion === true })
    this.applyTheme()
    this.keyboardHandler = event => this.keyboardHeight(event)
    this.themeHandler = () => { if (!this.disposed && this.data.themeMode === 'system') this.applyTheme() }
    wx.onKeyboardHeightChange?.(this.keyboardHandler); wx.onThemeChange?.(this.themeHandler)
  },
  onShow() {
    this.foreground = true; this.epoch++; this.setView({ ...layout(wx), busy: false, authAction: '', keyboardOpen: false, keyboardHeight: 0 }); this.clearPoll(); this.applyTheme()
    if (this.api?.hasSession()) return this.run(async epoch => {
      const previous = this.data.user, preserve = this.context(), user = await this.api.session()
      if (!this.current(epoch)) return
      const same = this.data.phase === 'console' && previous?.id === user.id && previous?.username === user.username && previous?.role === user.role && !user.must_change_password
      if (same) this.setView({ user }); else this.setUser(user)
      if (!user.must_change_password) {
        await this.loadGuilds({ preserve: same ? preserve : null })
        if (!this.current(epoch)) return
        if (this.data.tab === 'account') await this.readAccount(epoch)
        else if (this.data.tab === 'users') await this.readUsers(epoch)
        else if (this.data.tab === 'status') await this.readRuntime(epoch)
        else if (this.data.tab === 'library') await this.readLibrary(epoch)
      }
    })
  },
  onHide() {
    this.foreground = false; this.epoch++; this.clearPoll(); this.stopQr(); this.api?.abortAll(); this.passwords = {}; this.accountSecrets = {}
    this.setView({ passwordInput: '', temporaryPassword: '', temporaryPasswordUser: '', sheet: '', wechatBound: null, authAction: '', keyboardOpen: false, keyboardHeight: 0,
      accountInputNonce: this.data.accountInputNonce + 1 })
  },
  onUnload() { this.onHide(); this.disposed = true; wx.offKeyboardHeightChange?.(this.keyboardHandler); wx.offThemeChange?.(this.themeHandler) },
  onResize() { this.setView(layout(wx)) },
  current(epoch) { return !this.disposed && this.foreground && epoch === this.epoch },
  delay(callback, milliseconds) { return setTimeout(callback, milliseconds) },
  cancelDelay(timer) { clearTimeout(timer) },
  applyTheme() {
    let system = 'light'
    try { system = wx.getAppBaseInfo?.().theme || wx.getSystemInfoSync?.().theme || 'light' } catch {}
    const resolvedTheme = this.data.themeMode === 'system' ? system === 'dark' ? 'dark' : 'light' : this.data.themeMode
    this.setView({ resolvedTheme })
    wx.setNavigationBarColor?.({ frontColor: resolvedTheme === 'dark' ? '#ffffff' : '#000000', backgroundColor: resolvedTheme === 'dark' ? '#0d0f12' : '#f4f6fa' })
  },
  savePreferences() {
    this.applyTheme()
    try { wx.setStorageSync(PREFERENCES_KEY, { theme: this.data.themeMode, compact: this.data.compact, reducedMotion: this.data.reducedMotion }) }
    catch { this.setView({ error: '界面偏好暂无法保存，重启后将恢复默认浅色' }) }
  },
  chooseTheme(event) { const theme = event.currentTarget.dataset.theme; if (this.isAdmin() && ['light', 'dark', 'system'].includes(theme)) { this.setView({ themeMode: theme }); this.savePreferences() } },
  setPreference(event) { const field = event.currentTarget.dataset.field; if (this.isAdmin() && ['compact', 'reducedMotion'].includes(field)) { this.setView({ [field]: event.detail.value === true }); this.savePreferences() } },
  resetPreferences() { if (!this.requireAdmin()) return; this.setView({ themeMode: 'light', compact: false, reducedMotion: false }); this.savePreferences(); this.setView({ message: '已恢复默认浅色和舒适布局' }) },
  keyboardHeight(event) {
    if (this.disposed || !this.foreground) return
    const height = Math.max(0, Math.min(this.data.windowHeight - 80, Number(event.height ?? event.detail?.height) || 0))
    this.setView({ keyboardHeight: height, keyboardOpen: height > 0 })
  },
  keyboardFocus() { if (!this.disposed) this.setView({ keyboardOpen: true }) },
  keyboardBlur() { if (!this.disposed) this.setView({ keyboardOpen: false, keyboardHeight: 0 }) },
  clearPoll() { if (this.pollTimer != null) clearTimeout(this.pollTimer); this.pollTimer = null },
  schedulePoll() {
    this.clearPoll()
    if (!this.foreground || this.disposed || this.data.phase !== 'console' || !this.context() && !(this.isAdmin() && this.data.tab === 'status')) return
    const epoch = this.epoch
    this.pollTimer = setTimeout(async () => {
      this.pollTimer = null
      if (!this.current(epoch)) return
      if (!this.data.busy) {
        try { if (this.data.tab === 'status' && this.isAdmin()) await this.readRuntime(epoch); else await this.readState() }
        catch (failure) { if (this.current(epoch)) this.handleError(failure) }
      }
      if (this.current(epoch)) this.schedulePoll()
    }, config.pollIntervalMs)
  },
  async run(fn) {
    if (this.data.busy || this.disposed || !this.foreground) return
    const epoch = this.epoch; this.clearPoll(); this.setView({ busy: true, error: '', message: '' })
    try { await fn(epoch) } catch (failure) { if (this.current(epoch)) this.handleError(failure) }
    finally { if (this.current(epoch)) { this.setView({ busy: false }); this.schedulePoll() } }
  },
  confirm(title, content, action) {
    if (this.data.busy || this.confirming || this.disposed) return
    this.confirming = true; const epoch = this.epoch
    wx.showModal({ title, content, success: result => { if (result.confirm && this.current(epoch)) action() }, complete: () => { this.confirming = false } })
  },
  handleError(failure) {
    if (!this.foreground || this.disposed || failure?.code === 'CANCELLED') return
    if (['UNAUTHORIZED', 'INVALID_SESSION'].includes(failure?.code)) { this.clearPoll(); this.resetResources({ phase: 'login', user: null }) }
    if (failure?.code === 'PASSWORD_REQUIRED') { this.clearPoll(); this.passwords = {}; this.resetResources({ phase: 'password', user: { ...this.data.user, must_change_password: true } }) }
    this.setView({ error: safeMessage(failure?.message || '操作未完成，请刷新状态').slice(0, 220) })
  },
  resetResources(extra = {}) {
    this.stateSequence = (this.stateSequence || 0) + 1; this.searchSequence = (this.searchSequence || 0) + 1; this.librarySequence = (this.librarySequence || 0) + 1
    this.libraryItems = []; this.libraryLoaded = false; this.clearManagement()
    this.setView({ guilds: placeholders('服务器'), channels: placeholders('语音频道'), guildIndex: 0, channelIndex: 0, tab: 'play', sheet: '', wechatBound: null,
      queue: [], songs: [], connected: false, isPlaying: false, playbackState: 'idle', currentSong: '未播放', currentArtist: '等待添加歌曲', stateLabel: '请选择服务器和频道',
      repeat: false, platform: 0, keyword: '', playlistId: '', importName: '', searchDone: false, positionText: '00:00', durationText: '00:00', progressPercent: 0,
      libraryRows: [], libraryCount: 0, libraryLoaded: false, librarySummary: '汇总三个平台的歌单与收藏夹',
      libraryPlatforms: PLATFORMS.map(row => ({ ...row, connected: false, label: '未读取', accountName: row.fullName })), ...extra })
    this.refreshContext()
  },
  setUser(user) { this.resetResources({ user, phase: user.must_change_password ? 'password' : 'console', passwordInput: '' }); this.passwords = {} },
  setUsername(event) { this.setView({ username: String(event.detail.value || '').slice(0, 128) }) },
  setPassword(event) { const name = event.currentTarget.dataset.field; if (['login', 'current', 'next', 'confirm'].includes(name)) this.passwords[name] = String(event.detail.value || '').slice(0, 512) },
  login() {
    if (this.data.phase !== 'login') return
    const username = this.data.username.trim(), password = this.passwords.login || ''
    if (!username || !password) { this.setView({ error: '请输入用户名和密码' }); return }
    return this.runLogin('password', () => this.api.login(username, password))
  },
  loginWithWechat() {
    if (this.data.phase !== 'login') return
    return this.runLogin('wechat', () => this.api.loginWithWechat())
  },
  runLogin(authAction, authenticate) {
    return this.run(async epoch => {
      this.setView({ authAction })
      if (authAction === 'wechat') {
        this.passwords = {}; this.setView({ passwordInput: '', keyboardOpen: false, keyboardHeight: 0 }); wx.hideKeyboard?.()
      }
      try {
        const user = await authenticate()
        if (!this.current(epoch)) return
        try { wx.setStorageSync(USERNAME_KEY, user.username) } catch {}
        this.setView({ username: user.username })
        this.setUser(user); if (!user.must_change_password) await this.loadGuilds()
      } finally { if (this.current(epoch)) this.setView({ authAction: '' }) }
    })
  },
  openWechatBinding() {
    if (this.data.phase !== 'console' || !this.data.user || this.data.user.must_change_password || this.data.busy) return
    this.setView({ sheet: 'wechat', keyboardOpen: false, keyboardHeight: 0, wechatBound: null })
    return this.refreshWechatBinding()
  },
  refreshWechatBinding() {
    if (this.data.sheet !== 'wechat') return
    return this.run(async epoch => {
      this.setView({ wechatBound: null })
      const bound = await this.api.wechatBindingStatus()
      if (this.current(epoch) && this.data.sheet === 'wechat') this.setView({ wechatBound: bound })
    })
  },
  requestBindWechat() {
    if (this.data.sheet !== 'wechat' || !this.data.user || this.data.wechatBound !== false) return
    this.confirm('绑定微信', `将当前微信与控制台账号 ${this.data.user.username} 绑定？绑定后可在登录页使用微信免密登录。`, () => this.updateWechatBinding(true))
  },
  requestUnbindWechat() {
    if (this.data.sheet !== 'wechat' || this.data.wechatBound !== true) return
    this.confirm('解除微信绑定', '解除绑定后，此微信不能再免密登录该账号。你仍可使用账号密码登录。', () => this.updateWechatBinding(false))
  },
  updateWechatBinding(bind) {
    if (this.data.sheet !== 'wechat' || !this.data.user || this.data.user.must_change_password || this.data.wechatBound !== !bind) return
    return this.run(async epoch => {
      this.setView({ wechatBound: null, authAction: 'binding' })
      try {
        const bound = await (bind ? this.api.bindWechat() : this.api.unbindWechat())
        if (!this.current(epoch) || this.data.sheet !== 'wechat') return
        if (bound !== bind) throw new Error('微信绑定操作未确认，请刷新绑定状态')
        this.setView({ wechatBound: bound, message: bound ? '微信已绑定' : '微信绑定已解除' })
      } finally { if (this.current(epoch)) this.setView({ authAction: '' }) }
    })
  },
  openSecurity() { if (this.data.busy || this.data.phase !== 'console') return; this.clearPoll(); this.stopQr(); this.passwords = {}; this.setView({ phase: 'password', sheet: '', error: '', message: '', passwordInput: '' }) },
  cancelSecurity() { if (this.data.busy || !this.data.user || this.data.user.must_change_password) return; this.passwords = {}; this.setView({ phase: 'console', passwordInput: '' }); this.schedulePoll() },
  changePassword() {
    const { current, next, confirm } = this.passwords
    if (!current || !next || next !== confirm) { this.setView({ error: '请填写当前密码和一致的新密码' }); return }
    if (next.length < 8 || next.length > 128 || !/[a-z]/.test(next) || !/[A-Z]/.test(next) || !/[^A-Za-z0-9]/.test(next)) { this.setView({ error: '新密码需8–128位，包含大写、小写字母和特殊字符' }); return }
    return this.run(async epoch => { const user = await this.api.changePassword(current, next, confirm); if (this.current(epoch)) { this.setUser(user); await this.loadGuilds() } })
  },
  logout() { return this.run(async epoch => { try { await this.api.logout() } finally { if (this.current(epoch)) { this.passwords = {}; this.clearPoll(); this.resetResources({ phase: 'login', user: null, passwordInput: '' }) } } }) },
  requestLogout() { this.confirm('退出登录', '退出当前控制台？退出会保留微信绑定，也不会停止正在播放的频道。', () => this.logout()) },
  refreshContext() {
    const guild = this.data.guilds[this.data.guildIndex], channel = this.data.channels[this.data.channelIndex], target = Boolean(guild?.id && channel?.id)
    this.setView({ hasTarget: target, guildName: guild?.id ? guild.name : '选择 KOOK 服务器', channelName: channel?.id ? channel.name : '选择语音频道',
      targetLabel: target ? `${guild.name} · ${channel.name}` : '选择播放目标' })
  },
  clearPlayback() { this.setView({ queue: [], connected: false, isPlaying: false, playbackState: 'idle', currentSong: '未播放', currentArtist: '等待添加歌曲',
    positionText: '00:00', durationText: '00:00', progressPercent: 0, repeat: false }) },
  async loadGuilds({ preserve = null } = {}) {
    this.stateSequence = (this.stateSequence || 0) + 1
    const epoch = this.epoch, response = await this.api.guilds()
    if (!this.current(epoch)) return
    const guilds = items(response.guilds, '服务器'), guildIndex = Math.max(0, guilds.findIndex(row => row.id === preserve?.guild_id))
    this.clearPlayback(); this.setView({ guilds, guildIndex, channels: placeholders('语音频道'), channelIndex: 0,
      stateLabel: response.edge_stale ? '执行节点离线，显示缓存列表' : '请选择服务器和频道' }); this.refreshContext()
    if (guildIndex && preserve?.channel_id) {
      const result = await this.api.channels(guilds[guildIndex].id)
      if (!this.current(epoch)) return
      const channels = items(result.channels, '语音频道'), channelIndex = Math.max(0, channels.findIndex(row => row.id === preserve.channel_id))
      this.setView({ channels, channelIndex }); this.refreshContext(); if (channelIndex) await this.readState()
    }
  },
  refreshGuilds() { return this.run(() => this.loadGuilds({ preserve: this.context() })) },
  contextIconError(event) {
    if (this.disposed || !this.foreground) return
    const { kind, id, src } = event.currentTarget.dataset
    if (!['guilds', 'channels'].includes(kind) || !validId(id) || typeof src !== 'string' || !src) return
    // Match the failed image itself: an old callback must not clear a refreshed avatar.
    if (!this.data[kind].some(row => row.id === id && row.icon === src)) return
    this.setView({ [kind]: this.data[kind].map(row => row.id === id && row.icon === src ? { ...row, icon: '' } : row) })
  },
  chooseGuild(event) {
    if (this.data.busy) return
    const index = Number(event.detail?.value ?? event.currentTarget?.dataset?.index), guild = this.data.guilds[index]
    if (!guild) return
    this.stateSequence = (this.stateSequence || 0) + 1; this.clearPlayback()
    this.setView({ guildIndex: index, channels: placeholders('语音频道'), channelIndex: 0, sheet: '' }); this.refreshContext()
    if (!guild.id) return
    return this.run(async epoch => { const response = await this.api.channels(guild.id);
      if (this.current(epoch) && this.data.guilds[this.data.guildIndex]?.id === guild.id) { this.setView({ channels: items(response.channels, '语音频道') }); this.refreshContext() } })
  },
  chooseChannel(event) {
    if (this.data.busy) return
    const index = Number(event.detail?.value ?? event.currentTarget?.dataset?.index)
    if (!this.data.channels[index]) return
    this.stateSequence = (this.stateSequence || 0) + 1; this.clearPlayback(); this.setView({ channelIndex: index, sheet: '' }); this.refreshContext()
    if (this.context()) return this.refreshState()
  },
  context() { const guild = this.data.guilds[this.data.guildIndex], channel = this.data.channels[this.data.channelIndex]; return guild?.id && channel?.id ? { guild_id: guild.id, channel_id: channel.id } : null },
  async readState() {
    const ctx = this.context(); if (!ctx) return
    const epoch = this.epoch, sequence = this.stateSequence = (this.stateSequence || 0) + 1
    const [active, playlist] = await Promise.all([this.api.active(ctx.guild_id), this.api.playlist(ctx)])
    if (!this.current(epoch) || sequence !== this.stateSequence || this.context()?.channel_id !== ctx.channel_id || this.context()?.guild_id !== ctx.guild_id) return
    const rows = playlistRows(playlist.playlist), current = rows.find(row => row.playing), status = active.active?.[ctx.channel_id]
    this.setView({ connected: Boolean(status), playbackState: status || 'idle', isPlaying: Boolean(current) && status !== 'paused',
      stateLabel: active.edge_stale || playlist.edge_stale ? '执行节点离线，缓存状态不可用于确认操作' : ({ playing: '正在播放', paused: '已暂停', connected: '已加入频道', idle: '频道空闲' })[status] || '未加入频道',
      currentSong: current?.name || '未播放', currentArtist: current?.artist || '等待添加歌曲', queue: rows.filter(row => !row.playing).map((row, index) => ({ ...row, number: String(index + 1).padStart(2, '0') })),
      repeat: playlist.playback_modes?.playlist_repeat === true, positionText: duration(current?.position), durationText: duration(current?.duration),
      progressPercent: current?.duration > 0 ? Math.min(100, current.position / current.duration * 100) : 0 })
  },
  refreshState() { return this.run(() => this.readState()) },
  command(action, fields = {}) {
    const ctx = this.context()
    if (!ctx) { this.setView({ error: '请先选择服务器和语音频道' }); return }
    return this.run(async epoch => {
      this.stateSequence = (this.stateSequence || 0) + 1
      await this.api.command(action, ctx, fields)
      if (this.current(epoch)) { this.setView({ message: `${names[action] || '操作'}已完成` }); await this.readState() }
    })
  },
  action(event) {
    const action = event.currentTarget.dataset.action
    if (!['join', 'leave', 'pause', 'resume', 'skip', 'stop', 'clear', 'repeat'].includes(action) || this.data.busy) return
    if (['leave', 'stop', 'clear'].includes(action)) { const ctx = this.context(); this.confirm(names[action], `确认对 ${this.data.channelName} 执行“${names[action]}”？`,
      () => { if (JSON.stringify(ctx) === JSON.stringify(this.context())) this.command(action) }) }
    else return this.command(action)
  },
  togglePlayback() { return this.command(this.data.playbackState === 'paused' ? 'resume' : this.data.isPlaying ? 'pause' : 'resume') },
  queueAction(event) {
    const action = event.currentTarget.dataset.action, row = this.data.queue[Number(event.currentTarget.dataset.row)]
    if (!['remove', 'promote'].includes(action) || !row || row.queueIndex == null || this.data.busy) return
    const ctx = this.context(), sequence = this.stateSequence
    this.confirm(names[action], row.name, () => {
      if (JSON.stringify(ctx) === JSON.stringify(this.context()) && sequence === this.stateSequence) this.command(action, { index: row.queueIndex })
      else this.setView({ error: '队列已更新，请重新选择歌曲' })
    })
  },
  chooseTab(event) {
    const requested = event.currentTarget.dataset.tab, tab = ['control', 'search'].includes(requested) ? 'play' : requested
    if (this.data.phase !== 'console' || this.data.busy) return
    if (tab === 'more') { this.openSheet({ currentTarget: { dataset: { sheet: 'more' } } }); return }
    if (!['play', 'library', 'account', 'status', 'users', 'settings', 'help'].includes(tab) || ['account', 'status', 'users', 'settings'].includes(tab) && !this.requireAdmin()) return
    this.stopQr(); this.accountSecrets = {}; this.dismissTemporary(); this.setView({ tab, sheet: '', error: '', message: '', keyboardOpen: false, keyboardHeight: 0 }); this.schedulePoll()
    if (tab === 'library') return this.refreshLibrary()
    if (tab === 'account') return this.refreshAccount()
    if (tab === 'status') return this.refreshRuntime()
    if (tab === 'users') return this.refreshUsers()
  },
  openSheet(event) {
    const sheet = event.currentTarget.dataset.sheet
    if (!['guilds', 'channels', 'queue', 'player', 'import', 'more'].includes(sheet) || this.data.phase !== 'console') return
    if (['queue', 'player', 'import'].includes(sheet) && !this.context()) { this.setView({ error: '请先选择服务器和语音频道' }); return }
    this.setView({ sheet, keyboardOpen: false, keyboardHeight: 0 })
  },
  closeSheet() {
    if (this.data.sheet === 'wechat' && this.data.busy && this.data.authAction === 'binding') return
    this.setView({ sheet: '', wechatBound: null, keyboardOpen: false, keyboardHeight: 0 }); wx.hideKeyboard?.()
  },
  stopTouch() {},
  sheetTouchStart(event) { this.sheetTouch = event.touches?.[0] ? { x: event.touches[0].clientX, y: event.touches[0].clientY } : null },
  sheetTouchEnd(event) { const end = event.changedTouches?.[0], start = this.sheetTouch; this.sheetTouch = null;
    if (start && end && end.clientY - start.y > 72 && end.clientY - start.y > Math.abs(end.clientX - start.x) * 1.25) this.closeSheet() },
  choosePlatform(event) {
    const index = Number(event.detail?.value ?? event.currentTarget?.dataset?.index)
    if (PLATFORMS[index] && !this.data.busy) { this.searchSequence = (this.searchSequence || 0) + 1; this.setView({ platform: index, songs: [], searchDone: false,
      ...(index !== this.data.platform && this.data.importName ? { playlistId: '', importName: '' } : {}) }) }
  },
  setKeyword(event) { this.setView({ keyword: String(event.detail.value || '').slice(0, 128) }) },
  setPlaylist(event) { this.setView({ playlistId: String(event.detail.value || '').slice(0, 1024), importName: '' }) },
  search() {
    const platform = PLATFORMS[this.data.platform].id, keyword = this.data.keyword.trim(), sequence = this.searchSequence = (this.searchSequence || 0) + 1
    if (!keyword) { this.setView({ error: '请输入歌曲、歌手或 BV 号' }); return }
    return this.run(async epoch => {
      const result = await this.api.search(keyword, platform)
      if (this.current(epoch) && sequence === this.searchSequence && PLATFORMS[this.data.platform].id === platform && this.data.keyword.trim() === keyword)
        this.setView({ songs: searchRows(result.songs, platform), searchDone: true })
    })
  },
  addSong(event) { const song = this.data.songs[Number(event.currentTarget.dataset.row)]; if (song) return this.command('add', { song_id: song.id, song_name: song.name, artist_name: song.artist, platform: song.platform }) },
  importPlaylist() {
    const platform = PLATFORMS[this.data.platform].id, id = extractPlaylistId(this.data.playlistId, platform)
    if (!id) { this.setView({ error: '请填写有效的歌单／收藏夹 ID 或链接' }); return }
    return this.command('import', { playlist_id: id, platform })
  },
  async readLibrary(epoch) {
    const sequence = this.librarySequence = (this.librarySequence || 0) + 1
    const results = await Promise.allSettled(PLATFORMS.map(async meta => {
      const status = await this.api.platformStatus(meta.id), account = platformView(meta.id, status)
      if (!this.current(epoch) || sequence !== this.librarySequence) throw Object.assign(new Error('请求已取消'), { code: 'CANCELLED' })
      if (!account.connected) return { account, rows: [] }
      const payload = await this.api.platformPlaylists(meta.id, account.uid)
      return { account, rows: libraryRows(meta.id, payload, account) }
    }))
    const authFailure = results.find(result => result.status === 'rejected' && ['UNAUTHORIZED', 'PASSWORD_REQUIRED'].includes(result.reason?.code))
    if (authFailure) throw authFailure.reason
    if (!this.current(epoch) || sequence !== this.librarySequence) return
    const platforms = results.map((result, index) => result.status === 'fulfilled' ? result.value.account :
      { ...PLATFORMS[index], connected: false, accountName: PLATFORMS[index].fullName, label: '读取失败', error: safeMessage(result.reason?.message || '服务暂不可用') })
    this.libraryItems = results.flatMap(result => result.status === 'fulfilled' ? result.value.rows : [])
    this.libraryLoaded = true
    const connected = platforms.filter(row => row.connected).length
    this.setView({ libraryPlatforms: platforms, libraryLoaded: true, librarySummary: connected ? `已连接 ${connected}/3 个平台，共 ${this.libraryItems.length} 个歌单或收藏夹` : '尚未检测到已连接的音乐账号' })
    this.filterLibrary()
  },
  refreshLibrary() { return this.run(epoch => this.readLibrary(epoch)) },
  filterLibrary() { const rows = this.libraryItems.filter(row => this.data.libraryFilter === 'all' || row.platform === this.data.libraryFilter); this.setView({ libraryRows: rows, libraryCount: rows.length }) },
  chooseLibraryFilter(event) { const filter = event.currentTarget.dataset.platform; if (['all', ...PLATFORMS.map(row => row.id)].includes(filter)) { this.setView({ libraryFilter: filter }); this.filterLibrary() } },
  libraryIntent(event) {
    const item = this.libraryItems.find(row => row.key === event.currentTarget.dataset.key)
    if (!item || this.data.busy) return
    this.setView({ tab: 'play', platform: PLATFORMS.findIndex(meta => meta.id === item.platform), playlistId: item.id, importName: item.name, songs: [], searchDone: false,
      sheet: this.context() ? 'import' : '', message: this.context() ? '已带入播放页，确认后再导入' : '已选择歌单，请先选择播放频道，再打开导入歌单' })
  },
  copySource(event) { const item = this.libraryItems.find(row => row.key === event.currentTarget.dataset.key); if (item) wx.setClipboardData({ data: item.sourceUrl }) },
  coverError(event) {
    const key = event.currentTarget.dataset.key
    this.libraryItems = this.libraryItems.map(row => row.key === key ? { ...row, cover: '' } : row); this.filterLibrary()
  },
  dismissNotice() { this.setView({ error: '', message: '' }) },
  back() { this.onHide(); wx.navigateBack({ delta: 1, fail: () => wx.switchTab({ url: '/pages/home/home' }) }) },
  copyServiceUrl() { wx.setClipboardData({ data: config.apiBaseUrl }) },
})
