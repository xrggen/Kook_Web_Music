(() => {
    'use strict';

    const STORAGE_KEY = 'kook.ui.theme';
    const media = window.matchMedia?.('(prefers-color-scheme: dark)') || null;
    const stylesheets = [
        ['kook-theme-stylesheet', '/static/css/theme.css?v=1.6'],
        ['kook-mobile-stylesheet', '/static/css/mobile.css?v=2.3'],
        ['kook-mobile-polish-stylesheet', '/static/css/mobile-polish.css?v=1.1']
    ];

    function ensureResources() {
        stylesheets.forEach(([id, href]) => {
            if (document.getElementById(id)) return;
            const link = document.createElement('link');
            link.id = id;
            link.rel = 'stylesheet';
            link.href = href;
            document.head.appendChild(link);
        });

        if (!document.getElementById('kook-mobile-script')) {
            const script = document.createElement('script');
            script.id = 'kook-mobile-script';
            script.src = '/static/js/mobile-ui.js?v=2.0';
            script.async = false;
            document.head.appendChild(script);
        }
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

    function syncThemeColor(resolved) {
        let meta = document.querySelector('meta[name="theme-color"]');
        if (!meta) {
            meta = document.createElement('meta');
            meta.name = 'theme-color';
            document.head.appendChild(meta);
        }
        meta.content = resolved === 'light' ? '#f4f6fa' : '#0d0f12';
    }

    function apply() {
        ensureResources();
        const mode = readMode();
        const resolved = resolve(mode);
        const root = document.documentElement;
        root.dataset.uiThemeMode = mode;
        root.dataset.uiTheme = resolved;
        root.dataset.bsTheme = resolved;
        root.style.colorScheme = resolved;
        syncThemeColor(resolved);
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
