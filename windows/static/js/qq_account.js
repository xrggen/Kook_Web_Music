function qqSafeImageUrl(value) {
    try {
        const url = new URL(String(value || ''), window.location.origin);
        return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
    } catch (_) {
        return '';
    }
}

function qqSafeQrImage(value) {
    const text = String(value || '');
    return text.length <= 1400000 && /^data:image\/png;base64,[A-Za-z0-9+/=\s]+$/.test(text) ? text : '';
}

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
        $('#qq-profile-avatar').on('error', function() { $(this).hide(); });
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

        const expiry = $('#qq-expiry-display');
        const exp = data.expires_in;
        let expiryText = '—';
        if (exp > 0) {
            const d = Math.floor(exp / 86400);
            const h = Math.floor((exp % 86400) / 3600);
            expiryText = d > 0 ? `${d}天${h}小时` : `${h}小时`;
            expiry.removeClass('text-danger text-warning').addClass('text-success');
        } else if (exp === 0) {
            expiryText = '已过期';
            expiry.removeClass('text-success text-warning').addClass('text-danger');
        } else {
            expiry.removeClass('text-danger text-warning').addClass('text-success');
        }

        if (data.refresh_supported) {
            expiryText += ' · 自动续期';
        } else if (data.logged_in) {
            expiryText += ' · 自动检查';
        }
        expiry.text(expiryText);
        expiry.attr('title', data.message || '');

        this.loadProfile();
        this.loadPlaylists();
    }

    async loadProfile() {
        try {
            const resp = await fetch('/api/qq/account/profile');
            const data = await resp.json();
            if (data.code === 200) {
                if (data.avatar) {
                    const avatar = qqSafeImageUrl(data.avatar);
                    if (avatar) $('#qq-profile-avatar').attr('src', avatar).show();
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
                const grid = $('#qq-playlist-grid').empty();
                list.forEach(pl => {
                    const name = String(pl.name || '未知歌单');
                    const targetUrl = `https://y.qq.com/n/ryqq/playlist/${encodeURIComponent(String(pl.id || ''))}`;
                    const card = $('<div>', { class: 'card h-100', role: 'link', tabindex: 0 })
                        .css('cursor', 'pointer')
                        .on('click keydown', event => {
                            if (event.type === 'click' || event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault();
                                window.open(targetUrl, '_blank', 'noopener,noreferrer');
                            }
                        });
                    const cover = qqSafeImageUrl(pl.cover);
                    if (cover) {
                        card.append($('<img>', { class: 'card-img-top', alt: name }).attr('src', cover).on('error', function() { $(this).hide(); }));
                    }
                    card.append(
                        $('<div>', { class: 'card-body p-2' })
                            .append($('<div>', { class: 'fw-bold small text-truncate', title: name }).text(name))
                            .append($('<div>', { class: 'text-muted' }).css('font-size', '.75rem').text(`${Number(pl.trackCount) || 0}首 · ${(Number(pl.playCount) || 0).toLocaleString()}次`))
                    );
                    grid.append($('<div>', { class: 'col-md-4 col-lg-3' }).append(card));
                });
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
            const qrImage = qqSafeQrImage(data.qrcode);
            if (qrImage) {
                $('#qq-qr-image').attr('src', qrImage).show();
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
                this.showToast('QQ音乐登录成功，自动续期已启用', 'success');
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
                const renewalText = data.refresh_supported ? '，自动续期已启用' : '';
                $('#qq-cookie-save-msg').html(`<span class="text-success">Cookie已保存${renewalText}</span>`);
                this.showToast(`QQ音乐Cookie已保存${renewalText}`, 'success');
                this.checkLoginStatus();
            } else {
                $('#qq-cookie-save-msg').empty().append($('<span>', { class: 'text-danger' }).text(data.error || '保存失败'));
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
