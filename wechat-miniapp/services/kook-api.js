'use strict'

const config = require('../config')
const clients = new WeakMap()
const ACTIONS = Object.freeze({ join: '/api/join', leave: '/api/leave', pause: '/api/pause', resume: '/api/resume',
  skip: '/api/skip', stop: '/api/stop', clear: '/api/clear', remove: '/api/remove', promote: '/api/playlist/promote',
  repeat: '/api/playlist/repeat', seek: '/api/seek', add: '/api/playlist/add', import: '/api/playlist' })
const PLATFORM_PATHS = Object.freeze({ wy: '/api/account', qq: '/api/qq/account', bili: '/api/bili/account' })
const WECHAT_AUTH = '/api/auth/wechat/'
const ACCOUNT_ACTIONS = Object.freeze({ profile: ['GET', '/profile'], detail: ['GET', '/detail'], level: ['GET', '/level'], subcount: ['GET', '/subcount'],
  cookie: ['POST', '/cookie'], logout: ['POST', '/logout'], refresh: ['POST', '/refresh'], signin: ['POST', '/signin'],
  captcha: ['POST', '/cellphone/captcha'], verify: ['POST', '/cellphone/verify'], cellphone: ['POST', '/cellphone/login'] })
const validId = value => typeof value === 'string' && /^[A-Za-z0-9_.:-]{1,128}$/.test(value)
const userView = value => value && typeof value.username === 'string' && ['admin', 'user'].includes(value.role)
  ? { id: value.id, username: value.username.slice(0, 128), role: value.role, must_change_password: value.must_change_password === true } : null
function error(message, code) { return Object.assign(new Error(message), { code }) }

