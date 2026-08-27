(() => {
    'use strict';

    const KEYS = {
        density: 'kook.ui.density',
        reducedMotion: 'kook.ui.reducedMotion'
    };

    function readBoolean(key, fallback = false) {
        try {
            const value = localStorage.getItem(key);
            if (value === null) return fallback;
            return value === 'true';
        } catch (error) {
            console.warn('无法读取界面偏好:', error);
            return fallback;
        }
    }

    function getPreferences() {
        let density = 'comfortable';
        try {
            density = localStorage.getItem(KEYS.density) || 'comfortable';
        } catch (error) {
            console.warn('无法读取界面密度:', error);
        }
        if (!['comfortable', 'compact'].includes(density)) {
            density = 'comfortable';
        }
        return {
            density,
            reducedMotion: readBoolean(KEYS.reducedMotion, false)
        };
    }

    function applyPreferences() {
        const preferences = getPreferences();
        const root = document.documentElement;
        root.classList.toggle('ui-density-compact', preferences.density === 'compact');
        root.classList.toggle('ui-reduced-motion', preferences.reducedMotion);
        root.dataset.uiDensity = preferences.density;
        return preferences;
    }

    function setPreference(name, value) {
        try {
            if (name === 'density') {
                const normalized = value === 'compact' ? 'compact' : 'comfortable';
                localStorage.setItem(KEYS.density, normalized);
            } else if (name === 'reducedMotion') {
                localStorage.setItem(KEYS.reducedMotion, value ? 'true' : 'false');
            }
        } catch (error) {
            console.warn('无法保存界面偏好:', error);
        }
        return applyPreferences();
    }

    function resetPreferences() {
        try {
            Object.values(KEYS).forEach(key => localStorage.removeItem(key));
        } catch (error) {
            console.warn('无法重置界面偏好:', error);
        }
        return applyPreferences();
    }

    function isFreshAge(value, thresholdSeconds) {
        const age = Number(value);
        return Number.isFinite(age) && age >= 0 && age <= thresholdSeconds;
    }

    function applySidebarHealth(state) {
        const dot = document.getElementById('sidebar-health-dot');
        if (!dot) return;
        dot.classList.remove('online', 'warning', 'error');
        if (state) dot.classList.add(state);
    }

    async function refreshSidebarHealth() {
        const dot = document.getElementById('sidebar-health-dot');
        if (!dot) return;
        try {
            const response = await fetch('/api/debug', { cache: 'no-store' });
            const data = await response.json();
            if (!response.ok || data.status !== 'success') {
                throw new Error(data.error || `HTTP ${response.status}`);
            }
            const botHealthy = /运行中/.test(String(data.bot_status || '')) || data.bot_state === 'running';
            const loopFresh = isFreshAge(data.bot_loop_heartbeat_age, 120);
            const gatewayHealthy = !data.kook_gateway_probe_available || isFreshAge(data.kook_gateway_heartbeat_age, 150);
            const dependenciesReady = Boolean(data.token_valid) && Boolean(data.ffmpeg_path);
            if (botHealthy && loopFresh && gatewayHealthy && dependenciesReady) {
                applySidebarHealth('online');
                dot.title = '系统状态正常';
            } else if (botHealthy) {
                applySidebarHealth('warning');
                dot.title = '系统运行中，但存在需要关注的项目';
            } else {
                applySidebarHealth('error');
                dot.title = '系统状态异常';
            }
        } catch (error) {
            applySidebarHealth('error');
            dot.title = '无法读取系统状态';
        }
    }

    window.KookUI = {
        getPreferences,
        applyPreferences,
        setPreference,
        resetPreferences,
        refreshSidebarHealth
    };

    applyPreferences();
    document.addEventListener('DOMContentLoaded', refreshSidebarHealth, { once: true });
})();
