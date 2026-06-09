/**
 * 网易云账号管理页面 JS
 */
class AccountManager {
    constructor() {
        this.qrKey = null;
        this.qrTimer = null;
        this.accountData = null;
        this.init();
    }

    init() {
        this.bindEvents();
        this.checkLoginStatus();
    }

    bindEvents() {
        // 刷新二维码
        $('#qr-refresh-btn').click(() => this.fetchQRCode());

        // 发送验证码
        $('#send-captcha-btn').click(() => this.sendCaptcha());

        // 手机登录
        $('#phone-login-btn').click(() => this.cellphoneLogin());

        // Cookie保存
        $('#cookie-save-btn').click(() => this.saveCookie());

        // 每日签到
        $('#daily-signin-btn').click(() => this.dailySignin());

        // 退出登录
        $('#logout-btn').click(() => this.logout());

        // 登录tab切换（切换到二维码时自动拉取）
        $('a[data-bs-toggle="tab"][href="#qrcode-tab"]').on('shown.bs.tab', () => {
            if (!this.qrKey) this.fetchQRCode();
        });
    }

    // ========== 登录状态检查 ==========
    async checkLoginStatus() {
        try {
            const resp = await fetch('/api/account/status');
            const data = await resp.json();
            // login_status 返回结构: { data: { account: {...}, profile: {...} } }
            if (data && data.data && data.data.account) {
                this.accountData = data.data;
                this.showAccountSection();
            } else if (data && data.code === 200) {
                // 某些情况下 code=200 但无account信息，再尝试
                this.accountData = data.data || data;
                this.showAccountSection();
            } else {
                this.showLoginSection();
            }
        } catch (e) {
            console.error('检查登录状态失败:', e);
            this.showLoginSection();
        }
    }

    // ========== 登录区域 ==========
    showLoginSection() {
        $('#login-section').show();
        $('#account-section').hide();
        this.fetchQRCode();
    }

    showAccountSection() {
        $('#login-section').hide();
        $('#account-section').show();
        this.loadAccountInfo();
        this.loadSubcount();
        this.loadPlaylists();
    }

