import asyncio
import copy
import os
import shlex
import shutil
import threading
import time
import logging
from enum import Enum, unique
from typing import Dict, Union, List, Any, Optional, Coroutine as CoroutineType
from asyncio import AbstractEventLoop

try:
    import psutil
except ImportError:
    psutil = None
_PROCESS_ERRORS = (OSError,) if psutil is None else (psutil.Error, OSError)

try:
    from .requestor import VoiceRequestor
except ImportError:
    from requestor import VoiceRequestor

# 配置日志
logger = logging.getLogger(__name__)
log_enabled = False

def configure_logging(enabled: bool = True):
    global log_enabled
    # 播放库只控制自身的详细日志，不修改应用的根日志配置。
    log_enabled = bool(enabled)

ffmpeg_bin = os.environ.get('FFMPEG_BIN', 'ffmpeg')

original_loop = None  # 初始化为None，后面会赋值为AbstractEventLoop

def set_ffmpeg(path):
    global ffmpeg_bin
    path = str(path or '').strip()
    resolved = path if path and os.path.isfile(path) else shutil.which(path)
    if not resolved:
        raise FileNotFoundError(f'FFmpeg不存在或不可执行: {path or "<空>"}')
    ffmpeg_bin = os.path.abspath(resolved) if os.path.isfile(resolved) else resolved


def set_loop(loop):
    global original_loop
    original_loop = loop


def _build_decoder_command(file, ss_value=0, is_bili=False, extra_command=''):
    """构造兼容当前 FFmpeg 的网络音频解码参数。"""
    timeout_us = 60000000 if is_bili else 30000000
    command = [
        ffmpeg_bin,
        '-loglevel', 'error',
        '-nostats',
        '-reconnect', '1',
        '-reconnect_streamed', '1',
        '-reconnect_delay_max', '5',
        '-rw_timeout', str(timeout_us),
    ]
    if is_bili:
        command.extend([
            '-user_agent',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            '-referer', 'https://www.bilibili.com/',
        ])
    if extra_command:
        # headers/cookies/user_agent/referer 都是输入选项，必须位于 -i 之前。
        command.extend(shlex.split(extra_command))
    command.extend([
        '-ss', str(ss_value),
        '-i', str(file),
        '-filter:a', 'volume=0.4',
        '-acodec', 'pcm_s16le',
        '-ac', '2',
        '-ar', '48000',
        '-f', 'wav',
        '-y', '-',
    ])
    return command


async def _safe_kill_subprocess(proc, label="ffmpeg"):
    """在事件循环仍存活时终止子进程，并完整回收其异步管道。"""
    if proc is None:
        return

    # StreamReader 没有 close()；stdout/stderr 必须由 communicate() 排空，
    # 否则 Windows 的 Proactor 管道 transport 可能延迟到 loop.close() 后析构。
    stdin = getattr(proc, 'stdin', None)
    if stdin is not None:
        try:
            stdin.close()
            wait_closed = getattr(stdin, 'wait_closed', None)
            if wait_closed is not None:
                await asyncio.wait_for(wait_closed(), timeout=1)
        except (BrokenPipeError, ConnectionResetError, asyncio.TimeoutError):
            pass
        except Exception:
            pass

    try:
        if proc.returncode is None:
            proc.kill()
    except (ProcessLookupError, OSError):
        pass

    try:
        await asyncio.wait_for(proc.communicate(), timeout=3)
    except asyncio.TimeoutError:
        try:
            if proc.returncode is None:
                proc.kill()
        except (ProcessLookupError, OSError):
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=1)
        except Exception:
            pass
    except (BrokenPipeError, ConnectionResetError, OSError):
        try:
            await asyncio.wait_for(proc.wait(), timeout=1)
        except Exception:
            pass

    # 让 ProactorEventLoop 执行 pipe connection_lost 回调后再允许关闭循环。
    await asyncio.sleep(0)
    if log_enabled:
        logger.info(f'[{label}] 进程已安全终止')

@unique
class Status(Enum):
    STOP = 0
    WAIT = 1
    SKIP = 2
    END = 3
    START = 4
    PAUSE = 5
    PLAYING = 10
    EMPTY = 11

guild_status = {}
play_list: Dict[str, Dict[str, Any]] = {}
play_list_example = {'频道id':
                              {'token': '机器人token',
                               'guild_id': '服务器id',
                                'voice_channel': '语音频道id',
                                'text_channel': '最后一次执行指令的文字频道id',
                                'repeat': False,
                                'playlist_repeat': False,
                                'now_playing': {'file': '歌曲文件', 'ss': 0, 'start': 0,'extra':{}},
                               'play_list': [
                                   {'file': '路径', 'ss': 0}]}}

playlist_handle_status = {}
state_lock = threading.RLock()
_active_handlers: Dict[str, "PlayHandler"] = {}
_recovering_channels = set()
_pending_leave_channels = set()


def _new_channel_state(channel_id: str, token: str, guild_id: str = "") -> Dict[str, Any]:
    return {
        'token': token,
        'guild_id': str(guild_id),
        'voice_channel': channel_id,
        'repeat': False,
        'playlist_repeat': False,
        '_queue_backup': None,
        '_stopping': False,
        'now_playing': None,
        'play_list': [],
    }


def _complete_current_track_locked(channel_id: str) -> Dict[str, Any]:
    """完成当前歌曲并按循环模式重新排队；调用方必须持有 state_lock。"""
    channel_state = play_list.get(str(channel_id))
    if channel_state is None:
        return {
            'state': None,
            'track': None,
            'mode': None,
            'queue_empty': True,
        }

    now_info = channel_state.get('now_playing')
    channel_state['now_playing'] = None
    mode = None

    if now_info and isinstance(now_info, dict):
        replay = copy.deepcopy(now_info)
        replay['ss'] = 0
        replay.pop('start', None)

        if channel_state.get('repeat', False):
            channel_state['play_list'].insert(0, replay)
            mode = 'single'
        elif channel_state.get('playlist_repeat', False):
            channel_state['play_list'].append(replay)
            mode = 'playlist'

    return {
        'state': channel_state,
        'track': now_info,
        'mode': mode,
        'queue_empty': not channel_state['play_list'],
    }


def _get_active_handler_locked(channel_id: str):
    handler = _active_handlers.get(channel_id)
    if handler is not None and not handler.finished.is_set():
        return handler
    if handler is not None:
        _active_handlers.pop(channel_id, None)
    return None


def _start_handler_locked(channel_id: str, token: str):
    handler = _get_active_handler_locked(channel_id)
    if handler is not None:
        return handler, False
    handler = PlayHandler(channel_id, token)
    _active_handlers[channel_id] = handler
    try:
        handler.start()
    except Exception:
        if _active_handlers.get(channel_id) is handler:
            _active_handlers.pop(channel_id, None)
        raise
    return handler, True


