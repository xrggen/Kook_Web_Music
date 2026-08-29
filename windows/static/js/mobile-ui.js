(() => {
    'use strict';

    const MOBILE_QUERY = '(max-width: 820px)';
    const media = window.matchMedia(MOBILE_QUERY);

    function onReady(callback) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', callback, { once: true });
        } else {
            callback();
        }
    }

    function syncMobileViewport() {
        const viewport = window.visualViewport;
        const height = viewport?.height || window.innerHeight;
        document.documentElement.style.setProperty('--mobile-visual-height', `${Math.round(height)}px`);
        if (!media.matches) {
            document.body.classList.remove('mobile-keyboard-open');
            return;
        }
        const keyboardGap = Math.max(0, window.innerHeight - height);
        document.body.classList.toggle('mobile-keyboard-open', keyboardGap > 140);
    }

    function bindViewportTracking() {
        syncMobileViewport();
        window.addEventListener('resize', syncMobileViewport, { passive: true });
        window.addEventListener('orientationchange', syncMobileViewport, { passive: true });
        window.visualViewport?.addEventListener('resize', syncMobileViewport, { passive: true });
        window.visualViewport?.addEventListener('scroll', syncMobileViewport, { passive: true });
    }

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

    function bindMobileHeaderContext() {
        const title = document.getElementById('mobile-header-title');
        const context = document.getElementById('mobile-header-context');
        const targetSummary = document.getElementById('target-summary');
        if (!title || !context || !targetSummary) return;

        const sync = () => {
            const value = String(targetSummary.textContent || '').trim();
            const inactive = !value || /请选择服务器|语音频道/.test(value);
            title.textContent = inactive ? '播放' : value;
            context.textContent = inactive ? '选择播放目标' : '当前播放目标';
        };
        sync();
        new MutationObserver(sync).observe(targetSummary, { childList: true, subtree: true, characterData: true });
    }

    function bindMobileMoreMenu() {
        const more = document.querySelector('.mobile-more-menu');
        if (!more) return;

        const sync = () => {
            document.body.classList.toggle('mobile-more-open', media.matches && more.open);
        };
        more.addEventListener('toggle', sync);
        document.addEventListener('click', event => {
            if (more.open && !more.contains(event.target)) more.open = false;
        });
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape') more.open = false;
        });
        sync();
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

    function bindSwipeDown(element, close, enabled) {
        if (!element) return;
        let startY = null;
        let startX = null;
        element.addEventListener('pointerdown', event => {
            if (!enabled() || event.pointerType === 'mouse') return;
            if (event.target.closest('button, a, input, select, textarea')) return;
            startY = event.clientY;
            startX = event.clientX;
        }, { passive: true });
        element.addEventListener('pointerup', event => {
            if (startY === null || startX === null) return;
            const dy = event.clientY - startY;
            const dx = Math.abs(event.clientX - startX);
            startY = null;
            startX = null;
            if (dy > 72 && dy > dx * 1.25) close();
        }, { passive: true });
        element.addEventListener('pointercancel', () => {
            startY = null;
            startX = null;
        }, { passive: true });
    }

    function bindDashboardMobileUI() {
        const queueColumn = document.querySelector('.queue-column');
        const queuePanel = document.getElementById('playlist-container');
        const player = document.getElementById('player-container');
        if (!queueColumn || !player) return;

        const queueTools = queuePanel?.querySelector('.queue-tools');
        const secondary = player.querySelector('.player-secondary-actions');
        const nowPlaying = player.querySelector('.now-playing-copy');

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
            queuePanel?.setAttribute('aria-modal', 'false');
            syncBodyLock();
        };

        const collapsePlayer = () => {
            player.classList.remove('mobile-expanded');
            expand?.setAttribute('aria-expanded', 'false');
            player.setAttribute('aria-modal', 'false');
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
            queuePanel.setAttribute('aria-modal', 'true');
            syncBodyLock();
            queueClose?.focus({ preventScroll: true });
        };

        const expandPlayer = () => {
            if (!media.matches || player.hidden) return;
            closeQueue();
            player.classList.add('mobile-expanded');
            expand?.setAttribute('aria-expanded', 'true');
            player.setAttribute('aria-modal', 'true');
            syncBodyLock();
            collapse?.focus({ preventScroll: true });
        };

        queueToggle?.setAttribute('aria-expanded', 'false');
        expand?.setAttribute('aria-expanded', 'false');
        queueToggle?.addEventListener('click', openQueue);
        queueClose?.addEventListener('click', closeQueue);
        expand?.addEventListener('click', expandPlayer);
        collapse?.addEventListener('click', collapsePlayer);

        nowPlaying?.setAttribute('role', 'button');
        nowPlaying?.setAttribute('tabindex', '0');
        nowPlaying?.setAttribute('aria-label', '展开正在播放');
        nowPlaying?.addEventListener('click', event => {
            if (media.matches && !event.target.closest('button')) expandPlayer();
        });
        nowPlaying?.addEventListener('keydown', event => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                expandPlayer();
            }
        });

        queueColumn.addEventListener('click', event => {
            if (event.target === queueColumn) closeQueue();
        });

        document.addEventListener('keydown', event => {
            if (event.key !== 'Escape' || !media.matches) return;
            if (queueColumn.classList.contains('mobile-queue-open')) closeQueue();
            else if (player.classList.contains('mobile-expanded')) collapsePlayer();
        });

        bindSwipeDown(queuePanel?.querySelector('.queue-heading'), closeQueue, () => queueColumn.classList.contains('mobile-queue-open'));
        bindSwipeDown(player.querySelector('.now-playing-copy'), collapsePlayer, () => player.classList.contains('mobile-expanded'));

        const stateObserver = new MutationObserver(() => {
            if (queuePanel?.hidden) closeQueue();
            if (player.hidden) collapsePlayer();
        });
        if (queuePanel) stateObserver.observe(queuePanel, { attributes: true, attributeFilter: ['hidden'] });
        stateObserver.observe(player, { attributes: true, attributeFilter: ['hidden'] });

        const handleViewportChange = () => {
            if (!media.matches) {
                closeQueue();
                collapsePlayer();
            }
            syncMobileViewport();
        };
        if (typeof media.addEventListener === 'function') media.addEventListener('change', handleViewportChange);
        else if (typeof media.addListener === 'function') media.addListener(handleViewportChange);
    }

    onReady(() => {
        bindViewportTracking();
        syncMobileHealthDots();
        bindMobileHeaderContext();
        bindMobileMoreMenu();
        bindDashboardMobileUI();
    });
})();