function createKookClient(wxApi) {
  let sessionCookie = '', csrf = '', user = null, generation = 0
  const active = new Set(), qrSessions = new Map()
  let qrGeneration = 0
  function clear() { sessionCookie = ''; csrf = ''; user = null; qrSessions.clear() }
  function captureCookies(result) {
    const headers = result.header || {}
    const raw = Object.entries(headers).find(([name]) => name.toLowerCase() === 'set-cookie')?.[1] || ''
    const cookies = Array.isArray(result.cookies) && result.cookies.length ? result.cookies :
      (Array.isArray(raw) ? raw : String(raw).split(/,(?=\s*kook_(?:session|csrf)=)/))
    for (const cookie of cookies) {
      const match = String(cookie).match(/^\s*(kook_session|kook_csrf)=([^;]*)/)
      if (!match) continue
      if (match[2] && !/^[A-Za-z0-9_-]{20,256}$/.test(match[2])) throw error('服务返回无效会话', 'INVALID_SESSION')
      if (match[1] === 'kook_session') sessionCookie = match[2]
      else csrf = match[2]
    }
  }
  function request(path, { method = 'GET', data, publicLogin = false, platformResponse = false, acceptedCodes = [200], neteaseStatus = false, debugResponse = false } = {}) {
    if (!path.startsWith('/') || path.startsWith('//') || /[\r\n]/.test(path)) return Promise.reject(error('无效请求路径', 'BAD_REQUEST'))
    const wechatAuth = path.startsWith(WECHAT_AUTH)
    const epoch = generation
    return new Promise((resolve, reject) => {
      let task, done = false
      const finish = (fn, value) => { if (done) return; done = true; active.delete(task); fn(value) }
      const header = { 'content-type': 'application/json', Accept: 'application/json', 'X-Client-Class': 'wechat' }
      if (!publicLogin && sessionCookie && csrf) {
        header.Cookie = `kook_session=${sessionCookie}; kook_csrf=${csrf}`
        if (method !== 'GET') header['X-CSRF-Token'] = csrf
      }
      try {
        task = wxApi.request({ url: config.apiBaseUrl + path, method, data, header, timeout: config.requestTimeoutMs,
          success: result => {
            if (done) return
            if (epoch !== generation) { finish(reject, error('请求已取消', 'CANCELLED')); return }
            let body = result.data
            try { if (typeof body === 'string') body = JSON.parse(body) } catch { body = null }
            if (wechatAuth && result.statusCode === 401 && body?.code === 'WECHAT_CODE_INVALID') {
              finish(reject, error('微信登录凭证无效或已过期，请重新操作', 'WECHAT_CODE_INVALID')); return
            }
            if (result.statusCode === 401 && wechatAuth) {
              clear()
              finish(reject, error(publicLogin ? '当前微信无法免密登录，请用账号密码登录后检查绑定' : '会话已过期，请重新登录', 'UNAUTHORIZED')); return
            }
            if (!body || typeof body !== 'object' || Array.isArray(body)) {
              if (wechatAuth) { finish(reject, error('微信登录暂不可用，仍可使用账号密码登录', 'BACKEND_UPDATE_REQUIRED')); return }
              finish(reject, error(publicLogin ? 'KOOK 后端需部署小程序登录兼容更新' : '服务返回非JSON响应，请检查后端版本', 'BACKEND_UPDATE_REQUIRED')); return
            }
            if (result.statusCode === 401) { clear(); finish(reject, error(publicLogin ? '用户名或密码错误' : '会话已过期，请重新登录', 'UNAUTHORIZED')); return }
            // NetEase /login/status wraps its code/account/profile in data. Only the
            // fixed status route accepts that envelope; auth and writes remain strict.
            const responseCode = neteaseStatus ? body.code ?? body.data?.code : body.code
            const nestedStatusOk = !neteaseStatus || body.data?.code == null || acceptedCodes.includes(Number(body.data.code))
            const accepted = debugResponse ? body.status === 'success' : platformResponse ? body.success !== false && nestedStatusOk &&
              (acceptedCodes.includes(Number(responseCode)) || !neteaseStatus && body.success === true) : body.success === true
            if (result.statusCode < 200 || result.statusCode >= 300 || !accepted) {
              const code = result.statusCode === 428 ? 'PASSWORD_REQUIRED' : result.statusCode === 403 ? 'FORBIDDEN' :
                result.statusCode === 429 ? 'RATE_LIMITED' : responseCode || 'SERVICE_ERROR'
              if (wechatAuth) {
                const message = ({ 400: '微信登录凭证无效或已过期，请重新操作', 403: '无法完成此操作，请检查账号状态', 404: '微信登录暂不可用，仍可使用账号密码登录',
                  409: '该微信或控制台账号已有绑定，请先解除原绑定', 428: '请先使用账号密码登录并修改临时密码', 429: '操作过于频繁，请稍后再试',
                  502: '微信服务暂不可用，仍可使用账号密码登录', 503: '微信登录暂不可用，仍可使用账号密码登录' })[result.statusCode] ||
                  '微信操作未确认，请稍后查看绑定状态或使用账号密码登录'
                finish(reject, error(message, publicLogin && code === 'PASSWORD_REQUIRED' ? 'WECHAT_LOGIN_UNAVAILABLE' : code)); return
              }
              finish(reject, error(String(body.error || body.message || '操作失败，请刷新状态确认').slice(0, 200), code)); return
            }
            try { captureCookies(result) } catch (failure) { clear(); finish(reject, failure); return }
            finish(resolve, body)
          },
          fail: () => finish(reject, error(epoch !== generation ? '请求已取消' : wechatAuth ?
            (method === 'GET' ? '暂时无法读取微信绑定状态' : publicLogin ? '微信免密登录暂不可用，请检查网络或使用账号密码登录' : '微信绑定操作结果未确认，请刷新绑定状态') :
            publicLogin ? '无法完成登录，请检查网络与合法域名' :
            path === '/change-password' ? '密码修改结果未确认，请重新登录确认，不要重复提交' : path === '/logout' ? '服务端注销未确认，本机会话已清除' :
              method === 'GET' ? '无法连接 KOOK 服务，请检查网络与 request 合法域名' :
                '操作结果暂未确认，请刷新频道状态；不要连续重试', epoch !== generation ? 'CANCELLED' : 'NETWORK_ERROR')) })
        if (!done && task) active.add(task)
      } catch { finish(reject, error('网络请求未能发起', 'NETWORK_ERROR')) }
    })
  }
  function acceptLogin(body) {
    const view = userView(body.user)
    if (body.clientProtocol !== config.protocol || !view || !sessionCookie || !csrf || body.csrfToken !== csrf) {
      clear(); throw error('KOOK 服务登录协议不匹配，请更新后端', 'BACKEND_UPDATE_REQUIRED')
    }
    user = view
    return { ...view }
  }
  async function requestWithWechatCode(path, { publicLogin = false, data = {} } = {}) {
    const epoch = generation
    const code = await new Promise((resolve, reject) => {
      const unavailable = () => reject(error('未能获取微信登录凭证，请重试或使用账号密码登录', 'WECHAT_CODE_UNAVAILABLE'))
      try {
        if (typeof wxApi.login !== 'function') { unavailable(); return }
        wxApi.login({ timeout: config.requestTimeoutMs, success: result => {
          if (typeof result?.code !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(result.code)) unavailable()
          else resolve(result.code)
        }, fail: unavailable })
      } catch { unavailable() }
    })
    if (generation !== epoch) throw error('请求已取消', 'CANCELLED')
    return request(WECHAT_AUTH + path, { method: 'POST', data: { ...data, code }, publicLogin })
  }
  function bindingView(body) {
    if (typeof body.bound !== 'boolean') throw error('服务返回无效的微信绑定状态，请刷新确认', 'INVALID_WECHAT_STATUS')
    return body.bound
  }
  function context(value) {
    if (!validId(value?.guild_id) || !validId(value?.channel_id)) throw error('请先选择有效服务器和语音频道', 'CONTEXT_REQUIRED')
    return { guild_id: value.guild_id, channel_id: value.channel_id }
  }
  function admin(operation) {
    return user?.role === 'admin' && !user.must_change_password ? operation() : Promise.reject(error('此功能仅管理员可用', 'FORBIDDEN'))
  }
  function accountRequest(platform, action, data = {}) {
    const spec = ACCOUNT_ACTIONS[action]
    const allowed = platform === 'wy' ? ['detail', 'level', 'subcount', 'cookie', 'logout', 'signin', 'captcha', 'verify', 'cellphone'] :
      platform === 'qq' ? ['profile', 'cookie', 'logout', 'refresh'] : platform === 'bili' ? ['profile', 'cookie', 'logout'] : []
    if (!spec || !allowed.includes(action)) return Promise.reject(error('不支持的音乐账号操作', 'BAD_REQUEST'))
    let query = ''
    if (platform === 'wy' && action === 'detail') {
      const uid = typeof data?.uid === 'string' || typeof data?.uid === 'number' ? String(data.uid) : ''
      if (!/^[0-9]{1,32}$/.test(uid) || !/[1-9]/.test(uid)) return Promise.reject(error('音乐账号无效', 'BAD_REQUEST'))
      query = `?uid=${encodeURIComponent(uid)}`
    }
    return request(PLATFORM_PATHS[platform] + spec[1] + query, { method: spec[0], data: spec[0] === 'GET' ? undefined : data,
      platformResponse: true, acceptedCodes: action === 'cellphone' ? [200, 803] : [200] })
  }
  const client = {
    hasSession: () => Boolean(sessionCookie && csrf && user),
    forgetSession() { client.abortAll(); clear() },
    async login(username, password) { client.abortAll(); clear(); return acceptLogin(await request('/login', { method: 'POST', publicLogin: true, data: { username, password } })) },
    async loginWithWechat() { client.abortAll(); clear(); return acceptLogin(await requestWithWechatCode('login', { publicLogin: true })) },
    async wechatBindingStatus() { return bindingView(await request(WECHAT_AUTH + 'status')) },
    async bindWechat() {
      if (!client.hasSession()) throw error('会话已过期，请重新登录', 'UNAUTHORIZED')
      return bindingView(await requestWithWechatCode('bind'))
    },
    async unbindWechat() {
      if (!client.hasSession()) throw error('会话已过期，请重新登录', 'UNAUTHORIZED')
      return bindingView(await request(WECHAT_AUTH + 'unbind', { method: 'POST', data: {} }))
    },
    async changePassword(current, next, confirm) { return acceptLogin(await request('/change-password', { method: 'POST',
      data: { current_password: current, new_password: next, confirm_password: confirm } })) },
    async session() { const body = await request('/api/auth/session'); const view = userView(body.user); if (!view) { clear(); throw error('会话数据无效', 'INVALID_SESSION') }; user = view; return { ...view } },
    async logout() { try { await request('/logout', { method: 'POST', data: {} }) } finally { client.abortAll(); clear() } },
    guilds: () => request('/api/guilds'),
    channels(guild) { if (!validId(guild)) return Promise.reject(error('请选择服务器', 'CONTEXT_REQUIRED')); return request(`/api/channels?guild_id=${encodeURIComponent(guild)}`) },
    active(guild) { if (!validId(guild)) return Promise.reject(error('请选择服务器', 'CONTEXT_REQUIRED')); return request(`/api/channels/active?guild_id=${encodeURIComponent(guild)}`) },
    playlist(value) { const ctx = context(value); return request(`/api/playlist/current?guild_id=${encodeURIComponent(ctx.guild_id)}&channel_id=${encodeURIComponent(ctx.channel_id)}`) },
    search(keyword, platform) { if (!['wy', 'qq', 'bili'].includes(platform) || !String(keyword).trim() || String(keyword).length > 128) return Promise.reject(error('请输入有效搜索词和平台', 'BAD_REQUEST'));
      return request(`/api/search?keyword=${encodeURIComponent(String(keyword).trim())}&platform=${platform}`) },
    platformStatus(platform) {
      if (!PLATFORM_PATHS[platform]) return Promise.reject(error('不支持的音乐平台', 'BAD_REQUEST'))
      return request(PLATFORM_PATHS[platform] + '/status', { platformResponse: true, neteaseStatus: platform === 'wy' })
    },
    platformPlaylists(platform, uid = '') {
      if (!PLATFORM_PATHS[platform] || platform === 'wy' && !validId(String(uid))) return Promise.reject(error('音乐账号无效', 'BAD_REQUEST'))
      const query = platform === 'wy' ? `?uid=${encodeURIComponent(uid)}&limit=100` : '?limit=100'
      return request(PLATFORM_PATHS[platform] + '/playlists' + query, { platformResponse: true })
    },
    account(platform, action, data) { return admin(() => accountRequest(platform, action, data)) },
    createPlatformQr(platform) { return admin(async () => {
      if (!PLATFORM_PATHS[platform]) throw error('不支持的音乐平台', 'BAD_REQUEST')
      const epoch = generation, qrEpoch = ++qrGeneration
      qrSessions.delete(platform)
      let body, fields
      if (platform === 'wy') {
        const key = await request(PLATFORM_PATHS.wy + '/qr/key', { method: 'POST', data: {}, platformResponse: true })
        if (!key.data?.unikey || epoch !== generation || qrEpoch !== qrGeneration) throw error('二维码准备已取消', 'CANCELLED')
        fields = { key: String(key.data.unikey) }
        body = await request(PLATFORM_PATHS.wy + '/qr/create', { method: 'POST', data: fields, platformResponse: true })
      } else {
        body = await request(PLATFORM_PATHS[platform] + '/qr/create', { method: 'POST', data: {}, platformResponse: true })
        fields = platform === 'qq' ? { ptqrtoken: body.ptqrtoken, qrsig: body.qrsig } : { qrcode_key: body.qrcode_key }
      }
      if (epoch !== generation || qrEpoch !== qrGeneration) throw error('二维码准备已取消', 'CANCELLED')
      if (Object.values(fields).some(value => value == null || value === '')) throw error('二维码数据无效', 'BAD_QR')
      qrSessions.set(platform, fields)
      // QR login parameters stay in this closure; only the intended display image is public.
      return { image: String(platform === 'wy' ? body.data?.qrimg || '' : body.qrcode || '') }
    }) },
    checkPlatformQr(platform) { return admin(async () => {
      const fields = qrSessions.get(platform)
      if (!fields) throw error('请重新生成二维码', 'BAD_QR')
      const body = await request(PLATFORM_PATHS[platform] + '/qr/check', { method: 'POST', data: fields,
        platformResponse: true, acceptedCodes: platform === 'wy' ? [800, 801, 802, 803] : [200] })
      if (qrSessions.get(platform) !== fields) throw error('二维码请求已取消', 'CANCELLED')
      let status = platform === 'wy' ? ({ 800: 'expired', 801: 'waiting', 802: 'scanned', 803: 'success' })[Number(body.code)] : body.status
      if (!['expired', 'waiting', 'scanned', 'success'].includes(status)) throw error('二维码状态无效', 'BAD_QR')
      if (status === 'success' || status === 'expired') qrSessions.delete(platform)
      // Match the Web NetEase login flow: save its platform cookie server-side, never in Page.data.
      if (platform === 'wy' && status === 'success') {
        if (typeof body.cookie !== 'string' || !body.cookie) throw error('登录凭据未确认，请刷新账号状态', 'BAD_QR')
        await accountRequest('wy', 'cookie', { cookie: body.cookie })
      }
      return { status, message: ({ expired: '二维码已过期，请刷新', waiting: '等待扫码', scanned: '已扫码，请在音乐平台确认', success: '登录成功' })[status] }
    }) },
    cancelPlatformQr() { qrGeneration++; qrSessions.clear() },
    users() { return admin(() => request('/api/admin/users')) },
    createUser(data) { return admin(() => request('/api/admin/users', { method: 'POST', data })) },
    updateUser(id, data) { return admin(() => Number.isSafeInteger(Number(id)) && Number(id) > 0 ?
      request(`/api/admin/users/${Number(id)}`, { method: 'PATCH', data }) : Promise.reject(error('无效用户', 'BAD_REQUEST'))) },
    removeUser(id) { return admin(() => Number.isSafeInteger(Number(id)) && Number(id) > 0 ?
      request(`/api/admin/users/${Number(id)}`, { method: 'DELETE' }) : Promise.reject(error('无效用户', 'BAD_REQUEST'))) },
    resetUserPassword(id) { return admin(() => Number.isSafeInteger(Number(id)) && Number(id) > 0 ?
      request(`/api/admin/users/${Number(id)}/reset-password`, { method: 'POST', data: {} }) : Promise.reject(error('无效用户', 'BAD_REQUEST'))) },
    runtimeStatus() { return admin(() => request('/api/debug', { debugResponse: true })) },
    systemStatus() { return admin(() => request('/api/system/status')) },
    logs(type = 'app') { return admin(() => ['app', 'debug'].includes(type) ? request(`/api/logs?type=${type}&lines=200`) : Promise.reject(error('无效日志类型', 'BAD_REQUEST'))) },
    clearLogs(type = 'app') { return admin(() => ['app', 'debug'].includes(type) ? request('/api/logs/clear', { method: 'POST', data: { type } }) : Promise.reject(error('无效日志类型', 'BAD_REQUEST'))) },
    command(action, value, fields = {}) {
      if (!ACTIONS[action]) return Promise.reject(error('不支持此操作', 'BAD_REQUEST'))
      let ctx
      try { ctx = context(value) } catch (failure) { return Promise.reject(failure) }
      // Context cannot be overridden by caller fields; no write is automatically retried.
      return request(ACTIONS[action], { method: 'POST', data: { ...fields, ...ctx } })
    },
    abortAll() { generation++; client.cancelPlatformQr(); for (const task of active) { try { task.abort?.() } catch {} }; active.clear() },
  }
  return client
}
function getKookClient(api) { if (!clients.has(api)) clients.set(api, createKookClient(api)); return clients.get(api) }
module.exports = { createKookClient, getKookClient, ACTIONS }
