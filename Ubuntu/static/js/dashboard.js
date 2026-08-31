'use strict';

let currentGuildId = null;
let currentGuildName = null;
let currentChannelId = null;
let currentPlatform = 'wy';

let currentChannels = [];
let playlistRequestSequence = 0;
let searchRequestSequence = 0;
let currentPlaybackModes = {
    single_repeat: false,
    playlist_repeat: false,
    shuffle: false
};

const PLATFORM_NAMES = {
    wy: '网易云',
    qq: 'QQ 音乐',
    bili: 'B 站'
};

document.addEventListener('DOMContentLoaded', () => {
    restorePreferences();
    bindEvents();
    syncPlatformUI();
    updateTargetUI();
    loadGuilds();

    window.setInterval(() => {
        if (currentChannelId) {
            loadPlaylist(currentChannelId, { quiet: true });
        }
    }, 5000);
});

function restorePreferences() {
    try {
        const savedPlatform = localStorage.getItem('currentPlatform');
        if (Object.prototype.hasOwnProperty.call(PLATFORM_NAMES, savedPlatform)) {
            currentPlatform = savedPlatform;
        }
        currentGuildId = localStorage.getItem('currentGuildId');
        currentGuildName = localStorage.getItem('currentGuildName');
        currentChannelId = localStorage.getItem('currentChannelId');
    } catch (error) {
        console.warn('无法恢复控制台偏好:', error);
    }
}

function persistPreference(key, value) {
    try {
        if (value) {
            localStorage.setItem(key, value);
        } else {
            localStorage.removeItem(key);
        }
    } catch (error) {
        console.warn(`无法保存偏好 ${key}:`, error);
    }
}

async function requestJSON(url, options = {}) {
    const response = await fetch(url, options);
    let data;

    try {
        data = await response.json();
    } catch (error) {
        throw new Error(`服务器返回了无法识别的响应（HTTP ${response.status}）`);
    }

    if (!response.ok) {
        throw new Error(data.error || `请求失败（HTTP ${response.status}）`);
    }
    return data;
}

async function loadGuilds() {
    const guildList = document.getElementById('guild-list');
    renderLoading(guildList, '正在加载服务器…');

    try {
        const data = await requestJSON('/api/guilds');
        if (!data.success) {
            throw new Error(data.error || '服务器列表加载失败');
        }
        await displayGuilds(data.guilds || []);
    } catch (error) {
        renderEmptyBlock(guildList, '无法加载服务器，请确认机器人已在线。');
        showError(error.message);
    }
}

async function displayGuilds(guilds) {
    const guildList = document.getElementById('guild-list');
    guildList.replaceChildren();

    if (!guilds.length) {
        renderEmptyBlock(guildList, '没有可用的服务器');
        clearTarget();
        return;
    }

    guilds.forEach(guild => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'guild-item';
        button.dataset.id = String(guild.id);
        button.setAttribute('aria-pressed', String(String(guild.id) === String(currentGuildId)));

        const avatar = document.createElement('span');
        avatar.className = 'guild-avatar';
        avatar.textContent = getInitial(guild.name);

        if (guild.icon) {
            const image = document.createElement('img');
            image.src = guild.icon;
            image.alt = '';
            image.loading = 'lazy';
            image.referrerPolicy = 'no-referrer';
            image.addEventListener('error', () => image.remove());
            avatar.appendChild(image);
        }

        const copy = document.createElement('span');
        copy.className = 'guild-copy';
        const name = document.createElement('strong');
        name.textContent = guild.name || '未命名服务器';
        const role = document.createElement('span');
        role.textContent = guild.master_id ? '可管理服务器' : 'KOOK 服务器';
        copy.append(name, role);

        const check = document.createElement('i');
        check.className = 'bi bi-check-lg guild-check';
        check.setAttribute('aria-hidden', 'true');

        button.append(avatar, copy, check);
        button.addEventListener('click', () => selectGuild(String(guild.id), guild.name || '未命名服务器'));
        guildList.appendChild(button);
    });

    const savedGuild = guilds.find(guild => String(guild.id) === String(currentGuildId));
    if (savedGuild) {
        await selectGuild(String(savedGuild.id), savedGuild.name || currentGuildName || '未命名服务器', {
            preserveChannel: true
        });
    } else {
        clearTarget();
    }
}

