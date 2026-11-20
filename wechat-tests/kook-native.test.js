'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { createRequire } = require('node:module')
const { createKookClient, ACTIONS } = require('../wechat-miniapp/services/kook-api')
const { layout } = require('../wechat-miniapp/utils/layout')
const CONFIG = require('../wechat-miniapp/config')
const COOKIE = 's'.repeat(43), CSRF = 'c'.repeat(43)
function network() {
  const pending = [], writes = []
  const api = { request(options) { const task = { aborted: false, abort() { task.aborted = true; options.fail({ errMsg: 'cancelled' }) } };
    pending.push({ options, task }); return task }, getStorageSync() {}, setStorageSync: (key, value) => writes.push({ key, value }) }
  return { api, pending, writes }
}
function complete(request, data, statusCode = 200, cookies = []) { request.options.success({ data, statusCode, cookies, header: {} }) }
async function login(client, fixture) {
  const promise = client.login('fixture', 'dummy-test-password')
  complete(fixture.pending.at(-1), { success: true, clientProtocol: 'kook-wechat-v1', csrfToken: CSRF,
    user: { id: 1, username: 'fixture', role: 'user', must_change_password: false } }, 200, [`kook_session=${COOKIE}; Path=/`, `kook_csrf=${CSRF}; Path=/`])
  return promise
}

test('native login retains cookies privately and never persists passwords/session/CSRF or exposes them in a user view', async () => {
  const fixture = network(), client = createKookClient(fixture.api)
  assert.equal(client.hasSession(), false)
  const user = await login(client, fixture)
  assert.equal(client.hasSession(), true)
  assert.equal(user.role, 'user'); assert.equal(user.must_change_password, false)
  assert.deepEqual(Object.keys(user).sort(), ['id', 'must_change_password', 'role', 'username'])
  assert.ok(!JSON.stringify(user).includes('dummy-test-password') && !JSON.stringify(user).includes(COOKIE) && !JSON.stringify(user).includes(CSRF))
  assert.equal(fixture.writes.length, 0)
  assert.equal(fixture.pending[0].options.url, CONFIG.apiBaseUrl + '/login')
  assert.equal(fixture.pending[0].options.header.Cookie, undefined)
  const promise = client.command('pause', { guild_id: '100', channel_id: '200' }, { guild_id: 'wrong', channel_id: 'wrong' })
  const request = fixture.pending.at(-1)
  assert.equal(request.options.header.Cookie, `kook_session=${COOKIE}; kook_csrf=${CSRF}`)
  assert.equal(request.options.header['X-CSRF-Token'], CSRF)
  assert.deepEqual(request.options.data, { guild_id: '100', channel_id: '200' })
  assert.equal(new URL(request.options.url).search, '')
  complete(request, { success: true }); await promise
})

test('JSON backend/cookie protocol mismatch is detected without accepting an unverified session', async () => {
  const fixture = network(), client = createKookClient(fixture.api)
  const html = client.login('fixture', 'dummy')
  complete(fixture.pending.at(-1), '<html>legacy login redirect</html>', 401)
  await assert.rejects(html, { code: 'BACKEND_UPDATE_REQUIRED' }); assert.equal(client.hasSession(), false)
  const bad = client.login('fixture', 'dummy')
  complete(fixture.pending.at(-1), { success: true, clientProtocol: 'kook-wechat-v1', csrfToken: 'mismatched',
    user: { id: 1, username: 'fixture', role: 'user' } }, 200, [`kook_session=${COOKIE}`, `kook_csrf=${CSRF}`])
  await assert.rejects(bad, { code: 'BACKEND_UPDATE_REQUIRED' }); assert.equal(client.hasSession(), false)
})

