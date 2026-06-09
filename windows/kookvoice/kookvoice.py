import asyncio
import os
import shlex
import threading
import time
import logging
from enum import Enum, unique
from typing import Dict, Union, List, Any, Optional, Coroutine as CoroutineType
from asyncio import AbstractEventLoop
try:
    from .requestor import VoiceRequestor
except ImportError:
    from requestor import VoiceRequestor

# 配置日志
logger = logging.getLogger(__name__)
log_enabled = False

def configure_logging(enabled: bool = True):
    global log_enabled
    log_enabled = enabled
    if enabled:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    else:
        logging.disable(logging.CRITICAL)

ffmpeg_bin = os.environ.get('FFMPEG_BIN', 'ffmpeg')

original_loop = None  # 初始化为None，后面会赋值为AbstractEventLoop

def set_ffmpeg(path):
    global ffmpeg_bin
    ffmpeg_bin = path


def set_loop(loop):
    global original_loop
    original_loop = loop


async def _safe_kill_subprocess(proc, label="ffmpeg"):
    """安全终止 asyncio 子进程：先关闭管道再 kill，防止 Windows ProactorEventLoop 管道泄漏"""
    if proc is None:
        return
    # 先关闭所有管道，防止 ProactorEventLoop 的 __del__ 报 closed pipe
    for pipe in (proc.stdin, proc.stdout, proc.stderr):
        if pipe is not None:
            try:
                pipe.close()
            except Exception:
                pass
    # 再终止进程
    try:
        if proc.returncode is None:
            proc.kill()
    except Exception:
        pass
    # 等待进程结束并回收资源
    try:
        await asyncio.wait_for(proc.wait(), timeout=3)
    except Exception:
        pass
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
                               'now_playing': {'file': '歌曲文件', 'ss': 0, 'start': 0,'extra':{}},
                               'play_list': [
                                   {'file': '路径', 'ss': 0}]}}

playlist_handle_status = {}

