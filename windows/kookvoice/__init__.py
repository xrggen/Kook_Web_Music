try:
    from .kookvoice import (
        Player, Status, PlayInfo, set_ffmpeg, set_loop, configure_logging,
        play_list, guild_status, playlist_handle_status, state_lock,
        get_state_snapshot, reset_playback_state, finish_playback_recovery,
        wait_for_handlers,
        force_terminate_handler_processes, detach_stuck_handlers, on_event,
        trigger_event, run_async,
    )
except ImportError:
    from kookvoice import (
        Player, Status, PlayInfo, set_ffmpeg, set_loop, configure_logging,
        play_list, guild_status, playlist_handle_status, state_lock,
        get_state_snapshot, reset_playback_state, finish_playback_recovery,
        wait_for_handlers,
        force_terminate_handler_processes, detach_stuck_handlers, on_event,
        trigger_event, run_async,
    )

__all__ = [
    'Player', 'Status', 'PlayInfo', 'set_ffmpeg', 'set_loop',
    'configure_logging', 'play_list', 'guild_status',
    'playlist_handle_status', 'state_lock', 'get_state_snapshot',
    'reset_playback_state', 'finish_playback_recovery', 'wait_for_handlers',
    'force_terminate_handler_processes', 'detach_stuck_handlers', 'on_event',
    'trigger_event', 'run_async',
]
