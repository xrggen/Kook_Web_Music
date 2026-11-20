'use strict'

// Native view adapters for dashboard.js/library.js; never copy server objects into Page.data.
const PLATFORMS = Object.freeze([
  { id: 'wy', name: '网易云', fullName: '网易云音乐', symbol: '♪', tone: 'netease' },
  { id: 'qq', name: 'QQ 音乐', fullName: 'QQ 音乐', symbol: '♫', tone: 'qq' },
  { id: 'bili', name: 'Bilibili', fullName: 'Bilibili', symbol: '▻', tone: 'bili' },
])
const text = (value, limit = 200) => typeof value === 'string' || typeof value === 'number' ? String(value).slice(0, limit) : ''
const validId = value => /^[A-Za-z0-9_.:-]{1,128}$/.test(text(value, 129))
const seconds = value => Math.max(0, Math.min(864000, Number(value) || 0))
function duration(value) {
  const time = Math.floor(seconds(value))
  return `${String(Math.floor(time / 60)).padStart(2, '0')}:${String(time % 60).padStart(2, '0')}`
}
function playlistRows(rows) {
  return (Array.isArray(rows) ? rows : []).filter(row => row && typeof row === 'object' && !Array.isArray(row)).slice(0, 500)
    .map((row, index) => ({ key: `${row.playing ? 'now' : 'queue'}-${index}`, name: text(row.name) || '未知歌曲', artist: text(row.artist) || '未知歌手',
      playing: row.playing === true, queueIndex: Number.isInteger(row.queue_index) && row.queue_index >= 0 ? row.queue_index : null,
      position: seconds(row.position), duration: seconds(row.duration), number: String(index + 1).padStart(2, '0') }))
}
function searchRows(rows, platform) {
  if (!PLATFORMS.some(item => item.id === platform)) return []
  return (Array.isArray(rows) ? rows : []).filter(row => row && validId(row.id)).slice(0, 100).map(row => ({
    id: text(row.id, 128), name: text(row.name) || '未知歌曲', platform,
    artist: Array.isArray(row.ar) ? row.ar.map(artist => text(artist?.name)).filter(Boolean).join(' / ').slice(0, 200) : text(row.artist) || '未知歌手',
    album: text(row.al?.name || row.album?.name || row.album) || (platform === 'bili' ? 'Bilibili 视频' : ''),
  }))
}
function extractPlaylistId(value, platform) {
  if (!PLATFORMS.some(item => item.id === platform)) return ''
  const raw = text(value, 1024).trim()
  if (/^[A-Za-z0-9_-]{1,128}$/.test(raw)) return raw
  // Match the original mobile importer, including NetEase #/playlist links.
  const patterns = platform === 'qq' ? [/\/playlist\/(\d+)/, /[?&]id=(\d+)/, /[?&]disstid=(\d+)/] :
    platform === 'bili' ? [/[?&](?:id|fid|media_id)=(\d+)/, /\/medialist\/play\/ml(\d+)/] : [/[?&]id=(\d+)/, /\/playlist\/(\d+)/]
  for (const pattern of patterns) { const found = raw.match(pattern); if (found) return found[1].slice(0, 128) }
  return ''
}
function coverUrl(value, platform) {
  let raw = text(value, 2048).trim()
  if (raw.startsWith('//')) raw = 'https:' + raw
  else if (/^http:\/\//i.test(raw)) raw = 'https://' + raw.slice(7)
  else if (!/^[a-z][a-z0-9+.-]*:/i.test(raw) && raw) {
    const bases = { qq: 'https://y.gtimg.cn/', bili: 'https://i0.hdslb.com/' }
    raw = bases[platform] ? bases[platform] + raw.replace(/^\/+/, '') : ''
  }
  // Artwork may use public image hosts, but never arbitrary schemes or signed media links.
  return /^https:\/\/[a-z0-9.-]+(?:\/[\S]*)?$/i.test(raw) && !/[\\\s]/.test(raw) &&
    !/[?&](?:token|secret|signature|auth|credential|txSecret)=/i.test(raw) ? raw : ''
}
function platformView(platform, status) {
  const meta = PLATFORMS.find(item => item.id === platform)
  if (!meta) throw new Error('无效音乐平台')
  const data = status?.data || {}, profile = data.profile || {}, account = data.account || {}
  const uid = platform === 'wy' ? text(profile.userId || account.id, 128) : text(status?.uin || status?.uid, 128)
  const connected = platform === 'wy' ? validId(uid) : status?.logged_in === true
  return { ...meta, connected, uid, label: connected ? '已连接' : '未连接',
    accountName: connected ? text(profile.nickname || status?.uname || (platform === 'qq' && uid ? `QQ ${uid}` : meta.fullName)) : meta.fullName }
}
function libraryRows(platform, payload, account) {
  const rows = platform === 'wy' ? payload?.playlist : payload?.playlists
  const meta = PLATFORMS.find(item => item.id === platform)
  if (!meta) return []
  return (Array.isArray(rows) ? rows : []).filter(row => row && validId(row.id)).slice(0, 100).map(row => ({
    key: `${platform}-${row.id}`, id: text(row.id, 128), platform, platformName: meta.name, tone: meta.tone, symbol: meta.symbol,
    name: text(row.name) || (platform === 'bili' ? '未命名收藏夹' : '未命名歌单'),
    cover: coverUrl(row.coverImgUrl || row.cover, platform), count: Math.max(0, Math.min(1000000, Math.floor(Number(row.trackCount) || 0))),
    unit: platform === 'bili' ? '个视频' : '首', owner: text(row.creator?.nickname || account?.accountName),
    sourceUrl: platform === 'wy' ? `https://music.163.com/#/playlist?id=${encodeURIComponent(row.id)}` :
      platform === 'qq' ? `https://y.qq.com/n/ryqq/playlist/${encodeURIComponent(row.id)}` : `https://www.bilibili.com/medialist/play/ml${encodeURIComponent(row.id)}`,
  }))
}
module.exports = { PLATFORMS, text, validId, duration, playlistRows, searchRows, extractPlaylistId, platformView, libraryRows, coverUrl }