test('WeChat login exchanges a fresh code without a prior cookie, and accepts only the existing signed-in contract', async () => {
  const fixture = network(), client = createKookClient(fixture.api)
  let credential
  fixture.api.login = ({ success }) => { credential = success }
  const pending = client.loginWithWechat()
  assert.equal(fixture.pending.length, 0)
  credential({ code: 'fixture-one-time-code' }); await Promise.resolve()
  const entry = fixture.pending[0]
  assert.equal(entry.options.url, CONFIG.apiBaseUrl + '/api/auth/wechat/login')
  assert.equal(entry.options.method, 'POST')
  assert.equal(entry.options.header.Cookie, undefined)
  assert.deepEqual(entry.options.data, { code: 'fixture-one-time-code' })
  complete(entry, { success: true, clientProtocol: CONFIG.protocol, csrfToken: CSRF,
    user: { id: 9, username: 'fixture', role: 'user', openid: 'server-only' } }, 200, [`kook_session=${COOKIE}`, `kook_csrf=${CSRF}`])
  assert.deepEqual(await pending, { id: 9, username: 'fixture', role: 'user', must_change_password: false })
  assert.equal(client.hasSession(), true)
  assert.equal(fixture.writes.length, 0)
})

test('cancelling while WeChat is issuing a code prevents the server request', async () => {
  const fixture = network(), client = createKookClient(fixture.api)
  let credential
  fixture.api.login = ({ success }) => { credential = success }
  const pending = client.loginWithWechat()
  client.abortAll()
  credential({ code: 'unused-fixture-code' })
  await assert.rejects(pending, { code: 'CANCELLED' })
  assert.equal(fixture.pending.length, 0)
})

test('unbound WeChat leaves password login available without surfacing raw server errors or retrying', async () => {
  const fixture = network(), client = createKookClient(fixture.api)
  fixture.api.login = ({ success }) => success({ code: 'fixture' })
  const pending = client.loginWithWechat()
  await Promise.resolve()
  complete(fixture.pending[0], { success: false, error: 'upstream internal information' }, 401)
  await assert.rejects(pending, { code: 'UNAUTHORIZED', message: /账号密码/ })
  assert.equal(fixture.pending.length, 1)
  assert.equal(client.hasSession(), false)
  await login(client, fixture)
  assert.equal(client.hasSession(), true)
})

test('WeChat binding status uses the existing session and cannot confuse a failed read with unbound', async () => {
  const fixture = network(), client = createKookClient(fixture.api)
  await login(client, fixture)
  const lookup = client.wechatBindingStatus()
  const entry = fixture.pending.at(-1)
  assert.equal(entry.options.url, CONFIG.apiBaseUrl + '/api/auth/wechat/status')
  assert.equal(entry.options.method, 'GET')
  assert.equal(entry.options.header.Cookie, `kook_session=${COOKIE}; kook_csrf=${CSRF}`)
  complete(entry, { success: true, bound: 'false' })
  await assert.rejects(lookup, { code: 'INVALID_WECHAT_STATUS' })
  const retried = client.wechatBindingStatus()
  complete(fixture.pending.at(-1), { success: true, bound: false })
  assert.equal(await retried, false)
})

