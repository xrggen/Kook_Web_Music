'use strict';

let statusTimer = null;
let statusRequest = 0;

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('status-refresh-btn')?.addEventListener('click', () => refreshRuntimeStatus(true));
    refreshRuntimeStatus(false);
    statusTimer = window.setInterval(() => refreshRuntimeStatus(false), 5000);
});

window.addEventListener('beforeunload', () => {
    if (statusTimer) window.clearInterval(statusTimer);
});

async function refreshRuntimeStatus(showBusy) {
    const requestId = ++statusRequest;
    const button = document.getElementById('status-refresh-btn');
    const previousMarkup = button?.innerHTML;
    if (showBusy && button) {
        button.disabled = true;
        button.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span><span>刷新中</span>';
    }

    try {
        const response = await fetch('/api/debug', { cache: 'no-store' });
        const data = await response.json();
        if (requestId !== statusRequest) return;
        if (!response.ok || data.status !== 'success') {
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        renderRuntimeStatus(data);
    } catch (error) {
        if (requestId === statusRequest) renderRuntimeError(error);
    } finally {
        if (showBusy && button) {
            button.disabled = false;
            button.innerHTML = previousMarkup || '<i class="bi bi-arrow-clockwise"></i><span>立即刷新</span>';
        }
    }
}

function renderRuntimeStatus(data) {
    const botHealthy = /运行中/.test(String(data.bot_status || '')) || data.bot_state === 'running';
    const tokenReady = Boolean(data.token_valid);
    const ffmpegReady = Boolean(data.ffmpeg_path);
    const gatewayFresh = isFreshAge(data.kook_gateway_heartbeat_age, 150);
    const loopFresh = isFreshAge(data.bot_loop_heartbeat_age, 120);
    const overallHealthy = botHealthy && tokenReady && ffmpegReady && loopFresh && (gatewayFresh || !data.kook_gateway_probe_available);

    setText('metric-active-channels', data.active_guilds ?? 0);
    setText('metric-playing', data.playing_songs ?? 0);
    setText('metric-queued', data.queued_songs ?? 0);
    setText('metric-bot-state', humanizeBotState(data.bot_state, data.bot_status));

    setStatusValue('status-bot', humanizeBotState(data.bot_state, data.bot_status), botHealthy ? 'ok' : 'bad');
    setStatusValue('status-loop-heartbeat', formatAge(data.bot_loop_heartbeat_age), loopFresh ? 'ok' : 'warn');
    setStatusValue(
        'status-gateway-probe',
        data.kook_gateway_probe_available ? '已启用' : '不可用',
        data.kook_gateway_probe_available ? 'ok' : 'warn'
    );
    setStatusValue(
        'status-gateway-heartbeat',
        data.kook_gateway_probe_available ? formatAge(data.kook_gateway_heartbeat_age) : '未启用探针',
        !data.kook_gateway_probe_available ? 'warn' : gatewayFresh ? 'ok' : 'warn'
    );
    setStatusValue('status-token', tokenReady ? '已配置' : '未配置', tokenReady ? 'ok' : 'bad');
    setStatusValue('status-ffmpeg', ffmpegReady ? '可用' : '路径无效', ffmpegReady ? 'ok' : 'bad');

    const orb = document.getElementById('health-orb');
    orb?.classList.remove('ok', 'warn', 'bad');
    orb?.classList.add(overallHealthy ? 'ok' : botHealthy ? 'warn' : 'bad');

    setText('health-title', overallHealthy ? '运行状态正常' : botHealthy ? '运行中，但存在需要关注的项目' : 'Bot 运行状态异常');
    setText(
        'health-copy',
        overallHealthy
            ? 'Bot、事件循环与媒体依赖均处于可用状态。'
            : '请根据下方心跳、网关或依赖状态定位异常项。'
    );
    setText('health-refreshed-at', `最近刷新 ${new Date().toLocaleTimeString('zh-CN', { hour12: false })}`);

    const sidebarDot = document.getElementById('sidebar-health-dot');
    sidebarDot?.classList.remove('online', 'warning', 'error');
    sidebarDot?.classList.add(overallHealthy ? 'online' : botHealthy ? 'warning' : 'error');
}

function renderRuntimeError(error) {
    const orb = document.getElementById('health-orb');
    orb?.classList.remove('ok', 'warn');
    orb?.classList.add('bad');
    setText('health-title', '无法读取运行状态');
    setText('health-copy', error?.message || '运行时健康接口请求失败');
    setText('health-refreshed-at', `刷新失败 ${new Date().toLocaleTimeString('zh-CN', { hour12: false })}`);

    ['metric-active-channels', 'metric-playing', 'metric-queued', 'metric-bot-state'].forEach(id => setText(id, '—'));
    ['status-bot', 'status-loop-heartbeat', 'status-gateway-probe', 'status-gateway-heartbeat', 'status-token', 'status-ffmpeg']
        .forEach(id => setStatusValue(id, '未知', 'bad'));

    const sidebarDot = document.getElementById('sidebar-health-dot');
    sidebarDot?.classList.remove('online', 'warning');
    sidebarDot?.classList.add('error');
}

function setStatusValue(id, text, state) {
    const element = document.getElementById(id);
    if (!element) return;
    element.replaceChildren();
    const pill = document.createElement('span');
    pill.className = `status-pill ${state || ''}`.trim();
    pill.textContent = text;
    element.appendChild(pill);
}

function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = String(value ?? '—');
}

function isFreshAge(value, thresholdSeconds) {
    const age = Number(value);
    return Number.isFinite(age) && age >= 0 && age <= thresholdSeconds;
}

function formatAge(value) {
    const age = Number(value);
    if (!Number.isFinite(age) || age < 0) return '暂无数据';
    if (age < 2) return '刚刚';
    if (age < 60) return `${Math.round(age)} 秒前`;
    if (age < 3600) return `${Math.floor(age / 60)} 分钟前`;
    return `${Math.floor(age / 3600)} 小时前`;
}

function humanizeBotState(state, fallback) {
    const mapping = {
        running: '运行中',
        starting: '启动中',
        failed: '异常',
        configuration_error: '配置异常'
    };
    return mapping[state] || fallback || state || '未知';
}