async function selectGuild(guildId, guildName, options = {}) {
    const guildChanged = String(currentGuildId) !== String(guildId);
    currentGuildId = String(guildId);
    currentGuildName = guildName;

    if (guildChanged && !options.preserveChannel) {
        currentChannelId = null;
        persistPreference('currentChannelId', null);
    }

    persistPreference('currentGuildId', currentGuildId);
    persistPreference('currentGuildName', currentGuildName);

    document.querySelectorAll('#guild-list .guild-item').forEach(item => {
        const active = item.dataset.id === currentGuildId;
        item.classList.toggle('active', active);
        item.setAttribute('aria-pressed', String(active));
    });

    document.getElementById('server-name').textContent = currentGuildName;
    setVisible('server-info-container', true);
    updateTargetUI();

    await loadChannels(currentGuildId);
}

function clearTarget() {
    currentGuildId = null;
    currentGuildName = null;
    currentChannelId = null;
    currentChannels = [];

    persistPreference('currentGuildId', null);
    persistPreference('currentGuildName', null);
    persistPreference('currentChannelId', null);

    setVisible('server-info-container', false);
    updateTargetUI();
    updatePlaylist([]);
    updatePlaybackModes({});
}

async function loadChannels(guildId) {
    const select = document.getElementById('voice-channel-select');
    select.disabled = true;
    select.replaceChildren(createOption('', '正在加载语音频道…'));

    try {
        const [channelData, statusData] = await Promise.all([
            requestJSON(`/api/channels?guild_id=${encodeURIComponent(guildId)}`),
            requestJSON(`/api/channels/active?guild_id=${encodeURIComponent(guildId)}`)
                .catch(() => ({ success: true, active: {} }))
        ]);

        if (String(guildId) !== String(currentGuildId)) {
            return;
        }
        if (!channelData.success) {
            throw new Error(channelData.error || '频道列表加载失败');
        }

        const active = statusData.active || {};
        currentChannels = (channelData.channels || []).map(channel => ({
            ...channel,
            id: String(channel.id),
            active: Boolean(active[channel.id]),
            playing: active[channel.id] === 'playing'
        }));
        displayChannels(currentChannels);
    } catch (error) {
        select.replaceChildren(createOption('', '无法加载语音频道'));
        showError(error.message);
    } finally {
        select.disabled = false;
    }
}

function displayChannels(channels) {
    const select = document.getElementById('voice-channel-select');
    select.replaceChildren(createOption('', channels.length ? '选择语音频道' : '没有可用的语音频道'));

    channels.forEach(channel => {
        let label = channel.name || '未命名语音频道';
        if (channel.active) {
            label = `${channel.playing ? '正在播放' : '已连接'} · ${label}`;
        }
        const option = createOption(channel.id, label);
        option.dataset.active = String(channel.active);
        option.dataset.playing = String(channel.playing);
        option.dataset.channelName = channel.name || '未命名语音频道';
        select.appendChild(option);
    });

    const savedExists = channels.some(channel => channel.id === String(currentChannelId));
    if (!savedExists) {
        const activeChannel = channels.find(channel => channel.active);
        currentChannelId = activeChannel ? activeChannel.id : null;
    }

    select.value = currentChannelId || '';
    persistPreference('currentChannelId', currentChannelId);
    updateTargetUI();

    if (currentChannelId) {
        loadPlaylist(currentChannelId);
    } else {
        updatePlaylist([]);
        updatePlaybackModes({});
    }
}

function handleChannelSelection() {
    const select = document.getElementById('voice-channel-select');
    currentChannelId = select.value || null;
    persistPreference('currentChannelId', currentChannelId);
    updateTargetUI();

    if (currentChannelId) {
        loadPlaylist(currentChannelId);
    } else {
        updatePlaylist([]);
        updatePlaybackModes({});
    }
}

