'use strict';

document.addEventListener('DOMContentLoaded', () => {
    restoreLibraryImportIntent();
    bindDesktopPopoverBehavior();
    bindQueuePromoteActions();
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

function bindQueuePromoteActions() {
    const playlistBody = document.getElementById('playlist-body');
    if (!playlistBody) return;

    installQueuePromoteStyles();

    const decorate = () => {
        const rows = Array.from(playlistBody.querySelectorAll('tr'));
        rows.forEach((row, position) => {
            if (row.querySelector('.empty-table-cell') || row.querySelector('.promote-btn')) {
                return;
            }

            const cells = row.querySelectorAll('td');
            if (cells.length < 3) return;

            const actionCell = cells[cells.length - 1];
            actionCell.classList.add('queue-row-actions');

            const songName = cells[1]?.querySelector('.track-primary')?.textContent?.trim()
                || '这首歌曲';
            const promoteButton = document.createElement('button');
            promoteButton.type = 'button';
            promoteButton.className = 'queue-inline-action promote-btn';
            promoteButton.dataset.queueIndex = String(position);
            promoteButton.title = position === 0 ? '已是下一首' : `将《${songName}》顶到下一首`;
            promoteButton.setAttribute('aria-label', promoteButton.title);
            promoteButton.disabled = position === 0;

            const icon = document.createElement('i');
            icon.className = position === 0
                ? 'bi bi-pin-angle-fill'
                : 'bi bi-arrow-up-circle';
            icon.setAttribute('aria-hidden', 'true');
            promoteButton.appendChild(icon);

            promoteButton.addEventListener('click', () => {
                promoteQueueItem(position, songName, promoteButton);
            });

            actionCell.prepend(promoteButton);
        });
    };

    decorate();
    const observer = new MutationObserver(decorate);
    observer.observe(playlistBody, { childList: true });
}

async function promoteQueueItem(index, songName, button) {
    if (index === 0 || !currentChannelId) return;

    const targetChannelId = currentChannelId;
    const targetGuildId = currentGuildId;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.replaceChildren();
    const spinner = document.createElement('span');
    spinner.className = 'spinner-border spinner-border-sm';
    spinner.setAttribute('aria-hidden', 'true');
    button.appendChild(spinner);

    try {
        const data = await requestJSON('/api/playlist/promote', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                guild_id: targetGuildId,
                channel_id: targetChannelId,
                index
            })
        });
        if (!data.success) {
            throw new Error(data.error || '顶歌失败');
        }

        if (data.already_top) {
            showSuccess(`《${data.name || songName}》已经是下一首`);
        } else {
            showSuccess(`《${data.name || songName}》已顶到下一首`);
        }

        if (String(targetChannelId) === String(currentChannelId)) {
            await loadPlaylist(targetChannelId);
        }
    } catch (error) {
        showError(error.message);
        button.disabled = false;
        button.removeAttribute('aria-busy');
        button.replaceChildren();
        const icon = document.createElement('i');
        icon.className = 'bi bi-arrow-up-circle';
        icon.setAttribute('aria-hidden', 'true');
        button.appendChild(icon);
    }
}

function installQueuePromoteStyles() {
    if (document.getElementById('queue-promote-styles')) return;

    const style = document.createElement('style');
    style.id = 'queue-promote-styles';
    style.textContent = `
        .queue-table tbody tr {
            grid-template-columns: 36px minmax(0, 1fr) 68px;
        }
        .queue-row-actions {
            display: flex;
            align-items: center;
            justify-content: flex-end;
            gap: 4px;
        }
        .queue-inline-action {
            display: grid;
            width: 28px;
            height: 28px;
            padding: 0;
            place-items: center;
            border: 1px solid var(--app-border);
            border-radius: 50%;
            color: #8b91d9;
            background: transparent;
            transition: color .14s ease, border-color .14s ease, background .14s ease;
        }
        .queue-inline-action:hover:not(:disabled) {
            color: #c7c3ff;
            border-color: rgba(116,103,244,.56);
            background: rgba(116,103,244,.12);
        }
        .queue-inline-action:disabled {
            cursor: default;
            color: #575e68;
            opacity: .72;
        }
        .queue-inline-action .spinner-border {
            width: 12px;
            height: 12px;
            border-width: 1.5px;
        }
    `;
    document.head.appendChild(style);
}