def _wait_for_stopping_channel(channel_id: str, timeout: float = 10.0):
    with state_lock:
        if channel_id in _recovering_channels:
            raise RuntimeError('频道正在紧急恢复，请等待命令完成后重试')
        if guild_status.get(channel_id) != Status.STOP:
            return
        handler = _get_active_handler_locked(channel_id)
    if handler is not None:
        handler.finished.wait(timeout=timeout)
    with state_lock:
        if guild_status.get(channel_id) == Status.STOP:
            raise RuntimeError('频道正在停止，请稍后重试')


def get_state_snapshot(channel_id: Optional[str] = None):
    """返回播放状态深拷贝，供 Web/API 跨线程安全读取。"""
    with state_lock:
        if channel_id is not None:
            state = play_list.get(str(channel_id))
            return copy.deepcopy(state) if state is not None else None
        return {
            'play_list': copy.deepcopy(play_list),
            'guild_status': dict(guild_status),
            'playlist_handle_status': dict(playlist_handle_status),
        }


def reset_playback_state():
    """向所有 Handler 发出线程安全的紧急停止请求。"""
    handlers = []
    with state_lock:
        channel_ids = (
            set(play_list)
            | set(guild_status)
            | set(playlist_handle_status)
            | set(_active_handlers)
            | set(_pending_leave_channels)
        )
        _recovering_channels.update(channel_ids)
        for channel_id in channel_ids:
            handler = _get_active_handler_locked(channel_id)
            if handler is None:
                play_list.pop(channel_id, None)
                guild_status.pop(channel_id, None)
                playlist_handle_status.pop(channel_id, None)
                continue
            handlers.append(handler)
            guild_status[channel_id] = Status.STOP
            state = play_list.get(channel_id)
            if state is not None:
                state['_stopping'] = True
                state['play_list'] = []
    for handler in handlers:
        try:
            handler.request_stop()
        except Exception:
            logger.exception(
                '请求紧急停止失败，频道=%s',
                getattr(handler, 'channel_id', '?'),
            )
    return channel_ids


def finish_playback_recovery(channel_ids, leave_failed=()):
    """结束恢复；保留未确认 KOOK 脱离的频道供下次重试。"""
    with state_lock:
        _recovering_channels.difference_update(channel_ids)
        _pending_leave_channels.difference_update(channel_ids)
        _pending_leave_channels.update(leave_failed)


def wait_for_handlers(channel_ids, timeout: float = 5.0):
    """等待指定频道的 Handler 完成，返回仍未退出的频道。"""
    deadline = time.monotonic() + timeout
    with state_lock:
        handlers = {
            channel_id: _get_active_handler_locked(channel_id)
            for channel_id in channel_ids
        }
    for handler in handlers.values():
        if handler is None:
            continue
        remaining = max(0.0, deadline - time.monotonic())
        handler.finished.wait(remaining)
    with state_lock:
        return {
            channel_id
            for channel_id in channel_ids
            if _get_active_handler_locked(channel_id) is not None
        }


def force_terminate_handler_processes(channel_ids):
    """终止指定频道 Handler 跟踪到的 FFmpeg/ffprobe 进程。"""
    with state_lock:
        handlers = {
            channel_id: _get_active_handler_locked(channel_id)
            for channel_id in channel_ids
        }
    killed = 0
    for handler in handlers.values():
        if handler is None:
            continue
        try:
            killed += handler.force_terminate_subprocesses()
        except Exception:
            logger.exception(
                '强制终止媒体子进程失败，频道=%s',
                getattr(handler, 'channel_id', '?'),
            )
    return killed


def detach_stuck_handlers(channel_ids):
    """隔离仍未退出的旧 Handler，并释放频道状态供新会话重建。

    Handler 退出时会再次校验注册表所有权，因此被隔离的旧线程不会删除
    或离开之后建立的新会话。
    """
    with state_lock:
        handlers = {
            channel_id: _get_active_handler_locked(channel_id)
            for channel_id in channel_ids
        }
        # 和 PlayHandler.stop() 的 leave 决策使用同一把锁。若 leave 已
        # 开始，下面会先等待它完成，避免旧 leave 命中新建立的会话。
        for handler in handlers.values():
            if handler is not None:
                handler.mark_detached()

    for handler in handlers.values():
        if handler is None:
            continue
        try:
            handler.request_stop()
        except Exception:
            logger.exception(
                '标记旧处理器隔离失败，频道=%s',
                getattr(handler, 'channel_id', '?'),
            )

    deadline = time.monotonic() + 6.0
    for handler in handlers.values():
        wait_for_leave = getattr(handler, 'wait_for_leave', None)
        if handler is None or wait_for_leave is None:
            continue
        remaining = max(0.0, deadline - time.monotonic())
        if not wait_for_leave(remaining):
            logger.warning(
                '旧处理器的KOOK离开请求未按时结束，继续隔离: 频道=%s',
                getattr(handler, 'channel_id', '?'),
            )

    detached = set()
    with state_lock:
        for channel_id, handler in handlers.items():
            if handler is None or _active_handlers.get(channel_id) is not handler:
                continue
            _active_handlers.pop(channel_id, None)
            play_list.pop(channel_id, None)
            guild_status.pop(channel_id, None)
            playlist_handle_status.pop(channel_id, None)
            detached.add(channel_id)
    return detached


def _discard_current_item(channel_id: str, expected_handler=None):
    """丢弃无法解析的当前项，避免 now_playing 被下一轮无限重试。"""
    with state_lock:
        if (
            expected_handler is not None
            and _active_handlers.get(channel_id) is not expected_handler
        ):
            return False
        state = play_list.get(channel_id)
        if state is not None:
            state['now_playing'] = None
        if guild_status.get(channel_id) != Status.STOP:
            guild_status[channel_id] = Status.END
        return True