function updateTargetUI() {
    const selectedChannel = getSelectedChannel();
    const hasGuild = Boolean(currentGuildId);
    const hasTarget = Boolean(currentGuildId && currentChannelId && selectedChannel);
    const channelName = selectedChannel?.name || '未选择语音频道';

    const summary = hasTarget
        ? `${currentGuildName} / ${channelName}`
        : hasGuild
            ? `${currentGuildName} / 请选择语音频道`
            : '请先选择服务器与语音频道';

    document.getElementById('target-summary').textContent = summary;
    document.getElementById('search-target-hint').textContent = hasTarget
        ? `将添加到：${channelName}`
        : '尚未选择频道';
    document.getElementById('player-channel-name').textContent = hasTarget
        ? `频道：${channelName}`
        : '频道：—';
    document.getElementById('target-status-dot').classList.toggle('ready', hasTarget);

    setVisible('dashboard-empty-state', !hasTarget);
    setVisible('music-search-container', hasTarget);
    setVisible('player-container', hasTarget);
    setVisible('playlist-container', hasTarget);
    if (!hasTarget) {
        setVisible('search-results', false);
    }

    const joinButton = document.getElementById('join-btn');
    const leaveButton = document.getElementById('leave-btn');
    const isActive = Boolean(selectedChannel?.active);
    joinButton.disabled = !hasTarget || isActive;
    leaveButton.disabled = !hasTarget || !isActive;
    setButtonLabel(
        joinButton,
        isActive ? 'bi-check-circle-fill' : 'bi-mic-fill',
        isActive ? '已在频道' : '加入频道'
    );

    [
        'play-btn',
        'pause-btn',
        'skip-btn',
        'playlist-repeat-btn',
        'stop-btn',
        'refresh-btn',
        'clear-playlist-btn',
        'search-btn',
        'playlist-btn'
    ].forEach(id => {
        const element = document.getElementById(id);
        if (element && !element.dataset.busy) {
            element.disabled = !hasTarget;
        }
    });
}

function getSelectedChannel() {
    return currentChannels.find(channel => channel.id === String(currentChannelId)) || null;
}

function getSelectedChannelName() {
    return getSelectedChannel()?.name || '所选频道';
}

async function loadPlaylist(channelId = currentChannelId, options = {}) {
    if (!channelId) {
        updatePlaylist([]);
        updatePlaybackModes({});
        return;
    }

    const requestChannelId = String(channelId);
    const sequence = ++playlistRequestSequence;

    try {
        const data = await requestJSON(
            `/api/playlist/current?channel_id=${encodeURIComponent(requestChannelId)}`
        );
        if (
            sequence !== playlistRequestSequence ||
            requestChannelId !== String(currentChannelId)
        ) {
            return;
        }
        if (!data.success) {
            throw new Error(data.error || '播放列表加载失败');
        }
        updatePlaylist(data.playlist || []);
        updatePlaybackModes(data.playback_modes || {});
    } catch (error) {
        if (!options.quiet) {
            showError(error.message);
        } else {
            console.warn('静默刷新播放列表失败:', error);
        }
    }
}

function updatePlaylist(playlist) {
    const playlistBody = document.getElementById('playlist-body');
    const nowPlaying = (playlist || []).find(item => item.playing);
    const queued = (playlist || []).filter(item => !item.playing);

    document.getElementById('queue-count').textContent = String(queued.length);
    updateNowPlaying(nowPlaying);
    playlistBody.replaceChildren();

    if (!queued.length) {
        appendTableMessage(playlistBody, 3, nowPlaying ? '当前歌曲之后暂无待播内容' : '播放列表为空');
        return;
    }

    queued.forEach((item, position) => {
        const row = document.createElement('tr');

        const indexCell = document.createElement('td');
        const index = document.createElement('span');
        index.className = 'queue-index';
        index.textContent = String(position + 1).padStart(2, '0');
        indexCell.appendChild(index);

        const trackCell = document.createElement('td');
        appendTrackCopy(
            trackCell,
            item.name || '未知歌曲',
            item.artist || '未知歌手'
        );

        const actionCell = document.createElement('td');
        actionCell.className = 'text-end';
        const removeButton = document.createElement('button');
        removeButton.type = 'button';
        removeButton.className = 'btn btn-sm btn-outline-danger remove-btn';
        removeButton.title = `从播放列表移除 ${item.name || '这首歌曲'}`;
        removeButton.setAttribute('aria-label', removeButton.title);
        const removeIcon = document.createElement('i');
        removeIcon.className = 'bi bi-x-lg';
        removeButton.appendChild(removeIcon);
        removeButton.addEventListener('click', () => removeFromPlaylist(item.queue_index ?? position));
        actionCell.appendChild(removeButton);

        row.append(indexCell, trackCell, actionCell);
        playlistBody.appendChild(row);
    });
}

