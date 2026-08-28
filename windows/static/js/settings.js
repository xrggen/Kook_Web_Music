'use strict';

document.addEventListener('DOMContentLoaded', () => {
    const themeOptions = Array.from(document.querySelectorAll('input[name="ui-theme"]'));
    const densityToggle = document.getElementById('density-toggle');
    const motionToggle = document.getElementById('motion-toggle');
    const resetButton = document.getElementById('settings-reset-btn');
    const message = document.getElementById('settings-message');

    function syncControls() {
        const preferences = window.KookUI?.getPreferences?.() || {
            theme: 'dark',
            density: 'comfortable',
            reducedMotion: false
        };
        themeOptions.forEach(option => {
            option.checked = option.value === preferences.theme;
        });
        if (densityToggle) densityToggle.checked = preferences.density === 'compact';
        if (motionToggle) motionToggle.checked = Boolean(preferences.reducedMotion);
    }

    function showMessage(text) {
        if (!message) return;
        message.textContent = text;
        window.clearTimeout(showMessage.timer);
        showMessage.timer = window.setTimeout(() => {
            message.textContent = '';
        }, 2600);
    }

    themeOptions.forEach(option => {
        option.addEventListener('change', () => {
            if (!option.checked) return;
            const preferences = window.KookUI?.setPreference?.('theme', option.value);
            const labels = {
                dark: '已切换为深色模式',
                light: '已切换为浅色模式',
                system: `已跟随系统外观（当前${preferences?.resolvedTheme === 'light' ? '浅色' : '深色'}）`
            };
            showMessage(labels[option.value] || '主题设置已更新');
        });
    });

    densityToggle?.addEventListener('change', () => {
        window.KookUI?.setPreference?.('density', densityToggle.checked ? 'compact' : 'comfortable');
        showMessage(densityToggle.checked ? '已启用紧凑布局' : '已恢复舒适布局');
    });

    motionToggle?.addEventListener('change', () => {
        window.KookUI?.setPreference?.('reducedMotion', motionToggle.checked);
        showMessage(motionToggle.checked ? '已减少界面动画' : '已恢复界面动画');
    });

    resetButton?.addEventListener('click', () => {
        window.KookUI?.resetPreferences?.();
        syncControls();
        showMessage('界面偏好已恢复默认值');
    });

    syncControls();
});
