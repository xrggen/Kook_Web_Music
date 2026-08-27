'use strict';

const libraryState = {
    items: [],
    filter: 'all',
    loadedPlatforms: 0,
    connectedPlatforms: 0
};

const PLATFORM_META = {
    wy: { name: '网易云音乐', badge: '网易云', icon: 'bi-music-note' },
    qq: { name: 'QQ 音乐', badge: 'QQ 音乐', icon: 'bi-music-note-beamed' },
    bili: { name: 'Bilibili', badge: 'Bilibili', icon: 'bi-play-btn' }
};

document.addEventListener('DOMContentLoaded', () => {
    bindLibraryEvents();
    loadLibrary();
});

function bindLibraryEvents() {
    document.getElementById('library-refresh-btn')?.addEventListener('click', event => {
        const button = event.currentTarget;
        button.disabled = true;
        button.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span><span>刷新中</span>';
        loadLibrary().finally(() => {
            button.disabled = false;
            button.innerHTML = '<i class="bi bi-arrow-clockwise"></i><span>刷新音乐库</span>';
        });
    });

    document.querySelectorAll('#library-filter button').forEach(button => {
        button.addEventListener('click', () => {
            libraryState.filter = button.dataset.platform || 'all';
            document.querySelectorAll('#library-filter button').forEach(item => {
                item.classList.toggle('active', item === button);
            });
            renderLibrary();
        });
    });
}

async function loadLibrary() {
    libraryState.items = [];
    libraryState.loadedPlatforms = 0;
    libraryState.connectedPlatforms = 0;
    setLoadingState();

    const results = await Promise.allSettled([
        loadNeteaseLibrary(),
        loadQQLibrary(),
        loadBiliLibrary()
    ]);

    results.forEach(result => {
        if (result.status === 'fulfilled' && Array.isArray(result.value)) {
            libraryState.items.push(...result.value);
        }
    });

    renderLibrary();
}

async function loadNeteaseLibrary() {
    const statusElement = document.getElementById('library-wy-status');
    const nameElement = document.getElementById('library-wy-name');
    try {
        const statusResponse = await fetch('/api/account/status');
        const status = await statusResponse.json();
        const data = status?.data || {};
        const account = data.account || null;
        const profile = data.profile || {};
        const uid = profile.userId || account?.id;
        if (!uid) {
            setPlatformStatus(statusElement, '未连接', 'error');
            nameElement.textContent = '网易云音乐';
            return [];
        }

        libraryState.connectedPlatforms += 1;
        setPlatformStatus(statusElement, '已连接', 'connected');
        nameElement.textContent = profile.nickname || '网易云音乐';

        const playlistResponse = await fetch(`/api/account/playlists?uid=${encodeURIComponent(uid)}&limit=100`);
        const playlistData = await playlistResponse.json();
        const playlists = Array.isArray(playlistData.playlist) ? playlistData.playlist : [];
        return playlists.map(item => ({
            platform: 'wy',
            id: String(item.id || ''),
            name: item.name || '未命名歌单',
            cover: item.coverImgUrl || '',
            count: Number(item.trackCount || 0),
            unit: '首',
            owner: item.creator?.nickname || profile.nickname || '',
            externalUrl: item.id ? `https://music.163.com/#/playlist?id=${encodeURIComponent(item.id)}` : ''
        }));
    } catch (error) {
        console.error('网易云音乐库加载失败:', error);
        setPlatformStatus(statusElement, '读取失败', 'error');
        return [];
    } finally {
        libraryState.loadedPlatforms += 1;
    }
}

async function loadQQLibrary() {
    const statusElement = document.getElementById('library-qq-status');
    const nameElement = document.getElementById('library-qq-name');
    try {
        const statusResponse = await fetch('/api/qq/account/status');
        const status = await statusResponse.json();
        if (!status.logged_in) {
            setPlatformStatus(statusElement, '未连接', 'error');
            nameElement.textContent = 'QQ 音乐';
            return [];
        }

        libraryState.connectedPlatforms += 1;
        setPlatformStatus(statusElement, '已连接', 'connected');
        nameElement.textContent = status.uin ? `QQ ${status.uin}` : 'QQ 音乐';

        const response = await fetch('/api/qq/account/playlists');
        const data = await response.json();
        const playlists = Array.isArray(data.playlists) ? data.playlists : [];
        return playlists.map(item => ({
            platform: 'qq',
            id: String(item.id || ''),
            name: item.name || '未命名歌单',
            cover: item.cover || '',
            count: Number(item.trackCount || 0),
            unit: '首',
            owner: '',
            externalUrl: item.id ? `https://y.qq.com/n/ryqq/playlist/${encodeURIComponent(item.id)}` : ''
        }));
    } catch (error) {
        console.error('QQ音乐库加载失败:', error);
        setPlatformStatus(statusElement, '读取失败', 'error');
        return [];
    } finally {
        libraryState.loadedPlatforms += 1;
    }
}

