(() => {
    'use strict';

    const STYLESHEET_ID = 'kook-theme-stylesheet';
    const STORAGE_KEY = 'kook.ui.theme';
    const media = window.matchMedia?.('(prefers-color-scheme: dark)') || null;

    function ensureStylesheet() {
        if (document.getElementById(STYLESHEET_ID)) return;
        const link = document.createElement('link');
        link.id = STYLESHEET_ID;
        link.rel = 'stylesheet';
        link.href = '/static/css/theme.css?v=1.0';
        document.head.appendChild(link);
    }

    function readMode() {
        try {
            const value = localStorage.getItem(STORAGE_KEY) || 'dark';
            return ['dark', 'light', 'system'].includes(value) ? value : 'dark';
        } catch (error) {
            return 'dark';
        }
    }

    function resolve(mode) {
        if (mode === 'system') return media?.matches ? 'dark' : 'light';
        return mode === 'light' ? 'light' : 'dark';
    }

    function apply() {
        ensureStylesheet();
        const mode = readMode();
        const resolved = resolve(mode);
        const root = document.documentElement;
        root.dataset.uiThemeMode = mode;
        root.dataset.uiTheme = resolved;
        root.dataset.bsTheme = resolved;
        root.style.colorScheme = resolved;
        return { theme: mode, resolvedTheme: resolved };
    }

    window.KookTheme = { apply, readMode };
    apply();

    const onSystemChange = () => {
        if (readMode() === 'system') apply();
    };
    if (media && typeof media.addEventListener === 'function') {
        media.addEventListener('change', onSystemChange);
    } else if (media && typeof media.addListener === 'function') {
        media.addListener(onSystemChange);
    }
})();