function updateNowPlaying(item) {
    const playing = Boolean(item);
    document.getElementById('current-song').textContent = item?.name || '未播放';
    document.getElementById('current-artist').textContent = item?.artist || '等待添加歌曲';
    document.getElementById('playing-indicator').classList.toggle('active', playing);
    updateProgress(item?.position || 0, item?.duration || 0);
}

function bindEvents() {
    document.querySelectorAll('input[name="platform"]').forEach(radio => {
        radio.addEventListener('change', event => {
            currentPlatform = event.target.value;
            persistPreference('currentPlatform', currentPlatform);
            syncPlatformUI();
        });
    });

    document.getElementById('voice-channel-select').addEventListener('change', handleChannelSelection);
    document.getElementById('reload-guilds-btn').addEventListener('click', event => {
        runWithBusyButton(event.currentTarget, '刷新中', loadGuilds);
    });
    document.getElementById('refresh-btn').addEventListener('click', event => {
        runWithBusyButton(event.currentTarget, '刷新中', () => loadPlaylist(currentChannelId));
    });
    document.getElementById('join-btn').addEventListener('click', event => {
        joinChannel(event.currentTarget);
    });
    document.getElementById('leave-btn').addEventListener('click', event => {
        leaveChannel(event.currentTarget);
    });

    document.getElementById('search-btn').addEventListener('click', event => {
        searchFromInput(event.currentTarget);
    });
    document.getElementById('search-input').addEventListener('keydown', event => {
        if (event.key === 'Enter') {
            event.preventDefault();
            searchFromInput(document.getElementById('search-btn'));
        }
    });
    document.getElementById('playlist-btn').addEventListener('click', event => {
        importPlaylist(event.currentTarget);
    });
    document.getElementById('playlist-input').addEventListener('keydown', event => {
        if (event.key === 'Enter') {
            event.preventDefault();
            importPlaylist(document.getElementById('playlist-btn'));
        }
    });

    document.getElementById('play-btn').addEventListener('click', event => {
        runPlayerAction('/api/resume', '已继续播放', event.currentTarget);
    });
    document.getElementById('pause-btn').addEventListener('click', event => {
        runPlayerAction('/api/pause', '已暂停播放', event.currentTarget);
    });
    document.getElementById('skip-btn').addEventListener('click', event => {
        runPlayerAction('/api/skip', '已跳过当前歌曲', event.currentTarget);
    });
    document.getElementById('playlist-repeat-btn').addEventListener('click', event => {
        togglePlaylistRepeat(event.currentTarget);
    });
    document.getElementById('stop-btn').addEventListener('click', event => {
        runPlayerAction('/api/stop', '已停止播放', event.currentTarget);
    });
    document.getElementById('clear-playlist-btn').addEventListener('click', clearPlaylist);
}

function syncPlatformUI() {
    const radio = document.getElementById(`platform-${currentPlatform}`);
    if (radio) {
        radio.checked = true;
    }

    const playlistInput = document.getElementById('playlist-input');
    const placeholders = {
        wy: '网易云歌单 ID 或链接',
        qq: 'QQ 音乐歌单 ID 或链接',
        bili: 'B 站收藏夹 ID 或链接'
    };
    playlistInput.placeholder = placeholders[currentPlatform];
}

function searchFromInput(button) {
    const keyword = document.getElementById('search-input').value.trim();
    if (!keyword) {
        showError('请输入歌曲名称或歌手');
        document.getElementById('search-input').focus();
        return;
    }
    searchMusic(keyword, button);
}

