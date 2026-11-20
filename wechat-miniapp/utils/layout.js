'use strict'
function layout(api = {}) {
  let window = {}, base = {}
  try { window = api.getWindowInfo?.() || api.getSystemInfoSync?.() || {} } catch {}
  try { base = api.getAppBaseInfo?.() || api.getSystemInfoSync?.() || {} } catch {}
  const scale = Math.max(1, Math.min(1.6, (Number(base.fontSizeSetting) || 16) / 16))
  let menu = null
  try { menu = api.getMenuButtonBoundingClientRect?.() } catch {}
  return { uiFont: Math.round(14 * Math.min(scale, 1.35)), contentFont: Math.round(16 * scale),
    windowWidth: window.windowWidth || 375, windowHeight: window.windowHeight || 680,
    headerTop: Number(window.statusBarHeight) || 24,
    headerRight: menu?.left > 0 ? Math.max(88, (window.windowWidth || 375) - menu.left + 8) : 100 }
}
module.exports = { layout }