async function loadBiliLibrary() {
    const statusElement = document.getElementById('library-bili-status');
    const nameElement = document.getElementById('library-bili-name');
    try {
        const statusResponse = await fetch('/api/bili/account/status');
        const status = await statusResponse.json();
        if (!status.logged_in) {
            setPlatformStatus(statusElement, '未连接', 'error');
            nameElement.textContent = 'Bilibili';
            return [];
        }

        libraryState.connectedPlatforms += 1;
        setPlatformStatus(statusElement, '已连接', 'connected');
        nameElement.textContent = status.uname || 'Bilibili';

        const response = await fetch('/api/bili/account/playlists');
        const data = await response.json();
        const playlists = Array.isArray(data.playlists) ? data.playlists : [];
        return playlists.map(item => ({
            platform: 'bili',
            id: String(item.id || ''),
            name: item.name || '未命名收藏夹',
            cover: item.cover || '',
            count: Number(item.trackCount || 0),
            unit: '个视频',
            owner: status.uname || '',
            externalUrl: item.id ? `https://www.bilibili.com/medialist/play/ml${encodeURIComponent(item.id)}` : ''
        }));
    } catch (error) {
        console.error('Bilibili音乐库加载失败:', error);
        setPlatformStatus(statusElement, '读取失败', 'error');
        return [];
    } finally {
        libraryState.loadedPlatforms += 1;
    }
}

function setLoadingState() {
    ['wy', 'qq', 'bili'].forEach(platform => {
        setPlatformStatus(document.getElementById(`library-${platform}-status`), '检测中', '');
    });
    document.getElementById('library-summary').textContent = '正在读取已连接平台…';
    document.getElementById('library-count').textContent = '0 个收藏';
    const grid = document.getElementById('library-grid');
    grid.replaceChildren(createEmptyState('bi-arrow-repeat', '正在加载音乐库', '会同时检查三个平台的账号连接状态，并读取可用歌单或收藏夹。'));
}

function renderLibrary() {
    const grid = document.getElementById('library-grid');
    const items = libraryState.filter === 'all'
        ? libraryState.items
        : libraryState.items.filter(item => item.platform === libraryState.filter);

    document.getElementById('library-count').textContent = `${items.length} 个收藏`;
    document.getElementById('library-summary').textContent = libraryState.connectedPlatforms
        ? `已连接 ${libraryState.connectedPlatforms}/3 个平台，共读取 ${libraryState.items.length} 个歌单或收藏夹。`
        : '尚未检测到已连接的音乐账号。';

    grid.replaceChildren();
    if (!items.length) {
        const message = libraryState.connectedPlatforms
            ? '当前筛选下没有可显示的歌单或收藏夹。'
            : '请先前往“音乐账号”连接至少一个平台，连接后这里会自动汇总你的音乐库。';
        grid.appendChild(createEmptyState('bi-collection-play', '音乐库为空', message));
        return;
    }

    items.forEach(item => grid.appendChild(createLibraryCard(item)));
}

function createLibraryCard(item) {
    const article = document.createElement('article');
    article.className = 'library-card';
    article.dataset.platform = item.platform;

    const cover = document.createElement('div');
    cover.className = 'library-cover';
    const fallback = document.createElement('span');
    fallback.className = 'library-cover-fallback';
    const fallbackIcon = document.createElement('i');
    fallbackIcon.className = `bi ${PLATFORM_META[item.platform]?.icon || 'bi-music-note'}`;
    fallback.appendChild(fallbackIcon);
    cover.appendChild(fallback);

    if (item.cover) {
        const image = document.createElement('img');
        image.src = normalizeCoverUrl(item.cover);
        image.alt = '';
        image.loading = 'lazy';
        image.referrerPolicy = 'no-referrer';
        image.addEventListener('load', () => fallback.remove());
        image.addEventListener('error', () => image.remove());
        cover.appendChild(image);
    }

    const body = document.createElement('div');
    body.className = 'library-card-body';
    const title = document.createElement('div');
    title.className = 'library-card-title';
    title.textContent = item.name;
    title.title = item.name;

    const meta = document.createElement('div');
    meta.className = 'library-card-meta';
    const owner = item.owner ? ` · ${item.owner}` : '';
    meta.textContent = `${PLATFORM_META[item.platform]?.badge || item.platform} · ${item.count}${item.unit}${owner}`;

    const actions = document.createElement('div');
    actions.className = 'library-card-actions';

    const playButton = document.createElement('button');
    playButton.type = 'button';
    playButton.className = 'primary';
    playButton.innerHTML = '<i class="bi bi-box-arrow-in-right"></i><span>带到播放页</span>';
    playButton.addEventListener('click', () => handoffToDashboard(item));
    actions.appendChild(playButton);

    if (item.externalUrl) {
        const external = document.createElement('a');
        external.href = item.externalUrl;
        external.target = '_blank';
        external.rel = 'noopener noreferrer';
        external.innerHTML = '<i class="bi bi-box-arrow-up-right"></i><span>来源</span>';
        actions.appendChild(external);
    }

    body.append(title, meta, actions);
    article.append(cover, body);
    return article;
}

function handoffToDashboard(item) {
    try {
        localStorage.setItem('kookLibraryImportIntent', JSON.stringify({
            platform: item.platform,
            playlistId: item.id,
            name: item.name,
            createdAt: Date.now()
        }));
    } catch (error) {
        console.warn('无法保存音乐库导入意图:', error);
    }
    window.location.href = '/dashboard';
}

function createEmptyState(iconClass, titleText, copyText) {
    const wrapper = document.createElement('div');
    wrapper.className = 'library-empty';
    const icon = document.createElement('i');
    icon.className = `bi ${iconClass}`;
    const title = document.createElement('strong');
    title.textContent = titleText;
    const copy = document.createElement('p');
    copy.textContent = copyText;
    wrapper.append(icon, title, copy);
    return wrapper;
}

function setPlatformStatus(element, text, stateClass) {
    if (!element) return;
    element.textContent = text;
    element.classList.remove('connected', 'error');
    if (stateClass) element.classList.add(stateClass);
}

function normalizeCoverUrl(value) {
    if (!value) return '';
    if (value.startsWith('//')) return `https:${value}`;
    return value;
}
