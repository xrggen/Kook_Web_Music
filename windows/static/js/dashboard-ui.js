'use strict';

document.addEventListener('DOMContentLoaded', () => {
    restoreLibraryImportIntent();
    bindDesktopPopoverBehavior();
});

function restoreLibraryImportIntent() {
    let intent = null;
    try {
        const raw = localStorage.getItem('kookLibraryImportIntent');
        if (!raw) return;
        intent = JSON.parse(raw);
        localStorage.removeItem('kookLibraryImportIntent');
    } catch (error) {
        console.warn('无法读取音乐库导入意图:', error);
        return;
    }

    if (!intent || !['wy', 'qq', 'bili'].includes(intent.platform) || !intent.playlistId) {
        return;
    }

    const radio = document.getElementById(`platform-${intent.platform}`);
    if (radio) {
        radio.checked = true;
        radio.dispatchEvent(new Event('change', { bubbles: true }));
    }

    const playlistInput = document.getElementById('playlist-input');
    if (playlistInput) playlistInput.value = String(intent.playlistId);

    const importer = document.querySelector('.playlist-import');
    if (importer) importer.open = true;

    const name = intent.name ? `「${intent.name}」` : '所选歌单';
    window.setTimeout(() => {
        if (typeof showSuccess === 'function') {
            showSuccess(`${name}已带到播放页，选择频道后即可导入`);
        }
    }, 150);
}

function bindDesktopPopoverBehavior() {
    const guildSelector = document.querySelector('.guild-selector');
    const playlistImport = document.querySelector('.playlist-import');

    document.getElementById('guild-list')?.addEventListener('click', event => {
        if (event.target.closest('.guild-item') && guildSelector) {
            window.setTimeout(() => { guildSelector.open = false; }, 80);
        }
    });

    document.addEventListener('click', event => {
        if (guildSelector?.open && !guildSelector.contains(event.target)) {
            guildSelector.open = false;
        }
        if (playlistImport?.open && !playlistImport.contains(event.target)) {
            playlistImport.open = false;
        }
    });

    document.addEventListener('keydown', event => {
        if (event.key !== 'Escape') return;
        if (guildSelector) guildSelector.open = false;
        if (playlistImport) playlistImport.open = false;
    });
}
