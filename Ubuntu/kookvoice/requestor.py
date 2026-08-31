import aiohttp


class VoiceRequestor:
    def __init__(self, token):
        self.token = token
        self._session = None

    async def _get_session(self):
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=15, connect=5, sock_read=10)
            self._session = aiohttp.ClientSession(
                headers={'Authorization': f'Bot {self.token}'},
                timeout=timeout,
            )
        return self._session

    async def request(self, method, api, **kwargs):
        session = await self._get_session()
        # 语音 API 只允许固定的 KOOK 端点；调用方不能重新打开重定向，
        # 避免把带 Authorization 的请求转发到非预期主机。
        kwargs['allow_redirects'] = False
        async with session.request(
            method,
            f'https://www.kookapp.cn/api/v3/{api}',
            **kwargs,
        ) as res:
            if 300 <= res.status < 400:
                raise RuntimeError('KOOK语音API拒绝重定向响应')
            res.raise_for_status()
            resj = await res.json()
        if not isinstance(resj, dict):
            raise RuntimeError('KOOK语音API响应格式错误')
        if resj.get('code') != 0:
            raise RuntimeError(resj.get('message', 'KOOK语音API调用失败'))
        return resj.get('data', {})

    async def close(self):
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def join(self, cid):
        return await self.request('POST', 'voice/join', json={'channel_id': cid})

    async def leave(self, cid):
        return await self.request('POST', 'voice/leave', json={'channel_id': cid})

    async def list(self):
        return await self.request('GET', 'voice/list')

    async def keep_alive(self, cid):
        return await self.request('POST', 'voice/keep-alive', json={'channel_id': cid})
