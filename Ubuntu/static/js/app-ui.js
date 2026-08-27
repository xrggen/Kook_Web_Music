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

    window.KookUI = {
        getPreferences,
        applyPreferences,
        setPreference,
        resetPreferences
    };

    applyPreferences();
})();
