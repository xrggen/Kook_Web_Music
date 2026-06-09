try:
    from .kookvoice import Player, Status, PlayInfo, set_ffmpeg, configure_logging, play_list, guild_status, on_event, trigger_event, run_async
except ImportError:
    from kookvoice import Player, Status, PlayInfo, set_ffmpeg, configure_logging, play_list, guild_status, on_event, trigger_event, run_async

__all__ = ['Player', 'Status', 'PlayInfo', 'set_ffmpeg', 'configure_logging', 'play_list', 'guild_status', 'on_event', 'trigger_event', 'run_async']