async function searchMusic(keyword, button) {
    if (!ensureTarget()) {
        return;
    }

    const platform = currentPlatform;
    const sequence = ++searchRequestSequence;
    const resultsBody = document.getElementById('search-results-body');
    setVisible('search-results', true);
    document.getElementById('search-result-count').textContent = '搜索中';
    appendTableMessage(resultsBody, 4, `正在搜索${PLATFORM_NAMES[platform]}…`, true);
    setButtonBusy(button, true, '搜索中');

    try {
        const data = await requestJSON(
            `/api/search?keyword=${encodeURIComponent(keyword)}&platform=${encodeURIComponent(platform)}`
        );
        if (sequence !== searchRequestSequence) {
            return;
        }
        if (!data.success) {
            throw new Error(data.error || '搜索失败');
        }
        displaySearchResults(data.songs || [], platform);
    } catch (error) {
        if (sequence === searchRequestSequence) {
            appendTableMessage(resultsBody, 4, '搜索失败，请稍后重试');
            document.getElementById('search-result-count').textContent = '0 首';
            showError(error.message);
        }
    } finally {
        setButtonBusy(button, false);
    }
}

function displaySearchResults(songs, platform) {
    const resultsBody = document.getElementById('search-results-body');
    resultsBody.replaceChildren();
    document.getElementById('search-result-count').textContent = `${songs.length} 首`;

    if (!songs.length) {
        appendTableMessage(resultsBody, 4, '没有找到相关歌曲');
        return;
    }

    songs.forEach(song => {
        const artist = getSongArtist(song);
        const album = getSongAlbum(song, platform);
        const row = document.createElement('tr');

        const songCell = document.createElement('td');
        appendTrackCopy(songCell, song.name || '未知歌曲', `ID：${song.id || '—'}`);

        const artistCell = document.createElement('td');
        artistCell.textContent = artist;

        const albumCell = document.createElement('td');
        albumCell.textContent = album;

        const actionCell = document.createElement('td');
        actionCell.className = 'text-end';
        const addButton = document.createElement('button');
        addButton.type = 'button';
        addButton.className = 'btn btn-primary add-track-btn';
        setButtonLabel(addButton, 'bi-plus-lg', '添加到播放列表');
        addButton.title = `添加到 ${getSelectedChannelName()}`;
        addButton.addEventListener('click', () => addSongToPlaylist({
            id: song.id,
            name: song.name || '未知歌曲',
            artist,
            platform
        }, addButton));
        actionCell.appendChild(addButton);

        row.append(songCell, artistCell, albumCell, actionCell);
        resultsBody.appendChild(row);
    });
}

async function addSongToPlaylist(song, button) {
    if (!ensureTarget()) {
        return;
    }

    const targetGuildId = currentGuildId;
    const targetChannelId = currentChannelId;
    const targetChannelName = getSelectedChannelName();
    setButtonBusy(button, true, '添加中');

    try {
        const data = await requestJSON('/api/playlist/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                guild_id: targetGuildId,
                channel_id: targetChannelId,
                song_id: song.id,
                song_name: song.name,
                artist_name: song.artist,
                platform: song.platform
            })
        });
        if (!data.success) {
            throw new Error(data.error || '添加歌曲失败');
        }

        showSuccess(`《${song.name}》已添加到 ${targetChannelName}`);
        setButtonBusy(button, false);
        setButtonLabel(button, 'bi-check-lg', '已添加');
        button.disabled = true;

        if (String(targetChannelId) === String(currentChannelId)) {
            await loadPlaylist(targetChannelId);
        }

        window.setTimeout(() => {
            setButtonLabel(button, 'bi-plus-lg', '添加到播放列表');
            button.disabled = false;
        }, 1200);
    } catch (error) {
        setButtonBusy(button, false);
        showError(error.message);
    }
}

