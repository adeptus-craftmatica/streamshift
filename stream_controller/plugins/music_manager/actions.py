from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stream_controller.plugins.music_manager.music_state import MusicState


def make_action_handlers(music_state: "MusicState") -> dict[str, callable]:
    """Return a mapping of action_id -> callable for registration with AppContext."""
    return {
        "music.play_pause": music_state.play_pause,
        "music.play": music_state.play,
        "music.pause": music_state.pause,
        "music.stop": music_state.stop,
        "music.next_track": music_state.next_track,
        "music.previous_track": music_state.previous_track,
        "music.toggle_shuffle": music_state.toggle_shuffle,
        "music.cycle_loop_mode": music_state.cycle_loop_mode,
        "music.volume_up": music_state.volume_up,
        "music.volume_down": music_state.volume_down,
        "music.toggle_mute": music_state.toggle_mute,
        "music.play_random": music_state.play_random,
    }


ACTION_DEFINITIONS = [
    {
        "action_id": "music.player_card",
        "title": "Music Player Card",
        "description": "Full music transport tile — play/pause, seek, shuffle, loop, volume, playlist, and output device in one card.",
        "icon": "♪",
        "page": "Music",
        "group": "Music Manager",
    },
    {
        "action_id": "music.open_control_panel",
        "title": "Open Music Player",
        "description": "Open the Music Manager plugin workspace.",
        "icon": "MM",
        "page": "Music",
        "group": "Music Manager",
        "default_shortcut": "Ctrl+Alt+M",
    },
    {
        "action_id": "music.play_pause",
        "title": "Play / Pause",
        "description": "Toggle playback of the current track.",
        "icon": "PP",
        "page": "Music",
        "group": "Playback",
        "default_shortcut": "Ctrl+Alt+Space",
    },
    {
        "action_id": "music.play",
        "title": "Play",
        "description": "Resume or start music playback.",
        "icon": "PL",
        "page": "Music",
        "group": "Playback",
    },
    {
        "action_id": "music.pause",
        "title": "Pause",
        "description": "Pause the current track.",
        "icon": "PA",
        "page": "Music",
        "group": "Playback",
    },
    {
        "action_id": "music.stop",
        "title": "Stop",
        "description": "Stop playback and clear the current position.",
        "icon": "ST",
        "page": "Music",
        "group": "Playback",
    },
    {
        "action_id": "music.next_track",
        "title": "Next Track",
        "description": "Skip to the next track in the queue.",
        "icon": "NX",
        "page": "Music",
        "group": "Playback",
        "default_shortcut": "Ctrl+Alt+Right",
    },
    {
        "action_id": "music.previous_track",
        "title": "Previous Track",
        "description": "Go back to the previous track in the queue.",
        "icon": "PV",
        "page": "Music",
        "group": "Playback",
        "default_shortcut": "Ctrl+Alt+Left",
    },
    {
        "action_id": "music.toggle_shuffle",
        "title": "Shuffle Toggle",
        "description": "Enable or disable shuffle mode.",
        "icon": "SH",
        "page": "Music",
        "group": "Queue",
    },
    {
        "action_id": "music.cycle_loop_mode",
        "title": "Loop Mode Cycle",
        "description": "Cycle through loop modes: off, track, playlist, once, random.",
        "icon": "LP",
        "page": "Music",
        "group": "Queue",
    },
    {
        "action_id": "music.volume_up",
        "title": "Volume Up",
        "description": "Increase music volume by 10%.",
        "icon": "V+",
        "page": "Music",
        "group": "Volume",
        "default_shortcut": "Ctrl+Alt+Up",
    },
    {
        "action_id": "music.volume_down",
        "title": "Volume Down",
        "description": "Decrease music volume by 10%.",
        "icon": "V-",
        "page": "Music",
        "group": "Volume",
        "default_shortcut": "Ctrl+Alt+Down",
    },
    {
        "action_id": "music.toggle_mute",
        "title": "Mute Toggle",
        "description": "Mute or unmute music output.",
        "icon": "MU",
        "page": "Music",
        "group": "Volume",
    },
    {
        "action_id": "music.play_random",
        "title": "Play Random Song",
        "description": "Pick a random track from the library and play it immediately.",
        "icon": "🎲",
        "page": "Music",
        "group": "Playback",
    },
]