test('WeChat binding requires a session and CSRF, but sends neither password nor WeChat identity', async () => {
  const fixture = network(), client = createKookClient(fixture.api)
  let codeRequests = 0
  fixture.api.login = ({ success }) => success({ code: `code-${++codeRequests}` })
  await assert.rejects(client.bindWechat(), { code: 'UNAUTHORIZED' })
  await assert.rejects(client.unbindWechat(), { code: 'UNAUTHORIZED' })
  assert.equal(codeRequests, 0)
  await login(client, fixture)
  const failed = client.bindWechat()
  await Promise.resolve()
  let entry = fixture.pending.at(-1)
  assert.deepEqual(entry.options.data, { code: 'code-1' })
  assert.equal(entry.options.header['X-CSRF-Token'], CSRF)
  complete(entry, { success: false, code: 'WECHAT_CODE_INVALID' }, 401)
  await assert.rejects(failed, { code: 'WECHAT_CODE_INVALID' })
  assert.equal(client.hasSession(), true)

  const bind = client.bindWechat()
  await Promise.resolve()
  entry = fixture.pending.at(-1)
  assert.equal(entry.options.url, CONFIG.apiBaseUrl + '/api/auth/wechat/bind')
  assert.equal(entry.options.method, 'POST')
  assert.equal(entry.options.header.Cookie, `kook_session=${COOKIE}; kook_csrf=${CSRF}`)
  assert.equal(entry.options.header['X-CSRF-Token'], CSRF)
  assert.deepEqual(entry.options.data, { code: 'code-2' })
  complete(entry, { success: true, bound: true })
  assert.equal(await bind, true)

  const unbind = client.unbindWechat()
  entry = fixture.pending.at(-1)
  assert.equal(entry.options.url, CONFIG.apiBaseUrl + '/api/auth/wechat/unbind')
  assert.equal(entry.options.method, 'POST')
  assert.equal(entry.options.header['X-CSRF-Token'], CSRF)
  assert.deepEqual(entry.options.data, {})
  complete(entry, { success: true, bound: false })
  assert.equal(await unbind, false)
  assert.equal(codeRequests, 2)
  assert.equal(fixture.writes.length, 0)
})

test('cookie fallback parses combined Set-Cookie headers with Expires commas', async () => {
  const fixture = network(), client = createKookClient(fixture.api), promise = client.login('fixture', 'dummy')
  fixture.pending[0].options.success({ statusCode: 200, data: { success: true, clientProtocol: CONFIG.protocol, csrfToken: CSRF,
    user: { id: 1, username: 'fixture', role: 'user' } }, header: { 'sEt-CoOkIe': `kook_session=${COOKIE}; Expires=Thu, 08 Oct 2026 00:00:00 GMT; Path=/, kook_csrf=${CSRF}; Path=/` } })
  await promise; assert.equal(client.hasSession(), true)
})

test('unauthorized responses expire local auth; forbidden Scope does not bypass server policy', async () => {
  const fixture = network(), client = createKookClient(fixture.api); await login(client, fixture)
  const forbidden = client.command('join', { guild_id: '100', channel_id: '200' })
  complete(fixture.pending.at(-1), { success: false, error: '当前用户不在授权范围内' }, 403)
  await assert.rejects(forbidden, { code: 'FORBIDDEN' }); assert.equal(client.hasSession(), true)
  const session = client.session(); complete(fixture.pending.at(-1), { success: false, error: '未登录' }, 401)
  await assert.rejects(session, { code: 'UNAUTHORIZED' }); assert.equal(client.hasSession(), false)
})

test('fixed endpoint/action/context boundaries and unknown write results never trigger automatic retries', async () => {
  const fixture = network(), client = createKookClient(fixture.api); await login(client, fixture)
  await assert.rejects(client.command('arbitrary/path', { guild_id: '100', channel_id: '200' }), { code: 'BAD_REQUEST' })
  await assert.rejects(client.command('join', { guild_id: '100\n', channel_id: '200' }), { code: 'CONTEXT_REQUIRED' })
  await assert.rejects(client.search('query', 'unsupported'), { code: 'BAD_REQUEST' })
  const before = fixture.pending.length, command = client.command('skip', { guild_id: '100', channel_id: '200' })
  fixture.pending.at(-1).options.fail({ errMsg: `sensitive: ${COOKIE} ${CSRF}` })
  await assert.rejects(command, failure => { assert.equal(failure.code, 'NETWORK_ERROR'); assert.ok(failure.message.includes('刷新')); assert.ok(!failure.message.includes(COOKIE)); return true })
  assert.equal(fixture.pending.length, before + 1)
  assert.equal(new URL(CONFIG.apiBaseUrl).port, '28443'); assert.equal(client.request, undefined)
  assert.equal(ACTIONS.add, '/api/playlist/add')
})