async function importPlaylist(button) {
    if (!ensureTarget()) {
        return;
    }

    const input = document.getElementById('playlist-input');
    const rawValue = input.value.trim();
    const playlistId = extractPlaylistId(rawValue, currentPlatform);
    if (!playlistId) {
        showError('请输入有效的歌单或收藏夹 ID / 链接');
        input.focus();
        return;
    }

    const targetGuildId = currentGuildId;
    const targetChannelId = currentChannelId;
    const targetChannelName = getSelectedChannelName();
    const platform = currentPlatform;
    setButtonBusy(button, true, '导入中');

    try {
        const data = await requestJSON('/api/playlist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                guild_id: targetGuildId,
                channel_id: targetChannelId,
                playlist_id: playlistId,
                platform
            })
        });
        if (!data.success) {
            throw new Error(data.error || '导入歌单失败');
        }
        showSuccess(`已向 ${targetChannelName} 添加 ${data.count || 0} 首歌曲`);
        input.value = '';
        if (String(targetChannelId) === String(currentChannelId)) {
            await loadPlaylist(targetChannelId);
        }
    } catch (error) {
        showError(error.message);
    } finally {
        setButtonBusy(button, false);
    }
}

function extractPlaylistId(value, platform) {
    if (!value) {
        return null;
    }
    if (/^[A-Za-z0-9_-]+$/.test(value)) {
        return value;
    }

    const patterns = platform === 'qq'
        ? [/\/playlist\/(\d+)/, /[?&]id=(\d+)/, /[?&]disstid=(\d+)/]
        : platform === 'bili'
            ? [/[?&](?:id|fid|media_id)=(\d+)/, /\/favlist\?fid=(\d+)/]
            : [/[?&]id=(\d+)/, /\/playlist\/(\d+)/];

    for (const pattern of patterns) {
        const match = value.match(pattern);
        if (match) {
            return match[1];
        }
    }
    return null;
}

async function joinChannel(button) {
    if (!ensureTarget()) {
        return;
    }

    const guildId = currentGuildId;
    const channelId = currentChannelId;
    const channelName = getSelectedChannelName();
    setButtonBusy(button, true, '连接中');

    try {
        const data = await postChannelAction('/api/join', guildId, channelId);
        if (!data.success) {
            throw new Error(data.error || '加入频道失败');
        }
        showSuccess(`已加入 ${channelName}`);
        await loadChannels(guildId);
    } catch (error) {
        showError(error.message);
    } finally {
        setButtonBusy(button, false);
        updateTargetUI();
    }
}

async function leaveChannel(button) {
    if (!ensureTarget()) {
        return;
    }

    const guildId = currentGuildId;
    const channelId = currentChannelId;
    const channelName = getSelectedChannelName();
    setButtonBusy(button, true, '离开中');

    try {
        const data = await postChannelAction('/api/leave', guildId, channelId);
        if (!data.success) {
            throw new Error(data.error || '离开频道失败');
        }
        showSuccess(`已离开 ${channelName}`);
        await loadChannels(guildId);
        await loadPlaylist(channelId);
    } catch (error) {
        showError(error.message);
    } finally {
        setButtonBusy(button, false);
        updateTargetUI();
    }
}

async function runPlayerAction(endpoint, successMessage, button) {
    if (!ensureTarget()) {
        return;
    }

    const guildId = currentGuildId;
    const channelId = currentChannelId;
    setButtonBusy(button, true, '处理中');
    try {
        const data = await postChannelAction(endpoint, guildId, channelId);
        if (!data.success) {
            throw new Error(data.error || '操作失败');
        }
        showSuccess(successMessage);
        await loadPlaylist(channelId);
    } catch (error) {
        showError(error.message);
    } finally {
        setButtonBusy(button, false);
        updateTargetUI();
    }
}

async function togglePlaylistRepeat(button) {
    if (!ensureTarget()) {
        return;
    }

    const guildId = currentGuildId;
    const channelId = currentChannelId;
    setButtonBusy(button, true, '切换中');

    try {
        const data = await postChannelAction('/api/playlist/repeat', guildId, channelId);
        if (!data.success) {
            throw new Error(data.error || '切换列表循环失败');
        }
        updatePlaybackModes(data.playback_modes || {
            playlist_repeat: Boolean(data.enabled)
        });
        showSuccess(data.enabled
            ? '列表循环已开启，当前歌曲播完后会移至队尾'
            : '列表循环已关闭');
    } catch (error) {
        showError(error.message);
    } finally {
        setButtonBusy(button, false);
        updatePlaybackModes(currentPlaybackModes);
        updateTargetUI();
    }
}

