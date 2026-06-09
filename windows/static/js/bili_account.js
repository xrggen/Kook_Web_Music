class BiliAccountManager {
    constructor() {
        this.qrData = {};
        this.qrTimer = null;
        this.init();
    }

    init() {
        this.bindEvents();
        this.checkLoginStatus();
    }

    bindEvents() {
        $('#bili-qr-refresh-btn').on('click', () => this.fetchQRCode());
        $('#bili-cookie-save-btn').on('click', () => this.saveCookie());
        $('#bili-logout-btn').on('click', () => this.logout());

        $('#bili-login-tabs a[data-bs-toggle="tab"]').on('shown.bs.tab', (e) => {
            if (e.target.getAttribute('href') === '#bili-qrcode-tab') {
                this.fetchQRCode();
            }
        });

        $('#platform-tabs button[data-bs-target="#platform-bili"]').on('shown.bs.tab', () => {
            this.checkLoginStatus();
        });
    }

    async checkLoginStatus() {
        try {
            const resp = await fetch('/api/bili/account/status');
            const data = await resp.json();
            if (data.logged_in) {
                this.showAccount(data);
            } else {
                this.showLogin();
            }
        } catch (e) {
            this.showLogin();
        }
    }

    showLogin() {
        $('#bili-login-section').show();
        $('#bili-account-section').hide();
        this.fetchQRCode();
    }

    showAccount(data) {
        $('#bili-login-section').hide();
        $('#bili-account-section').show();
        $('#bili-uid-display').text(data.uid || '未知');
        this.loadProfile();
        this.loadPlaylists();
    }

    async loadProfile() {
        try {
            const resp = await fetch('/api/bili/account/profile');
            const data = await resp.json();
            if (data.code === 200) {
                if (data.face) {
                    $('#bili-profile-avatar').attr('src', data.face).show();
                }
                $('#bili-profile-nickname').text(data.uname || 'B站用户');
                $('#bili-uid-display').text(data.uid || '');
                $('#bili-level-display').text(data.level || '--');
            }
        } catch (e) {
            console.error('B站用户详情加载失败:', e);
        }
    }

    async loadPlaylists() {
        try {
            const resp = await fetch('/api/bili/account/playlists');
            const data = await resp.json();
            if (data.code === 200 && data.playlists) {
                const list = data.playlists;
                $('#bili-playlist-count').text(list.length);
                if (!list.length) {
                    $('#bili-playlist-grid').html('<div class="col-12 text-center text-muted py-4">暂无收藏夹</div>');
                    return;
                }
                let html = '';
                list.forEach(pl => {
                    const name = pl.name || '未知收藏夹';
                    html += `<div class="col-md-4 col-lg-3">
                        <div class="card h-100" style="cursor:pointer"
                             onclick="window.open('https://www.bilibili.com/medialist/play/ml${pl.id}','_blank')">
                            <img src="${pl.cover || ''}" class="card-img-top" alt="${name}"
                                 onerror="this.style.display='none'">
                            <div class="card-body p-2">
                                <div class="fw-bold small text-truncate" title="${name}">${name}</div>
                                <div class="text-muted" style="font-size:.75rem">${pl.trackCount||0}个视频</div>
                            </div>
                        </div>
                    </div>`;
                });
                $('#bili-playlist-grid').html(html);
            }
        } catch (e) {
            console.error('B站收藏夹加载失败:', e);
        }
    }

    async fetchQRCode() {
        $('#bili-qr-image').hide();
        $('#bili-qr-loading').show();
        $('#bili-qr-expired').hide();
        $('#bili-qr-status').text('正在生成二维码...');
        if (this.qrTimer) { clearInterval(this.qrTimer); this.qrTimer = null; }

        try {
            const resp = await fetch('/api/bili/account/qr/create', { method: 'POST' });
            const data = await resp.json();
            if (data.qrcode) {
                // 服务端已生成 base64 PNG 二维码图片，直接使用
                $('#bili-qr-image').attr('src', data.qrcode).show();
                $('#bili-qr-loading').hide();
                this.qrData = { qrcode_key: data.qrcode_key };
                this.qrStartTime = Date.now();
                this.startQRPolling();
            } else {
                $('#bili-qr-loading').hide();
                $('#bili-qr-status').text('获取二维码失败: ' + (data.error || ''));
            }
        } catch (e) {
            $('#bili-qr-loading').hide();
            $('#bili-qr-status').text('网络异常，请重试');
        }
    }

    startQRPolling() {
        this.qrTimer = setInterval(() => this.checkQRStatus(), 2000);
    }

    async checkQRStatus() {
        // 3分钟超时自动停止
        if (Date.now() - this.qrStartTime > 180000) {
            clearInterval(this.qrTimer);
            this.qrTimer = null;
            $('#bili-qr-image').hide();
            $('#bili-qr-expired').show();
            $('#bili-qr-status').text('二维码已过期');
            return;
        }

        try {
            const resp = await fetch('/api/bili/account/qr/check', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.qrData)
            });
            const data = await resp.json();

            if (data.status === 'success') {
                clearInterval(this.qrTimer);
                this.qrTimer = null;
                $('#bili-qr-status').text('登录成功!');
                this.showToast('B站登录成功', 'success');
                setTimeout(() => this.checkLoginStatus(), 1000);
            } else if (data.status === 'scanned') {
                $('#bili-qr-status').text('已扫码，请在手机上确认');
            } else if (data.status === 'expired') {
                clearInterval(this.qrTimer);
                this.qrTimer = null;
                $('#bili-qr-image').hide();
                $('#bili-qr-expired').show();
                $('#bili-qr-status').text('二维码已过期');
            }
        } catch (e) {
            // keep polling
        }
    }

    async saveCookie() {
        const cookie = $('#bili-cookie-input').val().trim();
        if (!cookie) {
            $('#bili-cookie-save-msg').html('<span class="text-danger">请输入Cookie (SESSDATA)</span>');
            return;
        }
        try {
            const resp = await fetch('/api/bili/account/cookie', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cookie })
            });
            const data = await resp.json();
            if (data.code === 200) {
                $('#bili-cookie-save-msg').html('<span class="text-success">Cookie已保存</span>');
                this.showToast('B站Cookie已保存', 'success');
                this.checkLoginStatus();
            } else {
                $('#bili-cookie-save-msg').html('<span class="text-danger">' + (data.error || '保存失败') + '</span>');
            }
        } catch (e) {
            $('#bili-cookie-save-msg').html('<span class="text-danger">网络异常</span>');
        }
    }

    async logout() {
        try {
            await fetch('/api/bili/account/logout', { method: 'POST' });
            this.showToast('已退出B站登录', 'success');
            this.checkLoginStatus();
        } catch (e) {
            this.showToast('退出失败', 'danger');
        }
    }

    showToast(message, type) {
        $('#toast-message').text(message);
        const toast = $('#account-toast');
        toast.removeClass('text-bg-success text-bg-danger').addClass('text-bg-' + type);
        const bsToast = new bootstrap.Toast(document.getElementById('account-toast'));
        bsToast.show();
    }
}

$(document).ready(function() {
    new BiliAccountManager();
});
