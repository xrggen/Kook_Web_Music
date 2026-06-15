class QQAccountManager {
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
        $('#qq-qr-refresh-btn').on('click', () => this.fetchQRCode());
        $('#qq-cookie-save-btn').on('click', () => this.saveCookie());
        $('#qq-logout-btn').on('click', () => this.logout());

        $('#qq-login-tabs a[data-bs-toggle="tab"]').on('shown.bs.tab', (e) => {
            if (e.target.getAttribute('href') === '#qq-qrcode-tab') {
                this.fetchQRCode();
            }
        });

        $('#platform-tabs button[data-bs-target="#platform-qq"]').on('shown.bs.tab', () => {
            this.checkLoginStatus();
        });
    }

    async checkLoginStatus() {
        try {
            const resp = await fetch('/api/qq/account/status');
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
        $('#qq-login-section').show();
        $('#qq-account-section').hide();
        this.fetchQRCode();
    }

    showAccount(data) {
        $('#qq-login-section').hide();
        $('#qq-account-section').show();
        $('#qq-uin-display').text(data.uin || '未知');
        // 显示 Cookie 有效期
        const exp = data.expires_in;
        if (exp > 0) {
            const d = Math.floor(exp / 86400);
            const h = Math.floor((exp % 86400) / 3600);
            $('#qq-expiry-display').text(d > 0 ? `${d}天${h}小时` : `${h}小时`).removeClass('text-danger').addClass('text-success');
        } else if (exp === 0) {
            $('#qq-expiry-display').text('已过期').removeClass('text-success').addClass('text-danger');
        } else {
            $('#qq-expiry-display').text('—');
        }
        this.loadProfile();
        this.loadPlaylists();
    }

    async loadProfile() {
        try {
            const resp = await fetch('/api/qq/account/profile');
            const data = await resp.json();
            if (data.code === 200) {
                if (data.avatar) {
                    $('#qq-profile-avatar').attr('src', data.avatar).show();
                }
                $('#qq-profile-nickname').text(data.nickname || 'QQ用户');
                $('#qq-uin-display').text(data.uin || '');
            }
        } catch (e) {
            console.error('QQ用户详情加载失败:', e);
        }
    }

    async loadPlaylists() {
        try {
            const resp = await fetch('/api/qq/account/playlists');
            const data = await resp.json();
            if (data.code === 200 && data.playlists) {
                const list = data.playlists;
                $('#qq-playlist-count').text(list.length);
                $('#qq-stat-playlists').text(list.length);
                if (!list.length) {
                    $('#qq-playlist-grid').html('<div class="col-12 text-center text-muted py-4">暂无歌单</div>');
                    return;
                }
                let html = '';
                list.forEach(pl => {
                    const name = pl.name || '未知歌单';
                    html += `<div class="col-md-4 col-lg-3">
                        <div class="card h-100" style="cursor:pointer"
                             onclick="window.open('https://y.qq.com/n/ryqq/playlist/${pl.id}','_blank')">
                            <img src="${pl.cover || ''}" class="card-img-top" alt="${name}"
                                 onerror="this.style.display='none'">
                            <div class="card-body p-2">
                                <div class="fw-bold small text-truncate" title="${name}">${name}</div>
                                <div class="text-muted" style="font-size:.75rem">${pl.trackCount||0}首 · ${(pl.playCount||0).toLocaleString()}次</div>
                            </div>
                        </div>
                    </div>`;
                });
                $('#qq-playlist-grid').html(html);
            }
        } catch (e) {
            console.error('QQ歌单加载失败:', e);
        }
    }

    async fetchQRCode() {
        $('#qq-qr-image').hide();
        $('#qq-qr-loading').show();
        $('#qq-qr-expired').hide();
        $('#qq-qr-status').text('正在生成二维码...');
        if (this.qrTimer) { clearInterval(this.qrTimer); this.qrTimer = null; }

        try {
            const resp = await fetch('/api/qq/account/qr/create', { method: 'POST' });
            const data = await resp.json();
            if (data.qrcode) {
                $('#qq-qr-image').attr('src', data.qrcode).show();
                $('#qq-qr-loading').hide();
                this.qrData = { ptqrtoken: data.ptqrtoken, qrsig: data.qrsig };
                this.startQRPolling();
            } else {
                $('#qq-qr-loading').hide();
                $('#qq-qr-status').text('获取二维码失败: ' + (data.error || ''));
            }
        } catch (e) {
            $('#qq-qr-loading').hide();
            $('#qq-qr-status').text('网络异常，请重试');
        }
    }

    startQRPolling() {
        this.qrTimer = setInterval(() => this.checkQRStatus(), 2000);
    }

    async checkQRStatus() {
        try {
            const resp = await fetch('/api/qq/account/qr/check', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.qrData)
            });
            const data = await resp.json();

            if (data.status === 'success') {
                clearInterval(this.qrTimer);
                this.qrTimer = null;
                $('#qq-qr-status').text('登录成功!');
                this.showToast('QQ音乐登录成功', 'success');
                setTimeout(() => this.checkLoginStatus(), 1000);
            } else if (data.status === 'scanned') {
                $('#qq-qr-status').text('已扫码，请在手机上确认授权');
            } else if (data.status === 'expired') {
                clearInterval(this.qrTimer);
                this.qrTimer = null;
                $('#qq-qr-image').hide();
                $('#qq-qr-expired').show();
                $('#qq-qr-status').text('二维码已过期');
            }
        } catch (e) {
            // keep polling
        }
    }

    async saveCookie() {
        const cookie = $('#qq-cookie-input').val().trim();
        if (!cookie) {
            $('#qq-cookie-save-msg').html('<span class="text-danger">请输入Cookie</span>');
            return;
        }
        try {
            const resp = await fetch('/api/qq/account/cookie', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cookie })
            });
            const data = await resp.json();
            if (data.code === 200) {
                $('#qq-cookie-save-msg').html('<span class="text-success">Cookie已保存</span>');
                this.showToast('QQ音乐Cookie已保存', 'success');
                this.checkLoginStatus();
            } else {
                $('#qq-cookie-save-msg').html('<span class="text-danger">' + (data.error || '保存失败') + '</span>');
            }
        } catch (e) {
            $('#qq-cookie-save-msg').html('<span class="text-danger">网络异常</span>');
        }
    }

    async logout() {
        try {
            await fetch('/api/qq/account/logout', { method: 'POST' });
            this.showToast('已退出QQ音乐登录', 'success');
            this.showLogin();
        } catch (e) {
            this.showToast('退出失败', 'danger');
        }
    }

    showToast(msg, type) {
        const toastEl = $('#account-toast');
        toastEl.removeClass('text-bg-success text-bg-danger text-bg-info')
               .addClass('text-bg-' + (type || 'success'));
        $('#toast-message').text(msg);
        const toast = new bootstrap.Toast(toastEl[0]);
        toast.show();
    }
}

$(function() {
    new QQAccountManager();
});
