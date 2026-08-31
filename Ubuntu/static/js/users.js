(() => {
    'use strict';
    const list = document.getElementById('iam-user-list');
    const form = document.getElementById('iam-create-form');
    const message = document.getElementById('iam-message');
    function showMessage(text, error = false, password = false) {
        if (!message) return;
        message.classList.toggle('error', error);
        message.classList.add('show');
        message.replaceChildren();
        const line = document.createElement('div');
        line.textContent = text;
        if (password) line.classList.add('iam-temp-password');
        message.appendChild(line);
    }
    async function requestJSON(url, options = {}) {
        const response = await fetch(url, { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.success === false) throw new Error(data.error || `HTTP ${response.status}`);
        return data;
    }
    function option(value, label, selected) {
        const node = document.createElement('option'); node.value = value; node.textContent = label; node.selected = selected; return node;
    }
    function iconButton(icon, title, className = '') {
        const button = document.createElement('button'); button.type = 'button'; button.className = `iam-icon-button ${className}`.trim(); button.title = title; button.setAttribute('aria-label', title);
        const i = document.createElement('i'); i.className = `bi ${icon}`; button.appendChild(i); return button;
    }
    function renderUser(user) {
        const row = document.createElement('div'); row.className = 'iam-user-row'; row.dataset.userId = String(user.id);
        const identity = document.createElement('div'); identity.className = 'iam-user-identity';
        const name = document.createElement('strong'); name.textContent = user.username;
        const meta = document.createElement('small'); meta.textContent = user.must_change_password ? '首次/重置密码待修改' : (user.last_login_at ? `最近登录：${new Date(user.last_login_at * 1000).toLocaleString()}` : '尚未登录');
        identity.append(name, meta);
        const role = document.createElement('select'); role.className = 'form-select form-select-sm iam-inline-control iam-role';
        role.append(option('user', '普通用户', user.role === 'user'), option('admin', '管理员', user.role === 'admin'));
        const enabledWrap = document.createElement('label'); enabledWrap.className = 'form-check form-switch m-0';
        const enabled = document.createElement('input'); enabled.type = 'checkbox'; enabled.className = 'form-check-input iam-enabled'; enabled.checked = Boolean(user.enabled);
        const enabledLabel = document.createElement('span'); enabledLabel.className = 'small ms-1'; enabledLabel.textContent = '启用'; enabledWrap.append(enabled, enabledLabel);
        const scope = document.createElement('input'); scope.type = 'text'; scope.className = 'form-control form-control-sm iam-inline-control iam-scope-input'; scope.value = user.scopes || ''; scope.placeholder = '*, guild:服务器ID, channel:服务器ID/频道ID'; scope.disabled = user.role === 'admin';
        role.addEventListener('change', () => { scope.disabled = role.value === 'admin'; });
        const actions = document.createElement('div'); actions.className = 'iam-row-actions';
        const save = iconButton('bi-check2', '保存'); const reset = iconButton('bi-key', '重置密码'); const remove = iconButton('bi-trash3', '删除', 'danger'); actions.append(save, reset, remove);
        save.addEventListener('click', async () => {
            save.disabled = true;
            try { await requestJSON(`/api/admin/users/${user.id}`, { method: 'PATCH', body: JSON.stringify({ role: role.value, enabled: enabled.checked, scopes: scope.value.trim() }) }); showMessage(`已保存 ${user.username} 的权限设置`); await loadUsers(); }
            catch (error) { showMessage(error.message, true); }
            finally { save.disabled = false; }
        });
        reset.addEventListener('click', async () => {
            if (!window.confirm(`重置 ${user.username} 的密码并注销其全部会话？`)) return;
            reset.disabled = true;
            try { const data = await requestJSON(`/api/admin/users/${user.id}/reset-password`, { method: 'POST', body: '{}' }); showMessage(`临时密码（仅显示本次）：${data.temporary_password}`, false, true); await loadUsers(); }
            catch (error) { showMessage(error.message, true); }
            finally { reset.disabled = false; }
        });
        remove.addEventListener('click', async () => {
            if (!window.confirm(`永久删除用户 ${user.username}？`)) return;
            remove.disabled = true;
            try { await requestJSON(`/api/admin/users/${user.id}`, { method: 'DELETE' }); showMessage(`已删除用户 ${user.username}`); await loadUsers(); }
            catch (error) { showMessage(error.message, true); remove.disabled = false; }
        });
        row.append(identity, role, enabledWrap, scope, actions); return row;
    }
    async function loadUsers() {
        if (!list) return; list.innerHTML = '<div class="text-muted py-3">正在读取用户…</div>';
        try { const data = await requestJSON('/api/admin/users'); list.replaceChildren(...data.users.map(renderUser)); }
        catch (error) { list.innerHTML = ''; showMessage(error.message, true); }
    }
    const createRole = document.getElementById('iam-create-role');
    const createScopes = document.getElementById('iam-create-scopes');
    function syncCreateScopeState() {
        const isUser = createRole.value === 'user';
        createScopes.disabled = !isUser;
        createScopes.required = isUser;
    }
    createRole?.addEventListener('change', syncCreateScopeState);
    syncCreateScopeState();
    form?.addEventListener('submit', async event => {
        event.preventDefault();
        const username = document.getElementById('iam-create-username').value.trim();
        const role = document.getElementById('iam-create-role').value;
        const scopes = createScopes.value.trim();
        const submit = form.querySelector('button[type="submit"]'); submit.disabled = true;
        try { const data = await requestJSON('/api/admin/users', { method: 'POST', body: JSON.stringify({ username, role, scopes }) }); showMessage(`用户已创建。临时密码（仅显示本次）：${data.temporary_password}`, false, true); form.reset(); syncCreateScopeState(); await loadUsers(); }
        catch (error) { showMessage(error.message, true); }
        finally { submit.disabled = false; }
    });
    document.addEventListener('DOMContentLoaded', loadUsers, { once: true });
})();