class Player:
    def __init__(self, channel_id, token=None):
        """
            :param str channel_id: 推流语音频道id（唯一会话标识）
            :param str token: 推流机器人token
        """
        self.channel_id = str(channel_id) if channel_id is not None else ""

        with state_lock:
            if self.channel_id in play_list:
                if token is None:
                    token = play_list[self.channel_id]['token']
                elif token != play_list[self.channel_id]['token']:
                    raise ValueError('播放歌曲过程中无法更换token')
        self.token = str(token) if token else ""

    def join(self, guild_id: str = ""):
        """加入语音频道并开始推流
            :param str guild_id: 服务器id（元数据）"""
        if not self.channel_id:
            raise ValueError('第一次启动推流时，你需要指定语音频道id')
        if not self.token:
            raise ValueError('第一次启动推流时，你需要指定机器人token')
        _wait_for_stopping_channel(self.channel_id)
        with state_lock:
            state = play_list.get(self.channel_id)
            if state is None:
                state = _new_channel_state(self.channel_id, self.token, guild_id)
                play_list[self.channel_id] = state
            else:
                state['guild_id'] = str(guild_id) or state.get('guild_id', '')
                state['voice_channel'] = self.channel_id
                state['_stopping'] = False

            handler = _get_active_handler_locked(self.channel_id)
            if handler is not None:
                if log_enabled:
                    logger.info(f'频道已有播放处理器，复用现有会话: {self.channel_id}')
                return False

            guild_status[self.channel_id] = (
                Status.END if state.get('play_list') else Status.WAIT
            )
            _start_handler_locked(self.channel_id, self.token)
        if log_enabled:
            logger.info(f'加入语音频道: {self.channel_id}，服务器: {guild_id}')
        return True

    def add_music(
        self,
        music: str,
        extra_data: Optional[dict] = None,
        guild_id: str = "",
    ):
        """
        添加音乐到播放列表
            :param str music: 音乐文件路径或音乐链接
            :param dict extra_data: 可以在这里保存音乐信息
        """
        if not self.channel_id:
            raise ValueError('频道id不能为空')
        if not self.token:
            raise ValueError('第一次启动推流时，你需要指定机器人token')
        # 检查是否是歌单歌曲标记，如果是则跳过文件存在检查
        if not music.startswith("PLAYLIST_SONG:") and not music.startswith("QQ_PLAYLIST_SONG:") and not music.startswith("BILI_PLAYLIST_SONG:"):
            if 'http' not in music:
                if not os.path.exists(music):
                    raise ValueError('文件不存在')

        _wait_for_stopping_channel(self.channel_id)
        with state_lock:
            state = play_list.get(self.channel_id)
            if state is None:
                state = _new_channel_state(self.channel_id, self.token, guild_id)
                play_list[self.channel_id] = state
            elif guild_id:
                state['guild_id'] = str(guild_id)
            state['voice_channel'] = self.channel_id
            state['_stopping'] = False
            state['play_list'].append({
                'file': music,
                'ss': 0,
                'extra': extra_data or {},
            })
            if guild_status.get(self.channel_id) == Status.WAIT:
                guild_status[self.channel_id] = Status.END
            _start_handler_locked(self.channel_id, self.token)
        if log_enabled:
            logger.info(f'添加音乐到播放列表，频道: {self.channel_id}，音乐: {music}')

    def stop(self):
        with state_lock:
            if self.channel_id not in play_list:
                raise ValueError('该频道没有正在播放的歌曲')
            state = play_list[self.channel_id]
            state['_stopping'] = True
            state['play_list'] = []
            guild_status[self.channel_id] = Status.STOP
            if _get_active_handler_locked(self.channel_id) is None:
                play_list.pop(self.channel_id, None)
                guild_status.pop(self.channel_id, None)
                playlist_handle_status.pop(self.channel_id, None)
        if log_enabled:
            logger.info(f'停止播放，频道: {self.channel_id}')

    def skip(self, skip_amount: int = 1):
        '''
        跳过指定数量的歌曲
            :param amount int: 要跳过的歌曲数量,默认为一首
        '''
        with state_lock:
            if self.channel_id not in play_list:
                raise ValueError('该频道没有正在播放的歌曲')
            for _ in range(skip_amount - 1):
                if play_list[self.channel_id]['play_list']:
                    play_list[self.channel_id]['play_list'].pop(0)
            guild_status[self.channel_id] = Status.SKIP
        if log_enabled:
            logger.info(f'跳过了 {skip_amount} 首歌曲，频道: {self.channel_id}')

    def pause(self):
        with state_lock:
            if self.channel_id not in play_list:
                raise ValueError('该频道没有正在播放的歌曲')
            guild_status[self.channel_id] = Status.PAUSE
        if log_enabled:
            logger.info(f'暂停播放，频道: {self.channel_id}')

    def resume(self):
        with state_lock:
            if self.channel_id not in play_list:
                raise ValueError('该频道没有正在播放的歌曲')
            guild_status[self.channel_id] = Status.PLAYING
        if log_enabled:
            logger.info(f'继续播放，频道: {self.channel_id}')

    def list(self, json=True):
        with state_lock:
            if self.channel_id not in play_list:
                raise ValueError('该频道没有正在播放的歌曲')
            if json:
                result = []
                if play_list[self.channel_id]['now_playing']:
                    result.append(copy.deepcopy(play_list[self.channel_id]['now_playing']))
                result.extend(copy.deepcopy(play_list[self.channel_id]['play_list']))
                return result
            return []

    def repeat_toggle(self):
        """切换单曲循环开关，返回切换后的状态"""
        with state_lock:
            if self.channel_id not in play_list:
                raise ValueError('该频道没有正在播放的歌曲')
            state = play_list[self.channel_id]
            current = state.get('repeat', False)
            enabled = not current
            state['repeat'] = enabled
            if enabled:
                state['playlist_repeat'] = False
        if log_enabled:
            logger.info(f'单曲循环: {"开启" if enabled else "关闭"}，频道: {self.channel_id}')
        return enabled

    def playlist_repeat_toggle(self):
        """切换列表循环；开启时自动关闭单曲循环。"""
        with state_lock:
            if self.channel_id not in play_list:
                raise ValueError('该频道没有正在播放的歌曲')
            state = play_list[self.channel_id]
            enabled = not state.get('playlist_repeat', False)
            state['playlist_repeat'] = enabled
            if enabled:
                state['repeat'] = False
        if log_enabled:
            logger.info(f'列表循环: {"开启" if enabled else "关闭"}，频道: {self.channel_id}')
        return enabled

    def shuffle_toggle(self):
        """切换随机播放，返回 (enabled, count)"""
        import random
        with state_lock:
            if self.channel_id not in play_list:
                raise ValueError('该频道没有正在播放的歌曲')
            ch = play_list[self.channel_id]
            queue = ch.get('play_list', [])
            if ch.get('_queue_backup') is not None:
                ch['play_list'] = ch['_queue_backup']
                ch['_queue_backup'] = None
                if log_enabled:
                    logger.info(f'随机播放: 关闭，恢复原序 {len(queue)} 首，频道: {self.channel_id}')
                return False, len(queue)
            backup = list(queue)
            random.shuffle(queue)
            ch['play_list'] = queue
            ch['_queue_backup'] = backup
        if log_enabled:
            logger.info(f'随机播放: 开启，打乱 {len(queue)} 首，频道: {self.channel_id}')
        return True, len(queue)

    def seek(self, music_seconds: int):
        '''
        跳转至歌曲指定位置
            :param music_seconds int: 所要跳转到歌曲的秒数
        '''
        with state_lock:
            if self.channel_id not in play_list:
                raise ValueError('该频道没有正在播放的歌曲')
            if play_list[self.channel_id]['now_playing']:
                now_play = play_list[self.channel_id]['now_playing'].copy()
                now_play['ss'] = int(music_seconds)
                now_play.pop('start', None)
                play_list[self.channel_id]['play_list'].insert(0, now_play)
                guild_status[self.channel_id] = Status.SKIP
                if log_enabled:
                    logger.info(f'跳转至 {music_seconds} 秒，频道: {self.channel_id}')