async function clearPlaylist() {
    if (!ensureTarget() || !window.confirm(`确定清空 ${getSelectedChannelName()} 的待播列表吗？`)) {
        return;
    }

    const guildId = currentGuildId;
    const channelId = currentChannelId;
    const button = document.getElementById('clear-playlist-btn');
    setButtonBusy(button, true, '清空中');

    try {
        const data = await postChannelAction('/api/clear', guildId, channelId);
        if (!data.success) {
            throw new Error(data.error || '清空播放列表失败');
        }
        showSuccess('待播列表已清空');
        await loadPlaylist(channelId);
    } catch (error) {
        showError(error.message);
    } finally {
        setButtonBusy(button, false);
        updateTargetUI();
    }
}

async function removeFromPlaylist(index) {
    if (!ensureTarget() || !window.confirm('确定从播放列表移除这首歌曲吗？')) {
        return;
    }

    const guildId = currentGuildId;
    const channelId = currentChannelId;
    try {
        const data = await requestJSON('/api/remove', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                guild_id: guildId,
                channel_id: channelId,
                index
            })
        });
        if (!data.success) {
            throw new Error(data.error || '移除歌曲失败');
        }
        showSuccess('歌曲已从播放列表移除');
        await loadPlaylist(channelId);
    } catch (error) {
        showError(error.message);
    }
}

function postChannelAction(endpoint, guildId, channelId) {
    return requestJSON(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            guild_id: guildId,
            channel_id: channelId
        })
    });
}

function updatePlayerStatus(data) {
    if (data.playing) {
        updateNowPlaying({
            name: data.song_name || '未知歌曲',
            artist: data.artist_name || '未知歌手',
            position: data.position || 0,
            duration: data.duration || 0
        });
    } else {
        updateNowPlaying(null);
    }
}

function updatePlaybackModes(modes = {}) {
    currentPlaybackModes = {
        single_repeat: Boolean(modes.single_repeat),
        playlist_repeat: Boolean(modes.playlist_repeat),
        shuffle: Boolean(modes.shuffle)
    };

    const button = document.getElementById('playlist-repeat-btn');
    if (!button) {
        return;
    }

    const enabled = currentPlaybackModes.playlist_repeat;
    button.classList.toggle('active', enabled);
    button.setAttribute('aria-pressed', String(enabled));
    button.title = enabled ? '关闭列表循环' : '开启列表循环';
    if (button.dataset.busy !== 'true') {
        setButtonLabel(button, 'bi-repeat', enabled ? '循环中' : '列表循环');
    }
}

function updateProgress(position, totalSeconds = 0) {
    const safePosition = Math.max(0, Number(position) || 0);
    const safeTotal = Math.max(0, Number(totalSeconds) || 0);
    document.getElementById('current-time').textContent = formatDuration(safePosition);
    document.getElementById('total-time').textContent = formatDuration(safeTotal);

    const percentage = safeTotal > 0
        ? Math.min(100, (safePosition / safeTotal) * 100)
        : 0;
    document.getElementById('song-progress').style.width = `${percentage}%`;
}

function formatDuration(seconds) {
    const value = Math.max(0, Math.floor(Number(seconds) || 0));
    const minutes = Math.floor(value / 60);
    const remainingSeconds = value % 60;
    return `${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`;
}

function getSongArtist(song) {
    if (Array.isArray(song.ar) && song.ar.length) {
        return song.ar.map(artist => artist?.name).filter(Boolean).join('、') || '未知歌手';
    }
    return song.artist || song.author || '未知歌手';
}

function getSongAlbum(song, platform) {
    if (song.al?.name) {
        return song.al.name;
    }
    return song.album || song.source || PLATFORM_NAMES[platform] || '—';
}

function appendTrackCopy(container, primaryText, secondaryText) {
    const primary = document.createElement('span');
    primary.className = 'track-primary';
    primary.textContent = primaryText;
    const secondary = document.createElement('span');
    secondary.className = 'track-secondary';
    secondary.textContent = secondaryText;
    container.append(primary, secondary);
}

