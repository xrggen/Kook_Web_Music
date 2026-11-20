'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { createRequire } = require('node:module')
const { createKookClient } = require('../wechat-miniapp/services/kook-api')
const model = require('../wechat-miniapp/utils/mobile-model')
const { runtimeView, userRows, safeMessage } = require('../wechat-miniapp/services/mobile-management')
const config = require('../wechat-miniapp/config')
const COOKIE = 's'.repeat(43), CSRF = 'c'.repeat(43)
const user = (role = 'admin') => ({ id: 1, username: 'fixture', role, must_change_password: false })
// A button tap carries its dataset, whereas input/picker changes carry detail.value.
const event = (dataset = {}, value) => ({ currentTarget: { dataset }, detail: value === undefined ? {} : { value } })
const tick = async () => { for (let index = 0; index < 12; index++) await Promise.resolve() }

test('list counters stay synchronized with native rows and clear together after leaving the session', () => {
  const { page } = pageFixture()
  page.setView({ queue: [{ name: 'one' }, { name: 'two' }], users: [{ id: 1 }], songs: [{ id: 'x' }], logs: [{ id: 0 }], libraryRows: [{ id: 'p' }] })
  assert.equal(page.data.queueCount, 2); assert.equal(page.data.userCount, 1); assert.equal(page.data.songCount, 1)
  assert.equal(page.data.logCount, 1); assert.equal(page.data.libraryCount, 1)
  page.resetResources({ phase: 'login', user: null })
  assert.equal(page.data.queueCount, 0); assert.equal(page.data.userCount, 0); assert.equal(page.data.songCount, 0)
  assert.equal(page.data.logCount, 0); assert.equal(page.data.libraryCount, 0)
  page.onUnload()
})
function deferred() { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
function network() {
  const pending = [], values = new Map(), timers = new Map(), listeners = new Map(); let timer = 0
  const api = { request(options) { const task = { abort() { options.fail({ errMsg: 'cancelled' }) } }; pending.push({ options, task }); return task },
    getStorageSync: key => values.get(key), setStorageSync: (key, value) => values.set(key, value),
    getWindowInfo: () => ({ windowWidth: 375, windowHeight: 720, statusBarHeight: 24 }), getAppBaseInfo: () => ({ fontSizeSetting: 16, theme: 'dark' }),
    setNavigationBarColor() {}, onKeyboardHeightChange: fn => listeners.set('keyboard', fn), offKeyboardHeightChange: fn => { assert.equal(fn, listeners.get('keyboard')); listeners.delete('keyboard') },
    onThemeChange: fn => listeners.set('theme', fn), offThemeChange: fn => { assert.equal(fn, listeners.get('theme')); listeners.delete('theme') },
    hideKeyboard() {}, showModal(options) { options.success({ confirm: true }); options.complete?.() }, setClipboardData() {} }
  return { api, pending, values, timers, listeners, setTimeout: (fn, ms) => { timers.set(++timer, { fn, ms }); return timer }, clearTimeout: id => timers.delete(id) }
}
function complete(request, body, statusCode = 200, cookies = []) { request.options.success({ statusCode, data: body, cookies, header: {} }) }
async function authenticated(role = 'admin') {
  const fixture = network(), client = createKookClient(fixture.api), login = client.login('fixture', 'fake-test-password')
  complete(fixture.pending[0], { success: true, clientProtocol: config.protocol, csrfToken: CSRF, user: user(role) }, 200, [`kook_session=${COOKIE}`, `kook_csrf=${CSRF}`])
  await login; return { fixture, client }
}
function pageFixture() {
  const fixture = network(), filename = path.resolve(__dirname, '../wechat-miniapp/pages/console/console.js'); let definition
  vm.runInNewContext(fs.readFileSync(filename, 'utf8'), { Page: value => { definition = value }, wx: fixture.api,
    require: createRequire(filename), setTimeout: fixture.setTimeout, clearTimeout: fixture.clearTimeout }, { filename })
  const page = { ...definition, data: JSON.parse(JSON.stringify(definition.data)), setData(values, callback) { Object.assign(this.data, values); callback?.() } }
  page.onLoad(); return { page, fixture }
}
function target(page) {
  page.setData({ guilds: [{ id: '', name: '' }, { id: '100', name: '测试服务器' }], channels: [{ id: '', name: '' }, { id: '200', name: '测试频道' }], guildIndex: 1, channelIndex: 1 }); page.refreshContext()
}

test('opening the console does not attempt WeChat login; only the login button requests a code', async () => {
  const { page, fixture } = pageFixture()
  let calls = 0
  fixture.api.login = ({ success }) => { calls++; success({ code: 'fixture-code' }) }
  await page.onShow()
  assert.equal(calls, 0)
  const pending = page.loginWithWechat()
  await tick()
  assert.equal(calls, 1)
  complete(fixture.pending[0], { success: true, clientProtocol: config.protocol, csrfToken: CSRF, user: user('user') },
    200, [`kook_session=${COOKIE}`, `kook_csrf=${CSRF}`])
  await tick()
  complete(fixture.pending[1], { success: true, guilds: [] })
  await pending
  assert.equal(page.data.phase, 'console')
  assert.equal(page.data.user.role, 'user')
  assert.deepEqual(Array.from(fixture.values.values()), ['fixture'])
  assert.ok(!JSON.stringify(page.data).includes('fixture-code'))
  page.onUnload()
})

test('ordinary users can manage WeChat binding explicitly and a cancelled confirmation has no side effects', async () => {
  const { page, fixture } = pageFixture()
  const signIn = page.api.login('fixture', 'dummy')
  complete(fixture.pending[0], { success: true, clientProtocol: config.protocol, csrfToken: CSRF, user: user('user') },
    200, [`kook_session=${COOKIE}`, `kook_csrf=${CSRF}`])
  page.setUser(await signIn)
  let wxCalls = 0, confirmed = false
  fixture.api.login = ({ success }) => { wxCalls++; success({ code: 'ephemeral-test-code' }) }
  fixture.api.showModal = options => { options.success({ confirm: confirmed }); options.complete() }
  const status = page.openWechatBinding()
  assert.equal(page.data.sheet, 'wechat')
  assert.equal(page.data.wechatBound, null)
  complete(fixture.pending[1], { success: true, bound: false })
  await status
  assert.equal(page.data.wechatBound, false)
  page.requestBindWechat()
  assert.equal(wxCalls, 0)
  assert.equal(fixture.pending.length, 2)

  confirmed = true
  page.requestBindWechat()
  await tick()
  assert.equal(wxCalls, 1)
  assert.equal(page.data.wechatBound, null)
  assert.ok(fixture.pending[2].options.url.endsWith('/wechat/bind'))
  complete(fixture.pending[2], { success: true, bound: true })
  await tick()
  assert.equal(page.data.wechatBound, true)
  assert.ok(!JSON.stringify(page.data).includes('ephemeral-test-code'))

  page.requestUnbindWechat()
  assert.ok(fixture.pending[3].options.url.endsWith('/wechat/unbind'))
  fixture.pending[3].options.fail()
  await tick()
  assert.equal(page.data.wechatBound, null)
  assert.match(page.data.error, /刷新/)
  assert.equal(fixture.pending.length, 4)
  const refreshed = page.refreshWechatBinding()
  complete(fixture.pending[4], { success: true, bound: true })
  await refreshed
  page.requestUnbindWechat()
  complete(fixture.pending[5], { success: true, bound: false })
  await tick()
  assert.equal(page.data.wechatBound, false)
  assert.equal(wxCalls, 1)
  page.closeSheet()
  assert.equal(page.data.wechatBound, null)
  page.onUnload()
})

test('server and channel avatar failures use local fallback without clearing a refreshed or unrelated image', () => {
  const { page } = pageFixture(); page.setUser(user())
  const oldSrc = 'https://images.invalid/old.png', newSrc = 'https://images.invalid/new.png'
  page.setView({ guilds: [{ id: '', icon: '' }, { id: '100', name: 'server', icon: oldSrc }, { id: '101', name: 'other', icon: newSrc }],
    channels: [{ id: '', icon: '' }, { id: '200', name: 'channel', icon: oldSrc }] })
  page.contextIconError(event({ kind: 'guilds', id: '100', src: oldSrc }))
  assert.equal(page.data.guilds[1].icon, ''); assert.equal(page.data.guilds[2].icon, newSrc); assert.equal(page.data.guildCount, 3)
  page.setView({ guilds: page.data.guilds.map(row => row.id === '100' ? { ...row, icon: newSrc } : row) })
  page.contextIconError(event({ kind: 'guilds', id: '100', src: oldSrc })); assert.equal(page.data.guilds[1].icon, newSrc)
  page.contextIconError(event({ kind: 'channels', id: '200', src: oldSrc })); assert.equal(page.data.channels[1].icon, '')
  page.onUnload()
})
test('avatar error callbacks ignore malformed targets and background or disposed pages', () => {
  const { page } = pageFixture(), src = 'https://images.invalid/server.png'
  page.setView({ guilds: [{ id: '100', icon: src }] })
  for (const data of [{ kind: 'user', id: '100', src }, { kind: 'guilds', id: 'other', src },
    { kind: 'guilds', id: '100', src: '' }, { kind: 'guilds', id: '100', src: {} }]) page.contextIconError(event(data))
  assert.equal(page.data.guilds[0].icon, src)
  page.onHide(); page.contextIconError(event({ kind: 'guilds', id: '100', src })); assert.equal(page.data.guilds[0].icon, src)
  page.onUnload(); page.contextIconError(event({ kind: 'guilds', id: '100', src })); assert.equal(page.data.guilds[0].icon, src)
})
test('tool metadata and both native/web authentication screens use the requested robot branding', () => {
  const metadata = require('../wechat-miniapp/tool.json'), settings = require('../wechat-miniapp/pages/console/console.json')
  assert.equal(metadata.name, 'kook 机器人控制台'); assert.match(metadata.description, /kook 机器人/)
  assert.doesNotMatch(metadata.description, /音乐|Music/i); assert.equal(settings.navigationBarTitleText, metadata.name)
  const wxml = fs.readFileSync(path.resolve(__dirname, '../wechat-miniapp/pages/console/console.wxml'), 'utf8')
  const authentication = wxml.match(/<scroll-view wx:if="\{\{phase !== 'console'\}\}"[\s\S]*?<\/scroll-view>/)?.[0]
  assert.ok(authentication, 'the native authentication region must exist')
  assert.match(authentication, /kook 机器人控制台/); assert.doesNotMatch(authentication, /音乐|gen Music|KOOK 控制台/)
  for (const platform of ['windows', 'Ubuntu']) for (const page of ['login', 'change_password']) {
    const html = fs.readFileSync(path.resolve(__dirname, `../${platform}/templates/${page}.html`), 'utf8')
    assert.match(html, /kook 机器人控制台/); assert.doesNotMatch(html, /音乐|gen Music/)
  }
})

test('platform envelopes accept code:200 without weakening the playback/auth success contract', async () => {
  const { fixture, client } = await authenticated('user')
  const status = client.platformStatus('qq'); complete(fixture.pending.at(-1), { code: 200, logged_in: false }); assert.equal((await status).logged_in, false)
  const lists = client.platformPlaylists('wy', '123'); assert.equal(new URL(fixture.pending.at(-1).options.url).searchParams.get('uid'), '123')
  complete(fixture.pending.at(-1), { code: 200, playlist: [] }); await lists
  const command = client.command('pause', { guild_id: '100', channel_id: '200' }); complete(fixture.pending.at(-1), { code: 200 })
  await assert.rejects(command)
  await assert.rejects(client.platformStatus('bad'), { code: 'BAD_REQUEST' })
})
test('NetEase status accepts its nested code for connected and logged-out accounts without accepting unrelated or failed envelopes', async () => {
  const { fixture, client } = await authenticated()
  for (const profile of [{ userId: 123, nickname: 'fixture' }, null]) {
    const reading = client.platformStatus('wy')
    complete(fixture.pending.at(-1), { data: { code: 200, profile, account: profile ? { id: 123 } : null } })
    assert.equal(model.platformView('wy', await reading).connected, profile !== null)
  }
  for (const body of [{ data: { code: 500, profile: { userId: 123 } } }, { code: 200, data: { code: 500 } },
    { code: 500, success: true, data: { code: 200, profile: { userId: 123 } } }, { data: { profile: { userId: 123 } } }, { success: false, data: { code: 200 } }]) {
    const reading = client.platformStatus('wy'); complete(fixture.pending.at(-1), body); await assert.rejects(reading)
  }
  for (const operation of [() => client.platformStatus('qq'), () => client.platformStatus('bili'),
    () => client.account('wy', 'cookie', { cookie: 'fake-test-cookie' }), () => client.account('wy', 'detail', { uid: '123' })]) {
    const request = operation(); complete(fixture.pending.at(-1), { data: { code: 200 } }); await assert.rejects(request)
  }
  const reading = client.platformStatus('wy'); complete(fixture.pending.at(-1), { data: { code: 200 } }, 503); await assert.rejects(reading)
})
test('NetEase detail sends only a validated uid query and rejects invalid identities before requesting', async () => {
  const { fixture, client } = await authenticated()
  const detail = client.account('wy', 'detail', { uid: '123', cookie: 'ignored-test-cookie', arbitrary: 'ignored' })
  const request = fixture.pending.at(-1)
  assert.equal(request.options.url, config.apiBaseUrl + '/api/account/detail?uid=123')
  assert.equal(request.options.method, 'GET'); assert.equal(request.options.data, undefined)
  complete(request, { code: 200, profile: { userId: 123 } }); await detail
  const before = fixture.pending.length
  for (const fields of [{}, null, { uid: {} }, { uid: '0' }, { uid: '1&cookie=fake' }, { uid: '../1' }, { uid: '1'.repeat(33) }]) {
    await assert.rejects(client.account('wy', 'detail', fields), { code: 'BAD_REQUEST' })
  }
  assert.equal(fixture.pending.length, before)
})
test('the native account page reads the real nested NetEase envelope and supplies its uid when loading details', async () => {
  const { page, fixture } = pageFixture(), client = createKookClient(fixture.api)
  const login = client.login('fixture', 'fake-test-password')
  complete(fixture.pending.at(-1), { success: true, clientProtocol: config.protocol, csrfToken: CSRF, user: user() }, 200,
    [`kook_session=${COOKIE}`, `kook_csrf=${CSRF}`]); await login
  page.api = client; page.setUser(user()); page.setView({ tab: 'account' })
  const reading = page.refreshAccount(); assert.equal(page.data.accountState, 'loading')
  assert.equal(fixture.pending.at(-1).options.url, config.apiBaseUrl + '/api/account/status')
  complete(fixture.pending.at(-1), { data: { code: 200, account: { id: 123 }, profile: { userId: 123, nickname: 'status name' } } }); await tick()
  assert.equal(page.data.account.connected, true); assert.equal(page.data.accountState, 'ready')
  const requests = fixture.pending.slice(-3)
  assert.equal(requests[0].options.url, config.apiBaseUrl + '/api/account/detail?uid=123')
  complete(requests[0], { code: 200, profile: { userId: 123, nickname: 'detail name', follows: 7 } })
  complete(requests[1], { code: 200, data: { level: 8 } }); complete(requests[2], { code: 200, createdPlaylistCount: 3 })
  await reading; assert.equal(page.data.error, ''); assert.equal(page.data.account.accountName, 'detail name')
  assert.deepEqual(JSON.parse(JSON.stringify(page.data.account.stats)).map(row => row.value), ['8', '3', 7])
  page.onUnload()
})
test('account read failures remain unknown, preserve last confirmed status, and optional detail errors cannot disconnect an account', async () => {
  const { page } = pageFixture(); page.setUser(user()); let failing = true
  page.api = { platformStatus: async () => { if (failing) throw Object.assign(new Error('fixture offline'), { code: 'NETWORK_ERROR' });
    return { data: { code: 200, profile: { userId: 123, nickname: 'fixture' } } } },
    account: async () => { throw Object.assign(new Error('fixture details unavailable'), { code: 'SERVICE_ERROR' }) }, abortAll() {}, cancelPlatformQr() {} }
  await page.refreshAccount(); assert.equal(page.data.accountState, 'error'); assert.equal(page.data.account, null)
  assert.match(page.data.accountError, /fixture offline/); assert.equal(page.data.error, '')
  failing = false; await page.refreshAccount(); assert.equal(page.data.accountState, 'ready'); assert.equal(page.data.account.connected, true)
  assert.match(page.data.accountDetailsError, /账号已连接/)
  failing = true; await page.refreshAccount(); assert.equal(page.data.accountState, 'error'); assert.equal(page.data.account.connected, true)
  assert.equal(page.data.account.accountName, 'fixture'); page.onUnload()
})
test('late account status after background cannot publish a profile or start detail requests', async () => {
  const { page } = pageFixture(); page.setUser(user()); const status = deferred(); let detailReads = 0
  page.api = { platformStatus: () => status.promise, account: async () => { detailReads++; return { code: 200 } }, abortAll() {}, cancelPlatformQr() {} }
  const reading = page.refreshAccount(); page.onHide()
  status.resolve({ data: { code: 200, profile: { userId: 123 } } }); await reading
  assert.equal(page.data.account, null); assert.equal(detailReads, 0); page.onUnload()
})
test('administrator API methods reject normal users before any request is sent', async () => {
  const { fixture, client } = await authenticated('user'), before = fixture.pending.length
  for (const operation of [() => client.users(), () => client.createUser({}), () => client.updateUser(2, {}), () => client.removeUser(2),
    () => client.resetUserPassword(2), () => client.account('wy', 'cookie', { cookie: 'fake' }), () => client.createPlatformQr('qq'),
    () => client.runtimeStatus(), () => client.systemStatus(), () => client.logs(), () => client.clearLogs()]) await assert.rejects(operation(), { code: 'FORBIDDEN' })
  assert.equal(fixture.pending.length, before)
})
test('admin requests keep CSRF for PATCH/DELETE and only use fixed account/runtime paths', async () => {
  const { fixture, client } = await authenticated()
  const patch = client.updateUser(2, { role: 'user', enabled: true, scopes: 'guild:100' }), request = fixture.pending.at(-1)
  assert.equal(request.options.method, 'PATCH'); assert.equal(request.options.header['X-CSRF-Token'], CSRF)
  assert.equal(request.options.url, config.apiBaseUrl + '/api/admin/users/2'); complete(request, { success: true }); await patch
  const remove = client.removeUser(2); assert.equal(fixture.pending.at(-1).options.method, 'DELETE'); complete(fixture.pending.at(-1), { success: true }); await remove
  const before = fixture.pending.length; await assert.rejects(client.account('bili', 'refresh'), { code: 'BAD_REQUEST' }); await assert.rejects(client.removeUser('../evil'), { code: 'BAD_REQUEST' }); assert.equal(fixture.pending.length, before)
  const runtime = client.runtimeStatus(); complete(fixture.pending.at(-1), { status: 'success', bot_state: 'running' }); assert.equal((await runtime).bot_state, 'running')
})
test('NetEase QR login keeps keys/cookies private and saves only confirmed credentials to its server route', async () => {
  const { fixture, client } = await authenticated(), prepare = client.createPlatformQr('wy')
  complete(fixture.pending.at(-1), { code: 200, data: { unikey: 'fake-private-qr-key' } }); await tick()
  assert.equal(fixture.pending.at(-1).options.data.key, 'fake-private-qr-key')
  complete(fixture.pending.at(-1), { code: 200, data: { qrimg: 'data:image/png;base64,YQ==' } }); const qr = await prepare
  assert.deepEqual(qr, { image: 'data:image/png;base64,YQ==' }); assert.ok(!JSON.stringify(qr).includes('fake-private-qr-key'))
  const check = client.checkPlatformQr('wy'); complete(fixture.pending.at(-1), { code: 803, cookie: 'fake-platform-cookie' }); await tick()
  assert.equal(fixture.pending.at(-1).options.url, config.apiBaseUrl + '/api/account/cookie')
  assert.deepEqual(fixture.pending.at(-1).options.data, { cookie: 'fake-platform-cookie' })
  complete(fixture.pending.at(-1), { code: 200 }); const result = await check; assert.equal(result.status, 'success'); assert.ok(!JSON.stringify(result).includes('fake-platform-cookie'))
  await assert.rejects(client.checkPlatformQr('wy'), { code: 'BAD_QR' })
})
test('cancelled QR setup/poll cannot start a later cookie write or restore an old QR session', async () => {
  const { fixture, client } = await authenticated(), prepare = client.createPlatformQr('wy')
  client.cancelPlatformQr(); complete(fixture.pending.at(-1), { code: 200, data: { unikey: 'late-private-key' } })
  await assert.rejects(prepare, { code: 'CANCELLED' }); assert.equal(fixture.pending.length, 2)
  const second = client.createPlatformQr('wy'); complete(fixture.pending.at(-1), { code: 200, data: { unikey: 'new-key' } }); await tick()
  complete(fixture.pending.at(-1), { code: 200, data: { qrimg: 'data:image/png;base64,YQ==' } }); await second
  const check = client.checkPlatformQr('wy'), before = fixture.pending.length; client.cancelPlatformQr(); complete(fixture.pending.at(-1), { code: 803, cookie: 'late-cookie' })
  await assert.rejects(check, { code: 'CANCELLED' }); assert.equal(fixture.pending.length, before)
})
test('only NetEase cellphone login accepts its original code803 success variant', async () => {
  const { fixture, client } = await authenticated()
  const phone = client.account('wy', 'cellphone', { phone: '12345678900', captcha: '1234', countrycode: '86' })
  assert.equal(fixture.pending.at(-1).options.url, config.apiBaseUrl + '/api/account/cellphone/login')
  complete(fixture.pending.at(-1), { code: 803 }); await phone
  const other = client.account('wy', 'cookie', { cookie: 'fake-cookie' }); complete(fixture.pending.at(-1), { code: 803 }); await assert.rejects(other)
})
test('log type selection matches both platform backends and rejects unsupported files before sending', async () => {
  const { fixture, client } = await authenticated(), before = fixture.pending.length
  await assert.rejects(client.logs('bot'), { code: 'BAD_REQUEST' }); await assert.rejects(client.clearLogs('error'), { code: 'BAD_REQUEST' })
  assert.equal(fixture.pending.length, before)
  const read = client.logs('app'); assert.equal(fixture.pending.at(-1).options.url, config.apiBaseUrl + '/api/logs?type=app&lines=200'); complete(fixture.pending.at(-1), { success: true, logs: [] }); await read
  const clear = client.clearLogs('app'); assert.deepEqual(fixture.pending.at(-1).options.data, { type: 'app' }); assert.equal(fixture.pending.at(-1).options.header['X-CSRF-Token'], CSRF); complete(fixture.pending.at(-1), { success: true }); await clear
})
test('view adapters preserve track/progress fields and reject secrets, unsafe images and malformed identities', () => {
  const queue = model.playlistRows([{ name: '歌曲', artist: '歌手', playing: true, duration: 200, position: 40, token: 'private-track-token', url: 'https://media.invalid/signed' },
    { name: '下一首', queue_index: 7 }, null])
  assert.equal(queue.length, 2); assert.equal(queue[0].duration, 200); assert.equal(queue[0].position, 40); assert.equal(queue[1].queueIndex, 7)
  assert.ok(!JSON.stringify(queue).includes('private-track-token')); assert.equal(model.duration(75), '01:15')
  assert.equal(model.coverUrl('javascript:evil()', 'qq'), ''); assert.equal(model.coverUrl('https://image.invalid/a?token=private', 'wy'), '')
  assert.equal(model.coverUrl('//i0.hdslb.com/a.jpg', 'bili'), 'https://i0.hdslb.com/a.jpg')
  const rows = model.searchRows([{ id: {}, name: 'invalid' }, { id: 'BV123', name: '视频', ar: [{ name: '作者' }], csrf: 'private' }], 'bili')
  assert.equal(rows.length, 1); assert.ok(!JSON.stringify(rows).includes('csrf'))
})
test('song-list ID parsing covers original mobile links including hash, QQ disstid and Bilibili favourites', () => {
  for (const [value, platform, expected] of [['123', 'wy', '123'], ['https://music.163.com/#/playlist?id=123', 'wy', '123'],
    ['https://y.qq.com/n/ryqq/playlist/456', 'qq', '456'], ['https://y.qq.com/?disstid=456', 'qq', '456'],
    ['https://space.bilibili.com/123/favlist?fid=789', 'bili', '789'], ['https://www.bilibili.com/medialist/play/ml789', 'bili', '789']]) assert.equal(model.extractPlaylistId(value, platform), expected)
  assert.equal(model.extractPlaylistId('not a list', 'wy'), ''); assert.equal(model.extractPlaylistId('123', 'evil'), '')
})
test('default light overrides system dark, preferences remain isolated, and keyboard/theme listeners are disposed', () => {
  const { page, fixture } = pageFixture(); assert.equal(page.data.themeMode, 'light'); assert.equal(page.data.resolvedTheme, 'light')
  page.setUser(user()); page.chooseTheme(event({ theme: 'system' })); assert.equal(page.data.resolvedTheme, 'dark')
  page.resetPreferences(); assert.equal(page.data.resolvedTheme, 'light')
  assert.deepEqual([...fixture.values.keys()], ['gen.kook.console.v1.preferences'])
  fixture.listeners.get('keyboard')({ height: 280 }); assert.equal(page.data.keyboardOpen, true); assert.equal(page.data.keyboardHeight, 280)
  page.onUnload(); assert.equal(fixture.listeners.size, 0); assert.equal(fixture.timers.size, 0)
})
test('normal-user navigation cannot enter any admin screen and forced password change cannot be cancelled', () => {
  const { page } = pageFixture(); page.setUser(user('user'))
  for (const tab of ['account', 'status', 'users', 'settings']) { page.chooseTab(event({ tab })); assert.equal(page.data.tab, 'play') }
  page.handleError({ code: 'PASSWORD_REQUIRED', message: '修改密码' }); assert.equal(page.data.phase, 'password'); assert.equal(page.data.user.must_change_password, true)
  page.cancelSecurity(); assert.equal(page.data.phase, 'password'); page.onUnload()
})
test('music library uses sanitized parallel platform data and an import intent never triggers playback', async () => {
  const { page } = pageFixture(); page.setUser(user('user')); target(page); let commands = 0
  page.api = { platformStatus: async platform => platform === 'wy' ? { code: 200, data: { profile: { userId: 1, nickname: '用户' }, cookie: 'private-library-cookie' } } : { code: 200, logged_in: false },
    platformPlaylists: async () => ({ code: 200, playlist: [{ id: '123', name: '歌单', trackCount: 9, token: 'private-library-token' }] }), abortAll() {}, cancelPlatformQr() {}, command() { commands++ } }
  await page.readLibrary(page.epoch); assert.equal(page.data.libraryRows.length, 1); assert.ok(!JSON.stringify(page.data).includes('private-library-'))
  page.libraryIntent(event({ key: 'wy-123' })); assert.equal(page.data.tab, 'play'); assert.equal(page.data.sheet, 'import'); assert.equal(page.data.playlistId, '123'); assert.equal(commands, 0)
  const captured = []; page.command = (action, fields) => captured.push({ action, fields }); page.importPlaylist()
  assert.equal(captured[0].action, 'import'); assert.equal(captured[0].fields.playlist_id, '123'); page.onUnload()
})
test('hiding during library status prevents follow-up playlist requests and late visible data', async () => {
  const { page } = pageFixture(); page.setUser(user('user')); const statuses = [deferred(), deferred(), deferred()]; let playlistReads = 0
  page.api = { platformStatus: platform => statuses[['wy', 'qq', 'bili'].indexOf(platform)].promise, platformPlaylists: async () => { playlistReads++; return { code: 200, playlist: [] } }, abortAll() {}, cancelPlatformQr() {} }
  const loading = page.readLibrary(page.epoch); page.onHide()
  statuses[0].resolve({ code: 200, data: { profile: { userId: 1 } } }); statuses[1].resolve({ code: 200, logged_in: true, uin: '2' }); statuses[2].resolve({ code: 200, logged_in: true, uid: 3 })
  await loading; assert.equal(playlistReads, 0); assert.equal(page.data.libraryRows.length, 0); page.onUnload()
})
test('sheets are mutually exclusive, gated by a selected target, and keyboard state resets on close', () => {
  const { page } = pageFixture(); page.setUser(user('user')); page.openSheet(event({ sheet: 'queue' })); assert.equal(page.data.sheet, '')
  target(page); page.openSheet(event({ sheet: 'player' })); assert.equal(page.data.sheet, 'player'); page.openSheet(event({ sheet: 'queue' })); assert.equal(page.data.sheet, 'queue')
  page.keyboardHeight({ height: 240 }); page.closeSheet(); assert.equal(page.data.sheet, ''); assert.equal(page.data.keyboardOpen, false); page.onUnload()
})
test('search ignores results after the input/context changed and playback progress uses server values', async () => {
  const { page } = pageFixture(); page.setUser(user('user')); target(page); const request = deferred()
  page.api = { search: () => request.promise, abortAll() {}, cancelPlatformQr() {}, active: async () => ({ success: true, active: { '200': 'paused' } }),
    playlist: async () => ({ success: true, playlist: [{ name: '歌曲', playing: true, position: 40, duration: 200 }], playback_modes: { playlist_repeat: true } }) }
  page.setData({ keyword: 'first' }); const searching = page.search(); page.setKeyword(event({}, 'second')); request.resolve({ success: true, songs: [{ id: '1', name: 'old result' }] }); await searching
  assert.equal(page.data.songs.length, 0); await page.readState(); assert.equal(page.data.progressPercent, 20); assert.equal(page.data.isPlaying, false); assert.equal(page.data.positionText, '00:40'); page.onUnload()
})
test('admin account inputs are private and QR image/timers disappear on background', async () => {
  const { page, fixture } = pageFixture(); page.setUser(user()); page.setData({ tab: 'account' }); page.setAccountSecret(event({ field: 'cookie' }, 'private-account-cookie'))
  assert.ok(!JSON.stringify(page.data).includes('private-account-cookie'))
  page.api = { createPlatformQr: async () => ({ image: 'data:image/png;base64,YQ==', key: 'private-qr-key' }), checkPlatformQr: async () => ({ status: 'waiting', message: '等待扫码' }), abortAll() {}, cancelPlatformQr() {} }
  await page.createQr(); assert.equal(page.data.accountQr, 'data:image/png;base64,YQ=='); assert.ok(!JSON.stringify(page.data).includes('private-qr-key')); assert.equal(fixture.timers.size, 1)
  page.onHide(); assert.equal(page.data.accountQr, ''); assert.equal(Object.keys(page.accountSecrets).length, 0); assert.equal(fixture.timers.size, 0); page.onUnload()
})
test('user creation reveals only a one-time password and self-reset preserves it on the logged-out screen', async () => {
  const { page } = pageFixture(); page.setUser(user()); let forgot = 0
  page.api = { createUser: async () => ({ success: true, temporary_password: 'fake-temporary-new-user' }), users: async () => ({ success: true, users: [{ id: 1, username: 'fixture', role: 'admin', enabled: true }] }),
    resetUserPassword: async () => ({ success: true, temporary_password: 'fake-temporary-self' }), forgetSession: () => { forgot++ }, abortAll() {}, cancelPlatformQr() {} }
  page.setData({ createUsername: 'other', createScopes: 'guild:100' }); await page.createUser(); assert.equal(page.data.temporaryPassword, 'fake-temporary-new-user')
  page.userAction(event({ id: 1, action: 'reset' })); await tick(); assert.equal(page.data.phase, 'login'); assert.equal(forgot, 1); assert.equal(page.data.temporaryPassword, 'fake-temporary-self')
  page.onHide(); assert.equal(page.data.temporaryPassword, ''); page.onUnload()
})
test('late creation/health responses cannot publish admin data or trigger another read after background', async () => {
  const { page } = pageFixture(); page.setUser(user()); const status = deferred(); let systemReads = 0
  page.api = { runtimeStatus: () => status.promise, systemStatus: async () => { systemReads++; return {} }, abortAll() {}, cancelPlatformQr() {} }
  const reading = page.readRuntime(page.epoch); page.onHide(); status.resolve({ status: 'success', bot_state: 'running' }); await reading
  assert.equal(systemReads, 0); assert.equal(page.data.runtime, null); page.onUnload()
})
test('account stats reject object-valued fields and changing platform clears an old library import intent', async () => {
  const { page } = pageFixture(); page.setUser(user())
  page.api = { platformStatus: async () => ({ code: 200, data: { profile: { userId: 1, nickname: 'fixture' } } }),
    account: async (platform, action) => action === 'detail' ? { code: 200, profile: { nickname: 'fixture' } } :
      action === 'level' ? { code: 200, data: { level: { token: 'private-level-token' } } } : { code: 200, createdPlaylistCount: { cookie: 'private-count-cookie' } },
    abortAll() {}, cancelPlatformQr() {} }
  await page.readAccount(page.epoch); assert.ok(!JSON.stringify(page.data).includes('private-level-token')); assert.ok(!JSON.stringify(page.data).includes('private-count-cookie'))
  page.setData({ platform: 0, playlistId: '123', importName: '网易云歌单' }); page.choosePlatform(event({ index: 1 })); assert.equal(page.data.playlistId, ''); assert.equal(page.data.importName, ''); page.onUnload()
})
test('health/user/log adapters use the original contracts and exclude backend secrets', () => {
  const view = runtimeView({ bot_state: 'running', token_valid: true, ffmpeg_path: true, bot_loop_heartbeat_age: 1, kook_gateway_probe_available: true, kook_gateway_heartbeat_age: 2,
    active_guilds: 3, token: 'private-health-token' }); assert.equal(view.tone, 'ok'); assert.ok(!JSON.stringify(view).includes('private-health-token'))
  assert.equal(runtimeView({ bot_state: 'failed' }).tone, 'bad')
  const users = userRows([{ id: 1, username: 'user', role: 'user', enabled: 1, scopes: 'guild:100', password: 'private-user-password' }]); assert.equal(users[0].enabled, true); assert.ok(!JSON.stringify(users).includes('private-user-password'))
  const message = safeMessage('Bearer fake-session cookie=fake-cookie https://media.invalid/a?token=fake-token'); assert.ok(!message.includes('fake-session') && !message.includes('fake-cookie') && !message.includes('fake-token'))
})