test('aborted and overlapping login callbacks cannot revive an old account; duplicate callback is ignored', async () => {
  const fixture = network(), client = createKookClient(fixture.api)
  const first = client.login('first', 'dummy').catch(failure => failure.code)
  const second = login(client, fixture)
  assert.equal(await first, 'CANCELLED'); await second
  complete(fixture.pending[0], { success: true, clientProtocol: CONFIG.protocol, csrfToken: 'o'.repeat(43),
    user: { username: 'first', role: 'admin' } }, 200, [`kook_session=${'x'.repeat(43)}`, `kook_csrf=${'o'.repeat(43)}`])
  complete(fixture.pending[1], { success: false, error: 'duplicate' }, 401)
  assert.equal(client.hasSession(), true)
  const session = client.session(); assert.ok(fixture.pending.at(-1).options.header.Cookie.includes(COOKIE)); complete(fixture.pending.at(-1), { success: true, user: { username: 'fixture', role: 'user' } }); await session
})

test('first password change accepts a rotated session and logout clears secrets even on a network failure', async () => {
  const fixture = network(), client = createKookClient(fixture.api); await login(client, fixture)
  const changed = client.changePassword('current', 'new', 'new')
  const csrf2 = 'd'.repeat(43), cookie2 = 't'.repeat(43)
  assert.equal(fixture.pending.at(-1).options.header['X-CSRF-Token'], CSRF)
  complete(fixture.pending.at(-1), { success: true, clientProtocol: CONFIG.protocol, csrfToken: csrf2,
    user: { username: 'fixture', role: 'user', must_change_password: false } }, 200, [`kook_session=${cookie2}`, `kook_csrf=${csrf2}`])
  await changed
  const logout = client.logout(); assert.ok(fixture.pending.at(-1).options.header.Cookie.includes(cookie2))
  fixture.pending.at(-1).options.fail(); await assert.rejects(logout, { code: 'NETWORK_ERROR' }); assert.equal(client.hasSession(), false)
})

test('KOOK native module owns every import/config/storage; only back-to-home is shared navigation', () => {
  const root = path.resolve(__dirname, '../wechat-miniapp')
  function visit(directory) { return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => entry.isDirectory() ? visit(path.join(directory, entry.name)) : [path.join(directory, entry.name)]) }
  for (const file of visit(root).filter(file => file.endsWith('.js'))) {
    const source = fs.readFileSync(file, 'utf8')
    assert.doesNotMatch(source, /getApp\(|screenshare|viewer-controller|tool-history|ielts-/i)
    for (const match of source.matchAll(/require\(\s*['"]([^'"]+)['"]\s*\)/g)) {
      const target = path.resolve(path.dirname(file), match[1]); assert.ok(target.startsWith(root + path.sep), file)
    }
  }
  const metadata = require('../wechat-miniapp/tool.json'); assert.equal(metadata.sortOrder, 14); assert.equal(metadata.route, '/kook/pages/console/console')
})

test('responsive native controls scale independently with explicit touch and wrap constraints', () => {
  for (const width of [320, 360, 375, 428, 600, 768, 1024]) for (const font of [16, 20, 24, 32]) {
    const result = layout({ getWindowInfo: () => ({ windowWidth: width, windowHeight: 600 }), getAppBaseInfo: () => ({ fontSizeSetting: font }) })
    assert.ok(result.uiFont >= 14 && result.uiFont <= 19); assert.ok(result.contentFont >= 16 && result.contentFont <= 26)
    assert.equal(result.windowWidth, width)
  }
  const css = fs.readFileSync(path.resolve(__dirname, '../wechat-miniapp/pages/console/console.wxss'), 'utf8')
  assert.match(css, /min-height: 44px/); assert.match(css, /overflow-wrap: anywhere/); assert.doesNotMatch(css, /transform:\s*scale/)
})