class Player:
    def __init__(self, channel_id, token=None):
        """
            :param str channel_id: 推流语音频道id（唯一会话标识）
            :param str token: 推流机器人token
        """
        self.channel_id = str(channel_id)

        if self.channel_id in play_list:
            if token is None:
                token = play_list[self.channel_id]['token']
            elif token != play_list[self.channel_id]['token']:
                raise ValueError('播放歌曲过程中无法更换token')
        self.token = str(token) if token else ""

    def join(self, guild_id: str = ""):
        """加入语音频道并开始推流
            :param str guild_id: 服务器id（元数据）"""
        global guild_status
        if not self.channel_id:
            raise ValueError('第一次启动推流时，你需要指定语音频道id')
        if not self.token:
            raise ValueError('第一次启动推流时，你需要指定机器人token')
        if self.channel_id not in play_list:
            play_list[self.channel_id] = {'token': self.token,
                                          'guild_id': str(guild_id),
                                          'voice_channel': self.channel_id,
                                          'repeat': False,
                                          '_queue_backup': None,
                                          'now_playing': None,
                                          'play_list': []}
        guild_status[self.channel_id] = Status.WAIT
        play_list[self.channel_id]['voice_channel'] = self.channel_id
        if log_enabled:
            logger.info(f'加入语音频道: {self.channel_id}，服务器: {guild_id}')
        PlayHandler(self.channel_id, self.token).start()

    def add_music(self, music: str, extra_data: dict = {}):
        """
        添加音乐到播放列表
            :param str music: 音乐文件路径或音乐链接
            :param dict extra_data: 可以在这里保存音乐信息
        """
        if not self.channel_id:
            raise ValueError('频道id不能为空')
        if not self.token:
            raise ValueError('第一次启动推流时，你需要指定机器人token')
        need_start = False
        if self.channel_id not in play_list:
            need_start = True
            play_list[self.channel_id] = {'token': self.token,
                                          'guild_id': '',
                                          'voice_channel': self.channel_id,
                                          'repeat': False,
                                          '_queue_backup': None,
                                          'now_playing': None,
                                          'play_list': []}
        # 检查是否是歌单歌曲标记，如果是则跳过文件存在检查
        if not music.startswith("PLAYLIST_SONG:") and not music.startswith("QQ_PLAYLIST_SONG:") and not music.startswith("BILI_PLAYLIST_SONG:"):
            if 'http' not in music:
                if not os.path.exists(music):
                    raise ValueError('文件不存在')

        play_list[self.channel_id]['voice_channel'] = self.channel_id
        play_list[self.channel_id]['play_list'].append({'file': music, 'ss': 0, 'extra': extra_data})
        if log_enabled:
            logger.info(f'添加音乐到播放列表，频道: {self.channel_id}，音乐: {music}')
        if self.channel_id in guild_status and guild_status[self.channel_id] == Status.WAIT:
            guild_status[self.channel_id] = Status.END
        if need_start:
            if play_list[self.channel_id]['play_list']:
                PlayHandler(self.channel_id, self.token).start()
            elif ((self.channel_id not in playlist_handle_status
                   or (not playlist_handle_status[self.channel_id]))
                  and play_list[self.channel_id]['play_list']):
                PlayHandler(self.channel_id, self.token).start()

    def stop(self):
        global guild_status, playlist_handle_status
        if self.channel_id not in play_list:
            raise ValueError('该频道没有正在播放的歌曲')
        guild_status[self.channel_id] = Status.STOP
        if log_enabled:
            logger.info(f'停止播放，频道: {self.channel_id}')

    def skip(self, skip_amount: int = 1):
        '''
        跳过指定数量的歌曲
            :param amount int: 要跳过的歌曲数量,默认为一首
        '''
        global guild_status
        if self.channel_id not in play_list:
            raise ValueError('该频道没有正在播放的歌曲')
        for i in range(skip_amount - 1):
            try:
                if play_list[self.channel_id]['play_list']:
                    play_list[self.channel_id]['play_list'].pop(0)
            except:
                pass
        guild_status[self.channel_id] = Status.SKIP
        if log_enabled:
            logger.info(f'跳过了 {skip_amount} 首歌曲，频道: {self.channel_id}')

    def pause(self):
        global guild_status
        if self.channel_id not in play_list:
            raise ValueError('该频道没有正在播放的歌曲')
        guild_status[self.channel_id] = Status.PAUSE
        if log_enabled:
            logger.info(f'暂停播放，频道: {self.channel_id}')

    def resume(self):
        global guild_status
        if self.channel_id not in play_list:
            raise ValueError('该频道没有正在播放的歌曲')
        guild_status[self.channel_id] = Status.PLAYING
        if log_enabled:
            logger.info(f'继续播放，频道: {self.channel_id}')

    def list(self, json=True):
        if self.channel_id not in play_list:
            raise ValueError('该频道没有正在播放的歌曲')
        if json:
            result = []
            if play_list[self.channel_id]['now_playing']:
                result.append(play_list[self.channel_id]['now_playing'])
            result.extend(play_list[self.channel_id]['play_list'])
            return result
        else:
            return []

    def repeat_toggle(self):
        """切换单曲循环开关，返回切换后的状态"""
        if self.channel_id not in play_list:
            raise ValueError('该频道没有正在播放的歌曲')
        current = play_list[self.channel_id].get('repeat', False)
        play_list[self.channel_id]['repeat'] = not current
        if log_enabled:
            logger.info(f'单曲循环: {"开启" if not current else "关闭"}，频道: {self.channel_id}')
        return not current

    def shuffle_toggle(self):
        """切换随机播放，返回 (enabled, count)"""
        import random
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
        global play_list
        if self.channel_id not in play_list:
            raise ValueError('该频道没有正在播放的歌曲')
        if play_list[self.channel_id]['now_playing']:
            now_play = play_list[self.channel_id]['now_playing'].copy()
            now_play['ss'] = int(music_seconds)
            if 'start' in now_play:
                del now_play['start']
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
        threading.Thread.__init__(self)
        self.token = token
        self.channel_id = channel_id
        self.requestor = VoiceRequestor(token)

    def run(self):
        if log_enabled:
            logger.info(f'开始处理，频道: {self.channel_id}')
        loop_t = asyncio.new_event_loop()
        asyncio.set_event_loop(loop_t)
        loop_t.run_until_complete(self.main())
        if log_enabled:
            logger.info(f'处理完成，频道: {self.channel_id}')

    async def main(self):
        start_event = asyncio.Event()
        task1 = asyncio.create_task(self.push())
        task2 = asyncio.create_task(self.keepalive())
        task3 = asyncio.create_task(self.stop(start_event))

        try:
            done, pending = await asyncio.wait(
                [task1, task2],
                return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for task in pending:
                task.cancel()
            # 允许取消后的清理逻辑执行
            await asyncio.sleep(0.1)

        start_event.set()
        await task3

    async def stop(self, start_event):
        await start_event.wait()
        global playlist_handle_status
        if self.channel_id in play_list:
            del play_list[self.channel_id]
        if self.channel_id in playlist_handle_status and playlist_handle_status[self.channel_id]:
            playlist_handle_status[self.channel_id] = False
        try:
            await self.requestor.leave(self._rtp_channel_id or self.channel_id)
        except:
            pass
        if log_enabled:
            logger.info(f'停止并清理，频道: {self.channel_id}')

    async def push(self):
        global playlist_handle_status
        playlist_handle_status[self.channel_id] = True
        try:
            await asyncio.sleep(1)
            if self.channel_id in play_list and 'voice_channel' in play_list[self.channel_id]:
                rtp_ch = play_list[self.channel_id]['voice_channel']
                self._rtp_channel_id = rtp_ch

                try:
                    await self.requestor.leave(self._rtp_channel_id)
                except:
                    pass
                try:
                    res = await self.requestor.join(self._rtp_channel_id)
                except Exception as e:
                    if log_enabled:
                        logger.error(f'加入频道失败: {e}')
                    raise RuntimeError(f'加入频道失败 {e}')

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

                while self.channel_id in guild_status and guild_status[self.channel_id] == Status.WAIT:
                    await asyncio.sleep(2)

                command = f"{ffmpeg_bin} -re -loglevel level+info -nostats -f wav -i - -map 0:a:0 -acodec libopus -ab {bitrate}k -ac 2 -ar 48000 -filter:a volume=1.0 -f tee [select=a:f=rtp:ssrc={audio_ssrc}:payload_type={audio_pt}]{rtp_url}"
                if log_enabled:
                    logger.info(f'运行 ffmpeg 命令: {command}')
                p = await asyncio.create_subprocess_shell(
                    command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )

                while True:
                    await asyncio.sleep(0.5)
                    if self.channel_id in play_list:
                        if play_list[self.channel_id]['now_playing'] and not play_list[self.channel_id]['play_list']:
                            music_info = play_list[self.channel_id]['now_playing']
                        else:
                            if play_list[self.channel_id]['play_list']:
                                music_info = play_list[self.channel_id]['play_list'].pop(0)
                                music_info['start'] = time.time()
                                play_list[self.channel_id]['now_playing'] = music_info
                            else:
                                break

                        if isinstance(music_info, dict) and 'file' in music_info:
                            file = music_info['file']

                            # 检查是否是歌单歌曲标记，如果是则尝试解析
                            if file.startswith("PLAYLIST_SONG:"):
                                try:
                                    from utils import resolve_marker_batch
                                    resolved = resolve_marker_batch([file], 1)
                                    if file in resolved:
                                        file = resolved[file]
                                        logger.info(f'[歌单URL] 已解析: {music_info.get("extra", {}).get("音乐名字", file)}')
                                    else:
                                        logger.warning(f'[歌单URL] 解析失败，跳过: {music_info.get("extra", {}).get("音乐名字", file)}')
                                        continue
                                except Exception as e:
                                    logger.error(f'[歌单URL] 解析异常: {e}')
                                    continue
                            elif file.startswith("QQ_PLAYLIST_SONG:"):
                                try:
                                    from qq_utils import resolve_qq_marker_batch
                                    resolved = resolve_qq_marker_batch([file], 1)
                                    if file in resolved:
                                        file = resolved[file]
                                        logger.info(f'[QQ歌单URL] 已解析: {music_info.get("extra", {}).get("音乐名字", file)}')
                                    else:
                                        logger.warning(f'[QQ歌单URL] 解析失败，跳过: {music_info.get("extra", {}).get("音乐名字", file)}')
                                        continue
                                except Exception as e:
                                    logger.error(f'[QQ歌单URL] 解析异常: {e}')
                                    continue
                            elif file.startswith("BILI_PLAYLIST_SONG:"):
                                try:
                                    from bili_utils import resolve_bili_marker_batch
                                    resolved = resolve_bili_marker_batch([file], 1)
                                    if file in resolved:
                                        file = resolved[file]
                                        logger.info(f'[Bili歌单URL] 已解析: {music_info.get("extra", {}).get("音乐名字", file)}')
                                    else:
                                        logger.warning(f'[Bili歌单URL] 解析失败，跳过: {music_info.get("extra", {}).get("音乐名字", file)}')
                                        continue
                                except Exception as e:
                                    logger.error(f'[Bili歌单URL] 解析异常: {e}')
                                    continue

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
                                        duration_command = f'"{_ffprobe_path}" -v quiet -show_entries format=duration -of csv=p=0 "{file}"'
                                        if log_enabled:
                                            logger.info(f'执行时长获取命令: {duration_command}')
                                        dur_proc = await asyncio.create_subprocess_shell(
                                            duration_command,
                                            stdout=asyncio.subprocess.PIPE,
                                            stderr=asyncio.subprocess.PIPE
                                        )
                                        try:
                                            stdout, _ = await dur_proc.communicate()
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
                                            await _safe_kill_subprocess(dur_proc, "ffprobe-dur")

                                    if audio_duration <= 0:
                                        if log_enabled:
                                            logger.info(f'使用备用方法获取时长')
                                        backup_command = f'{ffmpeg_bin} -i "{file}" {extra_command} -f null -'
                                        bak_proc = await asyncio.create_subprocess_shell(
                                            backup_command,
                                            stdout=asyncio.subprocess.DEVNULL,
                                            stderr=asyncio.subprocess.PIPE
                                        )
                                        try:
                                            _, stderr = await bak_proc.communicate()
                                            stderr_text = stderr.decode('utf-8', errors='ignore')
                                        finally:
                                            await _safe_kill_subprocess(bak_proc, "ffmpeg-dur")

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
                                if self.channel_id in play_list and play_list[self.channel_id]['now_playing']:
                                    play_list[self.channel_id]['now_playing']['duration'] = float(expected_duration)
                            except Exception:
                                pass

                            # 方案B+E：B站DASH流优化 — 更大超时、B站专用请求头
                            # 改用 create_subprocess_exec（参数列表）避免 Windows cmd.exe
                            # 破坏URL中的%编码字符（%3D/%2F等）
                            _timeout_us = 60000000 if _is_bili else 30000000
                            _cmd2 = [
                                ffmpeg_bin, '-nostats',
                                '-reconnect', '1', '-reconnect_streamed', '1',
                                '-reconnect_delay_max', '5',
                                '-timeout', str(_timeout_us),
                            ]
                            if _is_bili:
                                _cmd2.extend([
                                    '-user_agent',
                                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                                    '-referer', 'https://www.bilibili.com/',
                                ])
                            _cmd2.extend(['-ss', str(ss_value), '-i', file])
                            if extra_command:
                                _cmd2.extend(shlex.split(extra_command))
                            _cmd2.extend([
                                '-filter:a', 'volume=0.4',
                                '-acodec', 'pcm_s16le', '-ac', '2', '-ar', '48000',
                                '-f', 'wav', '-y', '-',
                            ])
                            if log_enabled:
                                logger.info(f'正在播放文件: {file}')
                                logger.info(f'解码命令: {" ".join(_cmd2)[:300]}')
                            p2 = await asyncio.create_subprocess_exec(
                                *_cmd2,
                                stdin=asyncio.subprocess.DEVNULL,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.DEVNULL
                            )

                            if log_enabled:
                                logger.info(f'开始播放音频，预期时长: {expected_duration:.2f} 秒')

                            first_music_start_time = time.time()

                            if self.channel_id not in guild_status:
                                guild_status[self.channel_id] = Status.END

                            if guild_status[self.channel_id] == Status.END:
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
                                guild_status[self.channel_id] = Status.PLAYING

                            # 方案E：B站DASH流使用更大缓冲区（2秒），减少I/O抖动
                            chunk_size = 384000 if _is_bili else 96000
                            total_audio = b''
                            last_write_time = 0.0
                            consecutive_empty_reads = 0
                            max_empty_reads = 10

                            try:
                                skip_song = False
                                while True:
                                    if p2 and p2.stdout:
                                        try:
                                            new_audio = await asyncio.wait_for(
                                                p2.stdout.read(chunk_size),
                                                timeout=2.0
                                            )
                                        except asyncio.TimeoutError:
                                            if p2.poll() is not None:
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
                                                    if self.channel_id in guild_status and guild_status[self.channel_id] == Status.PAUSE:
                                                        while self.channel_id in guild_status and guild_status[self.channel_id] == Status.PAUSE:
                                                            await asyncio.sleep(0.1)
                                                    p.stdin.write(audio_slice)
                                                    await p.stdin.drain()
                                                    last_write_time = time.time()

                                                    if self.channel_id in play_list and play_list[self.channel_id]['now_playing']:
                                                        play_list[self.channel_id]['now_playing']['ss'] = last_write_time - first_music_start_time

                                                    if self.channel_id in guild_status:
                                                        state = guild_status[self.channel_id]
                                                        if state == Status.SKIP:
                                                            if log_enabled:
                                                                logger.info(f'跳过当前歌曲: {file}')
                                                            try:
                                                                guild_status[self.channel_id] = Status.END
                                                            except Exception:
                                                                pass
                                                            skip_song = True
                                                            await _safe_kill_subprocess(p2, "ffmpeg-decode-skip")
                                                            break
                                                        if state == Status.STOP:
                                                            if log_enabled:
                                                                logger.info(f'停止播放: {file}')
                                                            if self.channel_id in play_list:
                                                                play_list[self.channel_id]['play_list'] = []
                                                            await _safe_kill_subprocess(p2, "ffmpeg-decode")
                                                            await _safe_kill_subprocess(p, "ffmpeg-encode")
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
                            await _safe_kill_subprocess(p2, "ffmpeg-decode-done")

                            # 保存当前歌曲信息（用于单曲循环）
                            now_info = None
                            if self.channel_id in play_list and play_list[self.channel_id]['now_playing']:
                                now_info = play_list[self.channel_id]['now_playing']
                                play_list[self.channel_id]['now_playing'] = None

                            # 单曲循环：将刚才播放的歌曲重新插入队列头部
                            repeat_on = (self.channel_id in play_list
                                         and play_list[self.channel_id].get('repeat', False))
                            if repeat_on and now_info and isinstance(now_info, dict):
                                replay = now_info.copy()
                                replay['ss'] = 0
                                replay.pop('start', None)
                                if self.channel_id in play_list:
                                    play_list[self.channel_id]['play_list'].insert(0, replay)
                                if log_enabled:
                                    logger.info(f'单曲循环: 重新加入队列，频道: {self.channel_id}')

                            if self.channel_id in play_list and len(play_list[self.channel_id]['play_list']) == 0:
                                await _safe_kill_subprocess(p2, "ffmpeg-decode")
                                await _safe_kill_subprocess(p, "ffmpeg-encode")
                                if self.channel_id in playlist_handle_status:
                                    playlist_handle_status[self.channel_id] = False
                                if log_enabled:
                                    logger.info(f'播放列表结束，频道: {self.channel_id}')
                            else:
                                try:
                                    from utils import refill_playlist_queue
                                    refill_playlist_queue(self.channel_id, play_list)
                                except Exception:
                                    pass
                                try:
                                    from qq_utils import refill_qq_playlist_queue
                                    refill_qq_playlist_queue(self.channel_id, play_list)
                                except Exception:
                                    pass
                                try:
                                    from bili_utils import refill_bili_playlist_queue
                                    refill_bili_playlist_queue(self.channel_id, play_list)
                                except Exception:
                                    pass
                                guild_status[self.channel_id] = Status.END
                                if log_enabled:
                                    logger.info(f'准备播放下一首歌曲，频道: {self.channel_id}')
                    else:
                        break
        except Exception as e:
            if log_enabled:
                logger.error(f'推流过程中出现错误: {str(e)}', exc_info=True)
            try:
                await _safe_kill_subprocess(locals().get('p2'), "ffmpeg-decode-exc")
            except Exception:
                pass
            try:
                await _safe_kill_subprocess(locals().get('p'), "ffmpeg-encode-exc")
            except Exception:
                pass

    async def keepalive(self):
        while True:
            await asyncio.sleep(45)
            if self._rtp_channel_id:
                await self.requestor.keep_alive(self._rtp_channel_id)
            elif self.channel_id:
                await self.requestor.keep_alive(self.channel_id)
            logger.info(f'[保活] 频道={self.channel_id}')

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