function appendTableMessage(tbody, colspan, message, loading = false) {
    tbody.replaceChildren();
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = colspan;
    cell.className = 'empty-table-cell';

    if (loading) {
        const spinner = document.createElement('span');
        spinner.className = 'spinner-border spinner-border-sm me-2';
        spinner.setAttribute('aria-hidden', 'true');
        cell.appendChild(spinner);
    }
    cell.appendChild(document.createTextNode(message));
    row.appendChild(cell);
    tbody.appendChild(row);
}

function renderLoading(container, message) {
    container.replaceChildren();
    const loading = document.createElement('div');
    loading.className = 'dashboard-loading';
    const spinner = document.createElement('span');
    spinner.className = 'spinner-border spinner-border-sm';
    spinner.setAttribute('aria-hidden', 'true');
    const text = document.createElement('span');
    text.textContent = message;
    loading.append(spinner, text);
    container.appendChild(loading);
}

function renderEmptyBlock(container, message) {
    container.replaceChildren();
    const block = document.createElement('div');
    block.className = 'dashboard-loading';
    block.textContent = message;
    container.appendChild(block);
}

function createOption(value, text) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = text;
    return option;
}

function getInitial(value) {
    const text = String(value || 'K').trim();
    return text.slice(0, 1).toUpperCase();
}

function ensureTarget() {
    if (!currentGuildId) {
        showError('请先选择 KOOK 服务器');
        return false;
    }
    if (!currentChannelId || !getSelectedChannel()) {
        showError('请先选择要操作的语音频道');
        return false;
    }
    return true;
}

function setVisible(id, visible) {
    const element = document.getElementById(id);
    if (element) {
        element.hidden = !visible;
    }
}

async function runWithBusyButton(button, busyLabel, action) {
    setButtonBusy(button, true, busyLabel);
    try {
        await action();
    } finally {
        setButtonBusy(button, false);
        updateTargetUI();
    }
}

function setButtonBusy(button, busy, busyLabel = '处理中') {
    if (!button) {
        return;
    }

    if (busy) {
        if (button.dataset.busy === 'true') {
            return;
        }
        button.dataset.busy = 'true';
        button.dataset.originalHtml = button.innerHTML;
        button.disabled = true;
        button.replaceChildren();
        const spinner = document.createElement('span');
        spinner.className = 'spinner-border spinner-border-sm';
        spinner.setAttribute('aria-hidden', 'true');
        const label = document.createElement('span');
        label.textContent = busyLabel;
        button.append(spinner, label);
    } else {
        if (button.dataset.originalHtml) {
            button.innerHTML = button.dataset.originalHtml;
        }
        delete button.dataset.busy;
        delete button.dataset.originalHtml;
        button.disabled = false;
    }
}

function setButtonLabel(button, iconClass, label) {
    button.replaceChildren();
    const icon = document.createElement('i');
    icon.className = `bi ${iconClass}`;
    icon.setAttribute('aria-hidden', 'true');
    const text = document.createElement('span');
    text.textContent = label;
    button.append(icon, text);
}

function showSuccess(message) {
    showNotice(message, 'success');
}

function showError(message) {
    console.error(message);
    showNotice(message, 'error');
}

function showNotice(message, type) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `dashboard-toast ${type}`;
    toast.setAttribute('role', type === 'error' ? 'alert' : 'status');

    const iconWrap = document.createElement('span');
    iconWrap.className = 'dashboard-toast-icon';
    const icon = document.createElement('i');
    icon.className = type === 'error' ? 'bi bi-exclamation-lg' : 'bi bi-check-lg';
    iconWrap.appendChild(icon);

    const copy = document.createElement('span');
    copy.className = 'dashboard-toast-message';
    copy.textContent = message;

    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'dashboard-toast-close';
    close.setAttribute('aria-label', '关闭提示');
    const closeIcon = document.createElement('i');
    closeIcon.className = 'bi bi-x-lg';
    close.appendChild(closeIcon);
    close.addEventListener('click', () => toast.remove());

    toast.append(iconWrap, copy, close);
    container.appendChild(toast);

    window.setTimeout(() => {
        toast.remove();
    }, type === 'error' ? 6500 : 4000);
}
