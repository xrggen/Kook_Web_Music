(() => {
    'use strict';

    const MOBILE_QUERY = '(max-width: 820px)';

    function syncMobileHealthDots() {
        const source = document.getElementById('sidebar-health-dot');
        const targets = [
            document.getElementById('mobile-health-dot'),
            document.getElementById('mobile-more-health-dot')
        ].filter(Boolean);
        if (!source || !targets.length) return;

        const sync = () => {
            targets.forEach(target => {
                target.classList.remove('online', 'warning', 'error');
                ['online', 'warning', 'error'].forEach(name => {
                    if (source.classList.contains(name)) target.classList.add(name);
                });
                target.title = source.title || '系统状态';
            });
        };
        sync();
        new MutationObserver(sync).observe(source, { attributes: true, attributeFilter: ['class', 'title'] });
    }

    function bindMobileMoreMenu() {
        const more = document.querySelector('.mobile-more-menu');
        if (!more) return;
        document.addEventListener('click', event => {
            if (more.open && !more.contains(event.target)) more.open = false;
        });
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape') more.open = false;
        });
    }

    function createIconButton({ id, className, title, icon }) {
        const button = document.createElement('button');
        button.type = 'button';
        button.id = id;
        button.className = className;
        button.title = title;
        button.setAttribute('aria-label', title);
        const node = document.createElement('i');
        node.className = `bi ${icon}`;
        node.setAttribute('aria-hidden', 'true');
        button.appendChild(node);
        return button;
    }

    function bindDashboardMobileUI() {
        const queueColumn = document.querySelector('.queue-column');
        const queuePanel = document.getElementById('playlist-container');
        const player = document.getElementById('player-container');
        if (!queueColumn || !player) return;

        const media = window.matchMedia(MOBILE_QUERY);
        const queueTools = queuePanel?.querySelector('.queue-tools');
        const secondary = player.querySelector('.player-secondary-actions');

        let queueClose = document.getElementById('mobile-queue-close-btn');
        if (!queueClose && queueTools) {
            queueClose = createIconButton({
                id: 'mobile-queue-close-btn',
                className: 'icon-button mobile-player-control mobile-queue-close',
                title: '关闭播放队列',
                icon: 'bi-x-lg'
            });
            queueTools.appendChild(queueClose);
        }

        let collapse = document.getElementById('mobile-player-collapse-btn');
        if (!collapse) {
            collapse = createIconButton({
                id: 'mobile-player-collapse-btn',
                className: 'mobile-player-control mobile-player-collapse',
                title: '收起播放器',
                icon: 'bi-chevron-down'
            });
            player.prepend(collapse);
        }

        let expand = document.getElementById('mobile-player-expand-btn');
        if (!expand && secondary) {
            expand = createIconButton({
                id: 'mobile-player-expand-btn',
                className: 'mobile-player-control mobile-player-expand',
                title: '展开播放器',
                icon: 'bi-chevron-up'
            });
            secondary.prepend(expand);
        }

        let queueToggle = document.getElementById('mobile-queue-toggle-btn');
        if (!queueToggle && secondary) {
            queueToggle = createIconButton({
                id: 'mobile-queue-toggle-btn',
                className: 'mobile-player-control mobile-queue-toggle',
                title: '播放队列',
                icon: 'bi-list-ul'
            });
            secondary.prepend(queueToggle);
        }

        const syncBodyLock = () => {
            const locked = media.matches && (
                queueColumn.classList.contains('mobile-queue-open') ||
                player.classList.contains('mobile-expanded')
            );
            document.body.classList.toggle('mobile-modal-open', locked);
        };

        const closeQueue = () => {
            queueColumn.classList.remove('mobile-queue-open');
            queueToggle?.setAttribute('aria-expanded', 'false');
            syncBodyLock();
        };

        const collapsePlayer = () => {
            player.classList.remove('mobile-expanded');
            expand?.setAttribute('aria-expanded', 'false');
            syncBodyLock();
        };

        const openQueue = () => {
            if (!media.matches) return;
            if (!queuePanel || queuePanel.hidden) {
                if (typeof window.showError === 'function') window.showError('请先选择服务器和语音频道');
                return;
            }
            collapsePlayer();
            queueColumn.classList.add('mobile-queue-open');
            queueToggle?.setAttribute('aria-expanded', 'true');
            syncBodyLock();
        };

        const expandPlayer = () => {
            if (!media.matches || player.hidden) return;
            closeQueue();
            player.classList.add('mobile-expanded');
            expand?.setAttribute('aria-expanded', 'true');
            syncBodyLock();
        };

        queueToggle?.setAttribute('aria-expanded', 'false');
        expand?.setAttribute('aria-expanded', 'false');
        queueToggle?.addEventListener('click', openQueue);
        queueClose?.addEventListener('click', closeQueue);
        expand?.addEventListener('click', expandPlayer);
        collapse?.addEventListener('click', collapsePlayer);

        queueColumn.addEventListener('click', event => {
            if (event.target === queueColumn) closeQueue();
        });

        document.addEventListener('keydown', event => {
            if (event.key !== 'Escape' || !media.matches) return;
            if (queueColumn.classList.contains('mobile-queue-open')) closeQueue();
            else if (player.classList.contains('mobile-expanded')) collapsePlayer();
        });

        const handleViewportChange = () => {
            if (!media.matches) {
                closeQueue();
                collapsePlayer();
            }
        };
        if (typeof media.addEventListener === 'function') media.addEventListener('change', handleViewportChange);
        else if (typeof media.addListener === 'function') media.addListener(handleViewportChange);
    }

    document.addEventListener('DOMContentLoaded', () => {
        syncMobileHealthDots();
        bindMobileMoreMenu();
        bindDashboardMobileUI();
    }, { once: true });
})();