    // ========== 二维码登录 ==========
    async fetchQRCode() {
        $('#qr-loading').show();
        $('#qr-image').hide();
        $('#qr-expired').hide();
        this.stopQRPolling();

        try {
            // 获取key
            const keyResp = await fetch('/api/account/qr/key', { method: 'POST' });
            const keyData = await keyResp.json();
            if (!keyData.data || !keyData.data.unikey) {
                this.showToast('获取二维码key失败', 'error');
                $('#qr-loading').hide();
                $('#qr-expired').show();
                return;
            }
            this.qrKey = keyData.data.unikey;

            // 创建二维码
            const qrResp = await fetch('/api/account/qr/create', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: this.qrKey })
            });
            const qrData = await qrResp.json();
            if (qrData.data && qrData.data.qrimg) {
                const img = qrData.data.qrimg;
                if (img.startsWith('data:image')) {
                    $('#qr-image').attr('src', img);
                } else {
                    $('#qr-image').attr('src', 'data:image/png;base64,' + img);
                }
                $('#qr-loading').hide();
                $('#qr-image').show();
                $('#qr-status').text('请使用网易云音乐App扫描二维码').removeClass('text-success text-danger');
                // 开始轮询
                this.startQRPolling();
            } else if (qrData.data && qrData.data.qrurl) {
                // 返回的是链接，用qrcode生成
                $('#qr-image').attr('src', 'https://api.qrserver.com/v1/create-qr-code/?size=240x240&data=' + encodeURIComponent(qrData.data.qrurl));
                $('#qr-loading').hide();
                $('#qr-image').show();
                this.startQRPolling();
            } else {
                throw new Error('未获取到二维码');
            }
        } catch (e) {
            console.error('获取二维码失败:', e);
            $('#qr-loading').hide();
            $('#qr-expired').show();
            this.showToast('获取二维码失败', 'error');
        }
    }

    startQRPolling() {
        this.stopQRPolling();
        this.qrTimer = setInterval(() => this.checkQRStatus(), 2000);
    }

    stopQRPolling() {
        if (this.qrTimer) {
            clearInterval(this.qrTimer);
            this.qrTimer = null;
        }
    }

    async checkQRStatus() {
        if (!this.qrKey) return;
        try {
            const resp = await fetch('/api/account/qr/check', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: this.qrKey })
            });
            const data = await resp.json();
            const code = data.code;
            // 801=等待扫码, 802=已扫码等待确认, 803=登录成功, 800=过期
            if (code === 802) {
                $('#qr-status').text('已扫码，请在手机上确认登录...').addClass('text-warning').removeClass('text-success text-danger');
            } else if (code === 803) {
                // 登录成功
                this.stopQRPolling();
                $('#qr-status').text('登录成功！').addClass('text-success').removeClass('text-warning text-danger');
                // 保存cookie
                const cookieStr = data.cookie;
                if (cookieStr) {
                    await this.persistCookie(cookieStr);
                }
                this.showToast('登录成功！', 'success');
                setTimeout(() => this.checkLoginStatus(), 1000);
            } else if (code === 800) {
                // 过期
                this.stopQRPolling();
                $('#qr-image').hide();
                $('#qr-expired').show();
                $('#qr-status').text('二维码已过期').addClass('text-danger');
            }
        } catch (e) {
            console.error('检查二维码状态失败:', e);
        }
    }

    // ========== 手机登录 ==========
    async sendCaptcha() {
        const phone = $('#phone-input').val().trim();
        if (!phone) {
            $('#phone-login-msg').html('<span class="text-danger">请输入手机号</span>');
            return;
        }
        $('#send-captcha-btn').prop('disabled', true).text('发送中...');
        try {
            const resp = await fetch('/api/account/cellphone/captcha', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ phone: phone, countrycode: '86' })
            });
            const data = await resp.json();
            if (data.code === 200) {
                $('#phone-login-msg').html('<span class="text-success">验证码已发送</span>');
                // 倒计时
                let sec = 60;
                const cd = setInterval(() => {
                    sec--;
                    $('#send-captcha-btn').text(sec + 's后重发');
                    if (sec <= 0) {
                        clearInterval(cd);
                        $('#send-captcha-btn').prop('disabled', false).text('发送验证码');
                    }
                }, 1000);
            } else {
                $('#phone-login-msg').html('<span class="text-danger">发送失败: ' + (data.message || data.msg || '未知错误') + '</span>');
                $('#send-captcha-btn').prop('disabled', false).text('发送验证码');
            }
        } catch (e) {
            $('#phone-login-msg').html('<span class="text-danger">网络错误</span>');
            $('#send-captcha-btn').prop('disabled', false).text('发送验证码');
        }
    }

    async cellphoneLogin() {
        const phone = $('#phone-input').val().trim();
        const captcha = $('#captcha-input').val().trim();
        if (!phone || !captcha) {
            $('#phone-login-msg').html('<span class="text-danger">请填写手机号和验证码</span>');
            return;
        }
        $('#phone-login-btn').prop('disabled', true).text('登录中...');
        try {
            const resp = await fetch('/api/account/cellphone/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ phone: phone, captcha: captcha, countrycode: '86' })
            });
            const data = await resp.json();
            if (data.code === 200 || data.code === 803) {
                $('#phone-login-msg').html('<span class="text-success">登录成功！</span>');
                this.showToast('登录成功！', 'success');
                setTimeout(() => this.checkLoginStatus(), 1000);
            } else {
                $('#phone-login-msg').html('<span class="text-danger">登录失败: ' + (data.message || data.msg || '未知错误') + '</span>');
            }
        } catch (e) {
            $('#phone-login-msg').html('<span class="text-danger">网络错误</span>');
        }
        $('#phone-login-btn').prop('disabled', false).text('登录');
    }

    // ========== Cookie手动输入 ==========
    async saveCookie() {
        const cookie = $('#cookie-input').val().trim();
        if (!cookie) {
            $('#cookie-save-msg').html('<span class="text-danger">请输入Cookie</span>');
            return;
        }
        try {
            const resp = await fetch('/api/account/cookie', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cookie: cookie })
            });
            const data = await resp.json();
            if (data.code === 200) {
                $('#cookie-save-msg').html('<span class="text-success">Cookie已保存，正在刷新...</span>');
                setTimeout(() => this.checkLoginStatus(), 1000);
            } else {
                $('#cookie-save-msg').html('<span class="text-danger">保存失败</span>');
            }
        } catch (e) {
            $('#cookie-save-msg').html('<span class="text-danger">网络错误</span>');
        }
    }

    async persistCookie(cookieStr) {
        try {
            await fetch('/api/account/cookie', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cookie: cookieStr })
            });
        } catch (e) {
            console.error('保存Cookie失败:', e);
        }
    }

    // ========== 账号信息 ==========
    async loadAccountInfo() {
        if (!this.accountData) return;
        const profile = this.accountData.profile || {};
        const account = this.accountData.account || {};

        // 头像
        const avatarUrl = profile.avatarUrl || '';
        $('#profile-avatar').attr('src', avatarUrl || 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96"><circle cx="48" cy="48" r="48" fill="%23ddd"/></svg>');

        // 昵称
        $('#profile-nickname').text(profile.nickname || '未知用户');
        $('#profile-uid').text(profile.userId || account.id || '--');
        $('#profile-signature').text(profile.signature || '暂无签名');

        // 等级
        this.loadLevel();

        // VIP
        if (profile.vipType && profile.vipType > 0) {
            $('#profile-vip-badge').show().text(profile.vipType >= 7 ? 'SVIP' : 'VIP');
        }

        // 关注/粉丝
        if (profile.follows !== undefined) $('#stat-follows').text(profile.follows);
        if (profile.followeds !== undefined) $('#stat-followeds').text(profile.followeds);

        // 加载详情补充
        this.loadDetail(profile.userId);
    }

    async loadLevel() {
        try {
            const resp = await fetch('/api/account/level');
            const data = await resp.json();
            if (data.data) {
                $('#profile-level-badge').text('Lv.' + (data.data.level || '--'));
            }
        } catch (e) {
            console.error('获取等级失败:', e);
        }
    }

    async loadDetail(uid) {
        if (!uid) return;
        try {
            const resp = await fetch('/api/account/detail?uid=' + uid);
            const data = await resp.json();
            if (data.code === 200 && data.profile) {
                const p = data.profile;
                $('#stat-follows').text(p.follows ?? $('#stat-follows').text());
                $('#stat-followeds').text(p.followeds ?? $('#stat-followeds').text());
                $('#profile-signature').text(p.signature || $('#profile-signature').text());
            }
        } catch (e) {
            console.error('获取用户详情失败:', e);
        }
    }

    async loadSubcount() {
        try {
            const resp = await fetch('/api/account/subcount');
            const data = await resp.json();
            if (data.code === 200) {
                $('#sub-playlist').text(data.createdPlaylistCount ?? '--');
                $('#sub-artist').text(data.artistCount ?? '--');
                $('#sub-album').text(data.albumCount ?? data.subAlbumCount ?? '--');
                $('#sub-djradio').text(data.djRadioCount ?? '--');
                $('#sub-mv').text(data.mvCount ?? '--');
                $('#sub-program').text(data.programCount ?? '--');
            }
        } catch (e) {
            console.error('获取收藏计数失败:', e);
        }
    }

    async loadPlaylists() {
        const uid = this.accountData?.profile?.userId || this.accountData?.account?.id;
        if (!uid) {
            $('#playlist-grid').html('<div class="col-12 text-center text-muted py-4">请先登录</div>');
            return;
        }
        try {
            const resp = await fetch('/api/account/playlists?uid=' + uid);
            const data = await resp.json();
            if (data.code === 200 && data.playlist) {
                const playlists = data.playlist;
                $('#playlist-count').text(playlists.length);
                if (playlists.length === 0) {
                    $('#playlist-grid').html('<div class="col-12 text-center text-muted py-4">暂无歌单</div>');
                    return;
                }
                let html = '';
                playlists.forEach(pl => {
                    const cover = pl.coverImgUrl || '';
                    const name = pl.name || '未知歌单';
                    const trackCount = pl.trackCount || 0;
                    const playCount = (pl.playCount || 0).toLocaleString();
                    const creator = pl.creator?.nickname || '';
                    html += `
                        <div class="col-md-4 col-lg-3">
                            <div class="card h-100 playlist-card" style="cursor: pointer;"
                                 onclick="window.open('https://music.163.com/#/playlist?id=${pl.id}', '_blank')">
                                <img src="${cover}" class="card-img-top" alt="${name}"
                                     onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 200 200%22><rect fill=%22%23eee%22 width=%22200%22 height=%22200%22/></svg>'">
                                <div class="card-body p-2">
                                    <div class="fw-bold small text-truncate" title="${name}">${name}</div>
                                    <div class="text-muted" style="font-size: 0.75rem;">${trackCount}首 · ${playCount}次播放</div>
                                    ${creator ? `<div class="text-muted" style="font-size: 0.7rem;">by ${creator}</div>` : ''}
                                </div>
                            </div>
                        </div>`;
                });
                $('#playlist-grid').html(html);
            } else {
                $('#playlist-grid').html('<div class="col-12 text-center text-muted py-4">获取歌单失败</div>');
            }
        } catch (e) {
            console.error('获取歌单失败:', e);
            $('#playlist-grid').html('<div class="col-12 text-center text-muted py-4">获取歌单出错</div>');
        }
    }

    // ========== 每日签到 ==========
    async dailySignin() {
        const btn = $('#daily-signin-btn');
        btn.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> 签到中...');
        try {
            // 同时尝试 android 和 web 签到
            const [resp0, resp1] = await Promise.all([
                fetch('/api/account/signin', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ type: 0 })
                }),
                fetch('/api/account/signin', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ type: 1 })
                })
            ]);
            const d0 = await resp0.json();
            const d1 = await resp1.json();

            let resultHtml = '';
            // android 签到
            if (d0.code === 200) {
                resultHtml += `<p><i class="bi bi-phone"></i> Android: <span class="text-success">+${d0.point || 3} 经验</span></p>`;
            } else {
                resultHtml += `<p><i class="bi bi-phone"></i> Android: <span class="text-muted">${d0.msg || d0.message || '已签到'}</span></p>`;
            }
            // web 签到
            if (d1.code === 200) {
                resultHtml += `<p><i class="bi bi-laptop"></i> Web: <span class="text-success">+${d1.point || 2} 经验</span></p>`;
            } else {
                resultHtml += `<p><i class="bi bi-laptop"></i> Web: <span class="text-muted">${d1.msg || d1.message || '已签到'}</span></p>`;
            }

            $('#signin-result-card').show();
            $('#signin-result-body').html(resultHtml);
            this.showToast('签到完成', 'success');
        } catch (e) {
            this.showToast('签到失败', 'error');
        }
        btn.prop('disabled', false).html('<i class="bi bi-calendar-check"></i> 每日签到');
    }

    // ========== 退出登录 ==========
    async logout() {
        if (!confirm('确定要退出网易云账号吗？')) return;
        try {
            await fetch('/api/account/logout', { method: 'POST' });
            this.accountData = null;
            this.qrKey = null;
            this.showToast('已退出登录', 'info');
            this.showLoginSection();
        } catch (e) {
            console.error('退出登录失败:', e);
        }
    }

    // ========== Toast提示 ==========
    showToast(msg, type) {
        const toast = $('#account-toast');
        toast.removeClass('text-bg-success text-bg-danger text-bg-info')
            .addClass(type === 'error' ? 'text-bg-danger' : type === 'info' ? 'text-bg-info' : 'text-bg-success');
        $('#toast-message').text(msg);
        new bootstrap.Toast(toast[0], { delay: 2000 }).show();
    }
}

// 页面初始化
$(document).ready(() => {
    window.accountManager = new AccountManager();
});