# 事件处理部分

events = {}

class PlayInfo:
    def __init__(self, channel_id, file, bot_token, extra_data):
        self.file = file
        self.extra_data = extra_data
        self.channel_id = channel_id
        self.token = bot_token

def on_event(event):
    global events
    def _on_event_wrapper(func):
        if event not in events:
            events[event] = []
        events[event].append(func)
        return func
    return _on_event_wrapper

async def trigger_event(event, *args, **kwargs):
    if event in events:
        for func in events[event]:
            await func(*args, **kwargs)

class PlayHandler(threading.Thread):
    _rtp_channel_id: str = None

    def __init__(self, channel_id: str, token: str):
        threading.Thread.__init__(
            self,
            name=f'kookvoice-{channel_id}',
            daemon=True,
        )
        self.token = token
        self.channel_id = channel_id
        self.requestor = VoiceRequestor(token)
        self.finished = threading.Event()
        self.stop_requested = threading.Event()
        self.detached = threading.Event()
        self.leave_delegated = threading.Event()
        self._control_lock = threading.RLock()
        self._loop = None
        self._push_task = None
        self._leave_task = None
        self._subprocesses = {}
        self._leave_started = threading.Event()
        self._leave_finished = threading.Event()
        self._rtp_channel_id = None

    def request_stop(self):
        """从任意线程请求停止，并唤醒/取消播放事件循环中的 push 任务。"""
        self.stop_requested.set()
        # 紧急恢复由命令侧使用独立会话并发执行 KOOK leave。处理器只负责
        # 本地清理，避免旧处理器稍后再次 leave 而误伤替代会话。
        self.leave_delegated.set()
        with state_lock:
            if _active_handlers.get(self.channel_id) is self:
                guild_status[self.channel_id] = Status.STOP
                state = play_list.get(self.channel_id)
                if state is not None:
                    state['_stopping'] = True
                    state['play_list'] = []

        with self._control_lock:
            loop = self._loop
            push_task = self._push_task
            leave_task = self._leave_task

        if loop is None or loop.is_closed():
            return False

        def cancel_tasks():
            for task in (push_task, leave_task):
                if task is not None and not task.done():
                    task.cancel()

        try:
            loop.call_soon_threadsafe(cancel_tasks)
            return True
        except (RuntimeError, AttributeError):
            return False

    def mark_detached(self):
        """标记为已隔离；旧处理器退出时不得再离开或清理新会话。"""
        self.detached.set()

    def wait_for_leave(self, timeout):
        """若离开请求已经开始，等待其结束后再允许创建替代会话。"""
        if not self._leave_started.is_set() or self._leave_finished.is_set():
            return True
        return self._leave_finished.wait(timeout)

    def should_stop(self):
        if self.stop_requested.is_set() or self.detached.is_set():
            return True
        with state_lock:
            return (
                _active_handlers.get(self.channel_id) is not self
                or guild_status.get(self.channel_id) == Status.STOP
            )

    def _track_subprocess(self, proc, label):
        if proc is None:
            return proc
        create_time = None
        if psutil is not None:
            try:
                create_time = psutil.Process(proc.pid).create_time()
            except (psutil.Error, OSError):
                pass
        with self._control_lock:
            self._subprocesses[proc.pid] = {
                'proc': proc,
                'label': label,
                'create_time': create_time,
            }
        return proc

    def _untrack_subprocess(self, proc):
        if proc is None:
            return
        with self._control_lock:
            record = self._subprocesses.get(proc.pid)
            if record is not None and record.get('proc') is proc:
                self._subprocesses.pop(proc.pid, None)

    async def _cleanup_subprocess(self, proc, label):
        try:
            await _safe_kill_subprocess(proc, label)
        finally:
            self._untrack_subprocess(proc)

    async def _cleanup_tracked_subprocesses(self):
        """在线程事件循环关闭前回收所有仍登记的媒体子进程。"""
        with self._control_lock:
            records = list(self._subprocesses.values())
        for record in records:
            await self._cleanup_subprocess(
                record.get('proc'),
                f"{record.get('label', 'ffmpeg')}-loop-final",
            )

    def force_terminate_subprocesses(self):
        """跨线程终止当前 Handler 启动且仍存活的媒体子进程。"""
        with self._control_lock:
            records = list(self._subprocesses.items())

        killed = 0
        killed_psutil_processes = []
        for pid, record in records:
            proc = record['proc']
            if getattr(proc, 'returncode', None) is not None:
                self._untrack_subprocess(proc)
                continue
            try:
                expected_create_time = record.get('create_time')
                if psutil is not None and expected_create_time is not None:
                    process = psutil.Process(pid)
                    if (
                        abs(process.create_time() - expected_create_time) > 0.01
                    ):
                        logger.warning(
                            '跳过PID已复用的媒体进程: pid=%s label=%s',
                            pid,
                            record['label'],
                        )
                        continue
                    process_name = process.name().lower()
                    if 'ffmpeg' not in process_name and 'ffprobe' not in process_name:
                        logger.warning(
                            '拒绝终止非媒体进程: pid=%s name=%s label=%s',
                            pid,
                            process_name,
                            record['label'],
                        )
                        continue
                    for child in process.children(recursive=True):
                        try:
                            child.kill()
                            killed_psutil_processes.append(child)
                            killed += 1
                        except psutil.Error:
                            pass
                    process.kill()
                    killed_psutil_processes.append(process)
                else:
                    # 创建时间无法取得时不再按 PID 二次查找，直接使用
                    # asyncio 子进程持有的原始句柄，避免误杀复用 PID。
                    proc.kill()
                killed += 1
                self._untrack_subprocess(proc)
                logger.warning(
                    '已强制终止媒体进程: channel=%s pid=%s label=%s',
                    self.channel_id,
                    pid,
                    record['label'],
                )
            except Exception:
                logger.exception(
                    '终止媒体进程失败: channel=%s pid=%s label=%s',
                    self.channel_id,
                    pid,
                    record['label'],
                )
        if psutil is not None and killed_psutil_processes:
            try:
                _, alive = psutil.wait_procs(
                    killed_psutil_processes,
                    timeout=1.0,
                )
                for process in alive:
                    logger.warning(
                        '媒体进程已发送终止信号但尚未退出: pid=%s',
                        process.pid,
                    )
            except _PROCESS_ERRORS:
                logger.exception('等待媒体进程退出失败，频道=%s', self.channel_id)
        return killed

    def run(self):
        if log_enabled:
            logger.info(f'开始处理，频道: {self.channel_id}')
        loop_t = asyncio.new_event_loop()
        with self._control_lock:
            self._loop = loop_t
        try:
            asyncio.set_event_loop(loop_t)
            loop_t.run_until_complete(self.main())
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception('播放处理器异常退出，频道: %s', self.channel_id)
        finally:
            try:
                pending = asyncio.all_tasks(loop_t)
                for task in pending:
                    task.cancel()
                if pending:
                    loop_t.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                logger.exception('取消播放残留任务失败，频道: %s', self.channel_id)
            try:
                loop_t.run_until_complete(self._cleanup_tracked_subprocesses())
                loop_t.run_until_complete(loop_t.shutdown_asyncgens())
                loop_t.run_until_complete(asyncio.sleep(0))
            except Exception:
                logger.exception('回收媒体子进程失败，频道: %s', self.channel_id)
            asyncio.set_event_loop(None)
            loop_t.close()
            with self._control_lock:
                self._loop = None
                self._push_task = None
                self._leave_task = None
                self._subprocesses.clear()
            with state_lock:
                if _active_handlers.get(self.channel_id) is self:
                    _active_handlers.pop(self.channel_id, None)
                    play_list.pop(self.channel_id, None)
                    guild_status.pop(self.channel_id, None)
                    playlist_handle_status.pop(self.channel_id, None)
            self.finished.set()
            if log_enabled:
                logger.info(f'处理完成，频道: {self.channel_id}')

    async def main(self):
        start_event = asyncio.Event()
        task1 = asyncio.create_task(self.push())
        task2 = asyncio.create_task(self.keepalive())
        task3 = asyncio.create_task(self.stop(start_event))
        with self._control_lock:
            self._push_task = task1
        if self.stop_requested.is_set():
            task1.cancel()
        try:
            done, _ = await asyncio.wait(
                [task1, task2],
                return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                if task.cancelled():
                    continue
                error = task.exception()
                if error is not None:
                    logger.error(
                        '播放任务提前结束，频道=%s: %s',
                        self.channel_id,
                        error,
                    )
        finally:
            for task in (task1, task2):
                if not task.done():
                    task.cancel()
            await asyncio.gather(task1, task2, return_exceptions=True)
            with self._control_lock:
                if self._push_task is task1:
                    self._push_task = None
            start_event.set()
            await task3

    async def stop(self, start_event):
        await start_event.wait()
        with state_lock:
            owns_channel = _active_handlers.get(self.channel_id) is self
            may_leave = (
                owns_channel
                and not self.detached.is_set()
                and not self.leave_delegated.is_set()
            )
            if may_leave:
                # 与 detach_stuck_handlers() 在同一把锁下完成决策，确保
                # 已经开始的旧 leave 完成前不会释放频道给新处理器。
                self._leave_started.set()

        if not may_leave:
            self._leave_finished.set()
            try:
                await self.requestor.close()
            except (Exception, asyncio.CancelledError):
                pass
            self.finished.set()
            return

        leave_task = asyncio.create_task(
            self.requestor.leave(self._rtp_channel_id or self.channel_id)
        )
        with self._control_lock:
            self._leave_task = leave_task
        if self.stop_requested.is_set():
            leave_task.cancel()
        try:
            await asyncio.wait_for(leave_task, timeout=5)
        except (Exception, asyncio.CancelledError):
            pass
        finally:
            with self._control_lock:
                if self._leave_task is leave_task:
                    self._leave_task = None
            self._leave_finished.set()
            try:
                await self.requestor.close()
            except (Exception, asyncio.CancelledError):
                pass
            with state_lock:
                if _active_handlers.get(self.channel_id) is self:
                    play_list.pop(self.channel_id, None)
                    playlist_handle_status.pop(self.channel_id, None)
                    guild_status.pop(self.channel_id, None)
                    _active_handlers.pop(self.channel_id, None)
            self.finished.set()
        if log_enabled:
            logger.info(f'停止并清理，频道: {self.channel_id}')

    async def push(self):
        with state_lock:
            if _active_handlers.get(self.channel_id) is not self:
                return
            playlist_handle_status[self.channel_id] = True
        try:
            if self.should_stop():
                return
            await asyncio.sleep(1)
            if self.should_stop():
                return
            with state_lock:
                if _active_handlers.get(self.channel_id) is not self:
                    return
                state = play_list.get(self.channel_id)
                rtp_ch = state.get('voice_channel') if state else None
            if rtp_ch:
                self._rtp_channel_id = rtp_ch

                try:
                    res = await self.requestor.join(self._rtp_channel_id)
                except Exception as first_error:
                    # 仅在 join 失败时清理可能残留的旧会话后重试一次。
                    try:
                        await self.requestor.leave(self._rtp_channel_id)
                    except Exception:
                        pass
                    try:
                        res = await self.requestor.join(self._rtp_channel_id)
                    except Exception as retry_error:
                        if log_enabled:
                            logger.error(
                                '加入频道失败: 首次=%s, 重试=%s',
                                first_error,
                                retry_error,
                            )
                        raise RuntimeError(f'加入频道失败 {retry_error}')

                rtp_url = f"rtp://{res['ip']}:{res['port']}?rtcpport={res['rtcp_port']}"
                if log_enabled:
                    try:
                        logger.info(f"RTP配置: {res}")
                    except Exception:
                        pass

                audio_ssrc = res.get('audio_ssrc', 1111)
                audio_pt = res.get('audio_pt', 111)

                bitrate = int(res['bitrate'] / 1000)
                bitrate *= 0.9 if bitrate > 100 else 1

                while True:
                    if self.should_stop():
                        return
                    with state_lock:
                        waiting = guild_status.get(self.channel_id) == Status.WAIT
                    if not waiting:
                        break
                    await asyncio.sleep(2)

                if self.should_stop():
                    return
                encoder_args = [
                    ffmpeg_bin,
                    '-re',
                    '-loglevel', 'level+info',
                    '-nostats',
                    '-f', 'wav',
                    '-i', '-',
                    '-map', '0:a:0',
                    '-acodec', 'libopus',
                    '-ab', f'{bitrate}k',
                    '-ac', '2',
                    '-ar', '48000',
                    '-filter:a', 'volume=1.0',
                    '-f', 'tee',
                    f'[select=a:f=rtp:ssrc={audio_ssrc}:payload_type={audio_pt}]{rtp_url}',
                ]
                if log_enabled:
                    logger.info('运行 ffmpeg 命令: %s', ' '.join(map(str, encoder_args)))
                p = self._track_subprocess(
                    await asyncio.create_subprocess_exec(
                        *encoder_args,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL
                    ),
                    "ffmpeg-encode",
                )

                while True:
                    await asyncio.sleep(0.5)
                    if self.should_stop():
                        return
                    with state_lock:
                        if _active_handlers.get(self.channel_id) is not self:
                            return
                        state = play_list.get(self.channel_id)
                        if state is None:
                            music_info = None
                        elif state['now_playing'] and not state['play_list']:
                            music_info = state['now_playing']
                        elif state['play_list']:
                            music_info = state['play_list'].pop(0)
                            music_info['start'] = time.time()
                            state['now_playing'] = music_info
                        else:
                            state['_stopping'] = True
                            guild_status[self.channel_id] = Status.STOP
                            music_info = None
                    if music_info is None:
                        break

                    if isinstance(music_info, dict) and 'file' in music_info:
                            file = music_info['file']

                            # 检查是否是歌单歌曲标记，如果是则尝试解析
                            if file.startswith("PLAYLIST_SONG:"):
                                try:
                                    try:
                                        from ..utils import resolve_marker_batch
                                    except ImportError:
                                        from utils import resolve_marker_batch
                                    resolved = resolve_marker_batch([file], 1)
                                    if file in resolved:
                                        file = resolved[file]
                                        logger.info(f'[歌单URL] 已解析: {music_info.get("extra", {}).get("音乐名字", file)}')
                                    else:
                                        logger.warning(f'[歌单URL] 解析失败，跳过: {music_info.get("extra", {}).get("音乐名字", file)}')
                                        _discard_current_item(self.channel_id, self)
                                        continue
                                except Exception as e:
                                    logger.error(f'[歌单URL] 解析异常: {e}')
                                    _discard_current_item(self.channel_id, self)
                                    continue
                            elif file.startswith("QQ_PLAYLIST_SONG:"):
                                try:
                                    try:
                                        from ..qq_utils import resolve_qq_marker_batch
                                    except ImportError:
                                        from qq_utils import resolve_qq_marker_batch
                                    resolved = resolve_qq_marker_batch([file], 1)
                                    if file in resolved:
                                        file = resolved[file]
                                        logger.info(f'[QQ歌单URL] 已解析: {music_info.get("extra", {}).get("音乐名字", file)}')
                                    else:
                                        logger.warning(f'[QQ歌单URL] 解析失败，跳过: {music_info.get("extra", {}).get("音乐名字", file)}')
                                        _discard_current_item(self.channel_id, self)
                                        continue
                                except Exception as e:
                                    logger.error(f'[QQ歌单URL] 解析异常: {e}')
                                    _discard_current_item(self.channel_id, self)
                                    continue
                            elif file.startswith("BILI_PLAYLIST_SONG:"):
                                try:
                                    try:
                                        from ..bili_utils import resolve_bili_marker_batch
                                    except ImportError:
                                        from bili_utils import resolve_bili_marker_batch
                                    resolved = resolve_bili_marker_batch([file], 1)
                                    if file in resolved:
                                        file = resolved[file]
                                        logger.info(f'[Bili歌单URL] 已解析: {music_info.get("extra", {}).get("音乐名字", file)}')
                                    else:
                                        logger.warning(f'[Bili歌单URL] 解析失败，跳过: {music_info.get("extra", {}).get("音乐名字", file)}')
                                        _discard_current_item(self.channel_id, self)
                                        continue
                                except Exception as e:
                                    logger.error(f'[Bili歌单URL] 解析异常: {e}')
                                    _discard_current_item(self.channel_id, self)
                                    continue

                            if self.should_stop():
                                return
                            extra_command = ''
                            if 'extra' in music_info and music_info['extra']:
                                extra_data = music_info['extra']
                                extra_command = extra_data.get('extra_command', '')

                                def pack_command(full_command, name, value):
                                    if value:
                                        full_command += f' -{name} "{value}"'
                                    return full_command

                                if isinstance(extra_data, dict):
                                    extra_command = pack_command(extra_command, 'headers', extra_data.get('header'))
                                    extra_command = pack_command(extra_command, 'cookies', extra_data.get('cookies'))
                                    extra_command = pack_command(extra_command, 'user_agent', extra_data.get('user_agent'))
                                    extra_command = pack_command(extra_command, 'referer', extra_data.get('referer'))

                            ss_value = music_info.get('ss', 0)

                            # B站来源标记：用于时长、chunk、超时等参数优化
                            _extra = music_info.get('extra', {}) if isinstance(music_info.get('extra'), dict) else {}
                            _is_bili = _extra.get('platform') == 'bili'

                            audio_duration = 0
                            # 方案A：如果携带了已知时长，跳过ffprobe（解决B站.m4s无时长头）
                            if _extra.get('duration', 0) > 0:
                                audio_duration = float(_extra['duration'])
                                if log_enabled:
                                    logger.info(f'使用API已知时长: {audio_duration:.2f}秒（跳过探测）')
                            else:
                                if log_enabled:
                                    logger.info(f'获取音频时长: {file}')
                                try:
                                    try:
                                        from ..config import FFPROBE_PATH as _ffprobe_path
                                    except ImportError:
                                        from config import FFPROBE_PATH as _ffprobe_path

                                    has_ffprobe = bool(_ffprobe_path and os.path.exists(_ffprobe_path))
                                    if has_ffprobe:
                                        duration_args = [
                                            _ffprobe_path,
                                            '-v', 'quiet',
                                            '-show_entries', 'format=duration',
                                            '-of', 'csv=p=0',
                                            file,
                                        ]
                                        if log_enabled:
                                            logger.info(
                                                '执行时长获取命令: %s',
                                                ' '.join(map(str, duration_args)),
                                            )
                                        dur_proc = self._track_subprocess(
                                            await asyncio.create_subprocess_exec(
                                                *duration_args,
                                                stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE
                                            ),
                                            "ffprobe-duration",
                                        )
                                        try:
                                            stdout, _ = await asyncio.wait_for(
                                                dur_proc.communicate(),
                                                timeout=20,
                                            )
                                            if stdout:
                                                duration_text = stdout.decode('utf-8', errors='ignore').strip()
                                                if duration_text and duration_text != 'N/A':
                                                    try:
                                                        audio_duration = float(duration_text)
                                                        if log_enabled:
                                                            logger.info(f'音频时长: {audio_duration:.2f} 秒')
                                                    except ValueError:
                                                        if log_enabled:
                                                            logger.warning(f'无法解析音频时长: {duration_text}')
                                                elif log_enabled:
                                                    logger.warning(f'ffprobe返回空时长: {duration_text}')
                                            elif log_enabled:
                                                logger.warning(f'ffprobe无输出，尝试备用方法')
                                        finally:
                                            await self._cleanup_subprocess(
                                                dur_proc,
                                                "ffprobe-dur",
                                            )

                                    if audio_duration <= 0:
                                        if log_enabled:
                                            logger.info(f'使用备用方法获取时长')
                                        backup_args = [ffmpeg_bin, '-i', file]
                                        if extra_command:
                                            backup_args.extend(shlex.split(extra_command))
                                        backup_args.extend(['-f', 'null', '-'])
                                        bak_proc = self._track_subprocess(
                                            await asyncio.create_subprocess_exec(
                                                *backup_args,
                                                stdout=asyncio.subprocess.DEVNULL,
                                                stderr=asyncio.subprocess.PIPE
                                            ),
                                            "ffmpeg-duration",
                                        )
                                        try:
                                            _, stderr = await asyncio.wait_for(
                                                bak_proc.communicate(),
                                                timeout=30,
                                            )
                                            stderr_text = stderr.decode('utf-8', errors='ignore')
                                        finally:
                                            await self._cleanup_subprocess(
                                                bak_proc,
                                                "ffmpeg-dur",
                                            )

                                        import re
                                        duration_match = re.search(r'Duration: (\d{2}):(\d{2}):(\d{2})\.(\d{2})', stderr_text)
                                        if duration_match:
                                            hours = int(duration_match.group(1))
                                            minutes = int(duration_match.group(2))
                                            seconds = int(duration_match.group(3))
                                            centiseconds = int(duration_match.group(4))
                                            audio_duration = hours * 3600 + minutes * 60 + seconds + centiseconds / 100
                                            if log_enabled:
                                                logger.info(f'备用方法获取音频时长: {audio_duration:.2f} 秒')
                                        else:
                                            if log_enabled:
                                                logger.warning(f'备用方法也无法获取音频时长')

                                except Exception as e:
                                    if log_enabled:
                                        logger.error(f'获取音频时长失败: {e}')
                                    audio_duration = 0

                            expected_duration = audio_duration

                            if expected_duration <= 0:
                                expected_duration = 180.0
                                if log_enabled:
                                    logger.info(f'使用默认音频时长: {expected_duration:.2f} 秒')

                            try:
                                with state_lock:
                                    state = (
                                        play_list.get(self.channel_id)
                                        if _active_handlers.get(self.channel_id) is self
                                        else None
                                    )
                                    if state and state['now_playing']:
                                        state['now_playing']['duration'] = float(expected_duration)
                            except Exception:
                                pass

                            # 方案B+E：B站DASH流优化 — 更大超时、B站专用请求头
                            # 改用 create_subprocess_exec（参数列表）避免 Windows cmd.exe
                            # 破坏URL中的%编码字符（%3D/%2F等）
                            _cmd2 = _build_decoder_command(
                                file,
                                ss_value=ss_value,
                                is_bili=_is_bili,
                                extra_command=extra_command,
                            )
                            if log_enabled:
                                logger.info(f'正在播放文件: {file}')
                                logger.info(f'解码命令: {" ".join(_cmd2)[:300]}')
                            if self.should_stop():
                                return
                            p2 = self._track_subprocess(
                                await asyncio.create_subprocess_exec(
                                    *_cmd2,
                                    stdin=asyncio.subprocess.DEVNULL,
                                    stdout=asyncio.subprocess.PIPE,
                                    stderr=asyncio.subprocess.PIPE
                                ),
                                "ffmpeg-decode",
                            )

                            if log_enabled:
                                logger.info(f'开始播放音频，预期时长: {expected_duration:.2f} 秒')

                            first_music_start_time = time.time()

                            with state_lock:
                                owns_channel = (
                                    _active_handlers.get(self.channel_id) is self
                                )
                                if owns_channel:
                                    if self.channel_id not in guild_status:
                                        guild_status[self.channel_id] = Status.END
                                    should_trigger_start = (
                                        guild_status[self.channel_id] == Status.END
                                    )
                                    if should_trigger_start:
                                        guild_status[self.channel_id] = Status.PLAYING
                                else:
                                    should_trigger_start = False
                            if not owns_channel:
                                return

                            if should_trigger_start:
                                if original_loop:
                                    asyncio.run_coroutine_threadsafe(
                                        trigger_event(
                                            Status.START,
                                            PlayInfo(self.channel_id, file, self.token, music_info.get('extra'))
                                        ),
                                        original_loop
                                    )
                                if log_enabled:
                                    logger.info(f'开始播放: {file}，频道: {self.channel_id}')

                            # 方案E：B站DASH流使用更大缓冲区（2秒），减少I/O抖动
                            chunk_size = 384000 if _is_bili else 96000
                            total_audio = b''
                            last_write_time = 0.0
                            consecutive_empty_reads = 0
                            max_empty_reads = 10

                            try:
                                skip_song = False
                                while True:
                                    if self.should_stop():
                                        return
                                    if p2 and p2.stdout:
                                        try:
                                            new_audio = await asyncio.wait_for(
                                                p2.stdout.read(chunk_size),
                                                timeout=2.0
                                            )
                                        except asyncio.TimeoutError:
                                            if p2.returncode is not None:
                                                if log_enabled:
                                                    logger.warning(f'解码进程已退出: {file}')
                                                break
                                            consecutive_empty_reads += 1
                                            if consecutive_empty_reads >= max_empty_reads:
                                                if log_enabled:
                                                    logger.warning(f'连续{max_empty_reads}次读取超时，可能网络问题: {file}')
                                                break
                                            continue

                                        if not new_audio:
                                            consecutive_empty_reads += 1
                                            if consecutive_empty_reads >= max_empty_reads:
                                                if p2.stderr:
                                                    try:
                                                        err_text = (await p2.stderr.read()).decode('utf-8', errors='ignore').strip()
                                                        if err_text and log_enabled:
                                                            logger.warning(f'解码进程stderr: {err_text[:500]}')
                                                    except Exception:
                                                        pass

                                                if total_audio and p and p.stdin:
                                                    try:
                                                        p.stdin.write(total_audio)
                                                        await p.stdin.drain()
                                                        if log_enabled:
                                                            logger.info(f'写入剩余音频数据: {len(total_audio)} 字节')
                                                    except Exception as e:
                                                        if log_enabled:
                                                            logger.error(f'写入剩余音频数据异常: {e}')

                                                # 解码器未产出任何音频数据 → 直接跳过，不等待
                                                if not total_audio:
                                                    if log_enabled:
                                                        logger.warning(f'解码器无音频输出，跳过: {file}')
                                                else:
                                                    actual_duration = max(0.0, time.time() - first_music_start_time)
                                                    min_play_time = 30.0
                                                    target_duration = max(expected_duration, min_play_time)
                                                    if actual_duration < target_duration:
                                                        wait_sec = target_duration - actual_duration
                                                        if log_enabled:
                                                            logger.info(f'等待剩余时间: {wait_sec:.2f} 秒 (目标时长: {target_duration:.2f} 秒)')
                                                        await asyncio.sleep(wait_sec)

                                                if log_enabled:
                                                    logger.info(f'音频播放完成: {file}')
                                                break
                                        else:
                                            consecutive_empty_reads = 0

                                        total_audio += new_audio

                                        while len(total_audio) >= chunk_size:
                                            audio_slice = total_audio[:chunk_size]
                                            total_audio = total_audio[chunk_size:]
                                            if p and p.stdin:
                                                try:
                                                    now = time.time()
                                                    if last_write_time > 0:
                                                        elapsed = now - last_write_time
                                                        if elapsed < 0.02:
                                                            await asyncio.sleep(0.02 - elapsed)
                                                    while True:
                                                        with state_lock:
                                                            paused = (
                                                                guild_status.get(self.channel_id)
                                                                == Status.PAUSE
                                                            )
                                                        if not paused:
                                                            break
                                                        await asyncio.sleep(0.1)
                                                    p.stdin.write(audio_slice)
                                                    await p.stdin.drain()
                                                    last_write_time = time.time()

                                                    with state_lock:
                                                        owns_channel = (
                                                            _active_handlers.get(self.channel_id)
                                                            is self
                                                        )
                                                        channel_state = (
                                                            play_list.get(self.channel_id)
                                                            if owns_channel
                                                            else None
                                                        )
                                                        if channel_state and channel_state['now_playing']:
                                                            channel_state['now_playing']['ss'] = (
                                                                last_write_time - first_music_start_time
                                                            )
                                                        playback_status = (
                                                            guild_status.get(self.channel_id)
                                                            if owns_channel
                                                            else Status.STOP
                                                        )
                                                        if playback_status == Status.SKIP:
                                                            guild_status[self.channel_id] = Status.END
                                                        elif playback_status == Status.STOP and channel_state:
                                                            channel_state['play_list'] = []

                                                    if playback_status == Status.SKIP:
                                                        if log_enabled:
                                                            logger.info(f'跳过当前歌曲: {file}')
                                                        skip_song = True
                                                        await self._cleanup_subprocess(
                                                            p2,
                                                            "ffmpeg-decode-skip",
                                                        )
                                                        break
                                                    if playback_status == Status.STOP:
                                                        if log_enabled:
                                                            logger.info(f'停止播放: {file}')
                                                        await self._cleanup_subprocess(
                                                            p2,
                                                            "ffmpeg-decode",
                                                        )
                                                        await self._cleanup_subprocess(
                                                            p,
                                                            "ffmpeg-encode",
                                                        )
                                                        return
                                                except Exception as e:
                                                    if log_enabled:
                                                        logger.error(f'音频写入异常: {e}')
                                                    break
                                        if skip_song:
                                            break
                                    else:
                                        if log_enabled:
                                            logger.error(f'音频进程异常: {file}')
                                        break
                            except Exception as e:
                                if log_enabled:
                                    logger.error(f'音频播放异常: {e}')

                            if log_enabled:
                                logger.info(f'歌曲播放完成: {file}')
                            await self._cleanup_subprocess(
                                p2,
                                "ffmpeg-decode-done",
                            )

                            # 完成当前歌曲，并根据单曲/列表循环模式重新入队
                            if self.should_stop():
                                return
                            with state_lock:
                                if _active_handlers.get(self.channel_id) is not self:
                                    return
                                completion = _complete_current_track_locked(
                                    self.channel_id
                                )
                                channel_state = completion['state']
                                cycle_mode = completion['mode']
                                queue_empty = completion['queue_empty']
                                if queue_empty:
                                    playlist_handle_status[self.channel_id] = False
                                refill_view = (
                                    {self.channel_id: channel_state}
                                    if channel_state is not None
                                    else {}
                                )

                            if cycle_mode == 'single':
                                if log_enabled:
                                    logger.info(f'单曲循环: 重新加入队列，频道: {self.channel_id}')
                            elif cycle_mode == 'playlist':
                                if log_enabled:
                                    logger.info(f'列表循环: 当前歌曲移至队尾，频道: {self.channel_id}')

                            if queue_empty:
                                if log_enabled:
                                    logger.info(f'播放列表结束，频道: {self.channel_id}')
                            else:
                                try:
                                    try:
                                        from ..utils import refill_playlist_queue
                                    except ImportError:
                                        from utils import refill_playlist_queue
                                    refill_playlist_queue(
                                        self.channel_id,
                                        refill_view,
                                        lock=state_lock,
                                    )
                                except Exception:
                                    pass
                                if self.should_stop():
                                    return
                                try:
                                    try:
                                        from ..qq_utils import refill_qq_playlist_queue
                                    except ImportError:
                                        from qq_utils import refill_qq_playlist_queue
                                    refill_qq_playlist_queue(
                                        self.channel_id,
                                        refill_view,
                                        lock=state_lock,
                                    )
                                except Exception:
                                    pass
                                if self.should_stop():
                                    return
                                try:
                                    try:
                                        from ..bili_utils import refill_bili_playlist_queue
                                    except ImportError:
                                        from bili_utils import refill_bili_playlist_queue
                                    refill_bili_playlist_queue(
                                        self.channel_id,
                                        refill_view,
                                        lock=state_lock,
                                    )
                                except Exception:
                                    pass
                                if self.should_stop():
                                    return
                                with state_lock:
                                    if (
                                        _active_handlers.get(self.channel_id) is self
                                        and play_list.get(self.channel_id)
                                        is channel_state
                                    ):
                                        guild_status[self.channel_id] = Status.END
                                if log_enabled:
                                    logger.info(f'准备播放下一首歌曲，频道: {self.channel_id}')
                    else:
                        break
                await self._cleanup_subprocess(p, "ffmpeg-encode-done")
        except Exception as e:
            if log_enabled:
                logger.error(f'推流过程中出现错误: {str(e)}', exc_info=True)
        finally:
            try:
                await self._cleanup_subprocess(
                    locals().get('p2'),
                    "ffmpeg-decode-final",
                )
            except Exception:
                pass
            try:
                await self._cleanup_subprocess(
                    locals().get('p'),
                    "ffmpeg-encode-final",
                )
            except Exception:
                pass

    async def keepalive(self):
        consecutive_failures = 0
        while True:
            await asyncio.sleep(45)
            if self.should_stop():
                return
            try:
                if self._rtp_channel_id:
                    await self.requestor.keep_alive(self._rtp_channel_id)
                elif self.channel_id:
                    await self.requestor.keep_alive(self.channel_id)
                consecutive_failures = 0
                if log_enabled:
                    logger.info(f'[保活] 频道={self.channel_id}')
            except Exception as exc:
                consecutive_failures += 1
                logger.warning(
                    '[保活] 频道=%s 失败（%d/3）: %s',
                    self.channel_id,
                    consecutive_failures,
                    exc,
                )
                if consecutive_failures >= 3:
                    raise RuntimeError(
                        f'频道 {self.channel_id} 连续保活失败'
                    ) from exc

async def start():
    global original_loop
    original_loop = asyncio.get_event_loop()
    while True:
        await asyncio.sleep(1000)

from typing import Coroutine, TypeVar, Any
T = TypeVar('T')

async def run_async(task: CoroutineType[Any, Any, T], timeout=10) -> T:
    if original_loop:
        return asyncio.run_coroutine_threadsafe(task, original_loop).result(timeout=timeout)
    return None

def run():
    asyncio.run(start())
