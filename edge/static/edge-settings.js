'use strict';

(() => {
    const ids = {
        enabled: 'edge-relay-enabled', host: 'edge-relay-host', start: 'edge-relay-port-start', end: 'edge-relay-port-end',
        path: 'edge-relay-path', tls: 'edge-relay-tls', agentId: 'edge-agent-id', agentName: 'edge-agent-name',
        token: 'edge-agent-token', status: 'edge-relay-status', active: 'edge-relay-active', latency: 'edge-relay-latency',
        heartbeat: 'edge-relay-heartbeat', message: 'edge-relay-message', ports: 'edge-port-health'
    };
    const el = id => document.getElementById(id);
    let statusTimer = null;

    function message(text, error = false) {
        const node = el(ids.message);
        if (!node) return;
        node.textContent = text;
        node.classList.toggle('text-danger', error);
        node.classList.toggle('text-success', !error);
    }

    async function jsonRequest(url, options = {}) {
        const response = await fetch(url, {
            cache: 'no-store', ...options,
            headers: {...(options.body ? {'Content-Type': 'application/json'} : {}), ...(options.headers || {})}
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.success === false) throw new Error(data.error || `HTTP ${response.status}`);
        return data;
    }

    function fillConfig(data) {
        const cfg = data.config || {};
        el(ids.enabled).checked = Boolean(cfg.enabled);
        el(ids.host).value = cfg.host || '';
        el(ids.start).value = cfg.port_start ?? 28470;
        el(ids.end).value = cfg.port_end ?? 28479;
        el(ids.path).value = cfg.path || '/edge/v1/connect';
        el(ids.tls).checked = Boolean(cfg.tls_verify);
        el(ids.agentId).value = cfg.agent_id || 'edge-main';
        el(ids.agentName).value = cfg.agent_name || 'Primary Edge';
        el(ids.token).placeholder = data.token_configured ? '已配置；留空表示不修改' : '尚未配置';
    }

    function stateText(state) {
        const map = {connected:'已连接',connecting:'连接中',disconnected:'已断开',disabled:'已禁用',configuration_error:'配置异常',local_runtime_unavailable:'本地运行时不可用',failed:'Agent 异常',starting:'启动中'};
        return map[state] || state || '未知';
    }

    function renderPorts(ports) {
        const root = el(ids.ports);
        if (!root) return;
        root.replaceChildren();
        for (const item of ports || []) {
            const chip = document.createElement('span');
            chip.className = 'page-chip';
            const dot = document.createElement('span');
            dot.className = 'dot';
            chip.append(dot, document.createTextNode(`${item.port} · ${item.state || 'unknown'}`));
            if (item.code) chip.title = `${item.code}${item.detail ? ` · ${item.detail}` : ''}`;
            root.appendChild(chip);
        }
    }

    async function refreshStatus() {
        try {
            const data = await jsonRequest('/api/admin/edge/status');
            const edge = data.edge || {};
            el(ids.status).textContent = stateText(edge.state);
            el(ids.active).textContent = edge.active_port ? `${edge.host}:${edge.active_port}` : '—';
            el(ids.latency).textContent = Number.isFinite(Number(edge.latency_ms)) ? `${edge.latency_ms} ms` : '—';
            el(ids.heartbeat).textContent = edge.last_heartbeat_at ? `${Math.max(0, Math.round(Date.now()/1000-edge.last_heartbeat_at))} 秒前` : '—';
            el(ids.status).className = `status-pill ${edge.state === 'connected' ? 'ok' : edge.state === 'connecting' ? 'warn' : 'bad'}`;
            renderPorts(edge.ports);
            if (edge.last_error_code && edge.state !== 'connected') message(`${edge.last_error_code}${edge.last_error ? `：${edge.last_error}` : ''}`, true);
        } catch (error) {
            el(ids.status).textContent = '读取失败';
            message(error.message, true);
        }
    }

    async function loadConfig() {
        const data = await jsonRequest('/api/admin/edge/config');
        fillConfig(data);
        await refreshStatus();
    }

    document.getElementById('edge-relay-save')?.addEventListener('click', async () => {
        try {
            const payload = {
                enabled: el(ids.enabled).checked, host: el(ids.host).value.trim(),
                port_start: Number(el(ids.start).value), port_end: Number(el(ids.end).value),
                path: el(ids.path).value.trim(), tls_verify: el(ids.tls).checked,
                agent_id: el(ids.agentId).value.trim(), agent_name: el(ids.agentName).value.trim()
            };
            await jsonRequest('/api/admin/edge/config', {method:'PATCH', body:JSON.stringify(payload)});
            const token = el(ids.token).value.trim();
            if (token) {
                await jsonRequest('/api/admin/edge/token', {method:'POST', body:JSON.stringify({token})});
                el(ids.token).value = '';
            }
            message('远程节点配置已保存，Agent 正在按新的端口池重新连接。');
            await loadConfig();
        } catch (error) { message(error.message, true); }
    });

    document.getElementById('edge-relay-reconnect')?.addEventListener('click', async () => {
        try {
            await jsonRequest('/api/admin/edge/reconnect', {method:'POST', body:'{}'});
            message('已请求重新建立 WSS。');
            setTimeout(refreshStatus, 800);
        } catch (error) { message(error.message, true); }
    });

    document.getElementById('edge-relay-test')?.addEventListener('click', async event => {
        const button = event.currentTarget;
        button.disabled = true;
        message('正在并行检测端口池的 TCP/TLS/HTTP 可达性…');
        try {
            const data = await jsonRequest('/api/admin/edge/test-ports', {method:'POST', body:'{}'});
            renderPorts(data.ports);
            const ok = (data.ports || []).filter(item => item.state === 'reachable').length;
            message(`端口池检测完成：${ok}/${(data.ports || []).length} 个入口可达。`, ok === 0);
        } catch (error) { message(error.message, true); }
        finally { button.disabled = false; }
    });

    document.addEventListener('DOMContentLoaded', () => {
        loadConfig().catch(error => message(error.message, true));
        statusTimer = window.setInterval(refreshStatus, 5000);
    }, {once:true});
    window.addEventListener('beforeunload', () => statusTimer && clearInterval(statusTimer));
})();
