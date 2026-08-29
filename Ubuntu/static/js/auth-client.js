(() => {
    'use strict';
    const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
    const rawFetch = window.fetch.bind(window);
    function readCookie(name) {
        const prefix = `${encodeURIComponent(name)}=`;
        const part = document.cookie.split('; ').find(item => item.startsWith(prefix));
        return part ? decodeURIComponent(part.slice(prefix.length)) : '';
    }
    window.fetch = function(input, init = {}) {
        const requestMethod = String(init.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
        let requestUrl;
        try { requestUrl = new URL(input instanceof Request ? input.url : String(input), window.location.href); }
        catch (_) { return rawFetch(input, init); }
        if (requestUrl.origin === window.location.origin && UNSAFE.has(requestMethod)) {
            const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
            if (!headers.has('X-CSRF-Token')) {
                const token = readCookie('kook_csrf');
                if (token) headers.set('X-CSRF-Token', token);
            }
            init = { ...init, headers };
        }
        return rawFetch(input, init);
    };
    const xhrOpen = XMLHttpRequest.prototype.open;
    const xhrSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url, ...rest) {
        this.__kookMethod = String(method || 'GET').toUpperCase();
        this.__kookUrl = url;
        return xhrOpen.call(this, method, url, ...rest);
    };
    XMLHttpRequest.prototype.send = function(body) {
        try {
            const url = new URL(String(this.__kookUrl || ''), window.location.href);
            if (url.origin === window.location.origin && UNSAFE.has(this.__kookMethod)) {
                const token = readCookie('kook_csrf');
                if (token) this.setRequestHeader('X-CSRF-Token', token);
            }
        } catch (_) {}
        return xhrSend.call(this, body);
    };
})();