test('native page aborts background tasks, preserves no password in Page data and ignores stale state replies', async () => {
  const filename = path.resolve(__dirname, '../wechat-miniapp/pages/console/console.js'), fixture = network()
  let definition; const timers = new Map(); let timer = 0
  vm.runInNewContext(fs.readFileSync(filename, 'utf8'), { Page: value => { definition = value }, wx: fixture.api, require: createRequire(filename),
    setTimeout: fn => { timers.set(++timer, fn); return timer }, clearTimeout: id => timers.delete(id) }, { filename })
  const page = { ...definition, data: JSON.parse(JSON.stringify(definition.data)), setData(values) { Object.assign(this.data, values) } }
  page.onLoad(); page.onShow(); page.setPassword({ currentTarget: { dataset: { field: 'login' } }, detail: { value: 'private-test-passphrase' } })
  assert.ok(!JSON.stringify(page.data).includes('private-test-passphrase'))
  page.setData({ phase: 'console', guilds: [{ id: '', name: '' }, { id: '100', name: 'guild' }], channels: [{ id: '', name: '' }, { id: '200', name: 'channel' }], guildIndex: 1, channelIndex: 1 })
  const result = page.readState()
  assert.equal(fixture.pending.length, 2)
  page.stateSequence++
  complete(fixture.pending[0], { success: true, active: { '200': 'playing' } }); complete(fixture.pending[1], { success: true, playlist: [{ name: 'stale', playing: true }] })
  await result; assert.equal(page.data.currentSong, '未播放')
  page.schedulePoll(); assert.equal(timers.size, 1)
  page.onHide(); assert.equal(timers.size, 0); assert.equal(page.foreground, false); assert.deepEqual(Object.keys(page.passwords), [])
  page.setData({ guilds: [{ id: 'old-user-resource', name: 'old private guild' }], currentSong: 'old private song', songs: [{ id: 'old-song' }], keyword: 'old private query' })
  page.setUser({ id: 2, username: 'new-user', role: 'user', must_change_password: false })
  assert.equal(page.data.guilds.length, 1); assert.equal(page.data.guilds[0].id, '')
  assert.equal(page.data.currentSong, '未播放'); assert.equal(page.data.songs.length, 0); assert.equal(page.data.keyword, '')
  page.onUnload(); assert.equal(page.disposed, true)
})

test('foreground restore preserves only the same user visible context and never automatically sends a command', async () => {
  const filename = path.resolve(__dirname, '../wechat-miniapp/pages/console/console.js'), fixture = network()
  let definition, commands = 0, timer = 0
  vm.runInNewContext(fs.readFileSync(filename, 'utf8'), { Page: value => { definition = value }, wx: fixture.api, require: createRequire(filename),
    setTimeout: () => ++timer, clearTimeout() {} }, { filename })
  const page = { ...definition, data: JSON.parse(JSON.stringify(definition.data)), setData(values) { Object.assign(this.data, values) } }
  page.onLoad()
  const user = { id: 1, username: 'fixture', role: 'user', must_change_password: false }
  page.setData({ user, phase: 'console', guilds: [{ id: '', name: '' }, { id: '100', name: 'guild' }], channels: [{ id: '', name: '' }, { id: '200', name: 'channel' }], guildIndex: 1, channelIndex: 1 })
  page.api = { hasSession: () => true, session: async () => user,
    guilds: async () => ({ success: true, guilds: [{ id: '100', name: 'guild' }] }),
    channels: async () => ({ success: true, channels: [{ id: '200', name: 'channel' }] }),
    active: async () => ({ success: true, active: { '200': 'playing' } }),
    playlist: async () => ({ success: true, playlist: [{ name: 'permitted song', playing: true }] }),
    command() { commands++ }, abortAll() {} }
  await page.onShow()
  assert.equal(page.context().guild_id, '100'); assert.equal(page.context().channel_id, '200'); assert.equal(page.data.currentSong, 'permitted song'); assert.equal(commands, 0)
  page.api.channels = async () => ({ success: true, channels: [] })
  await page.onShow(); assert.equal(page.context(), null); assert.equal(page.data.currentSong, '未播放'); assert.equal(commands, 0)
  page.onUnload()
})
