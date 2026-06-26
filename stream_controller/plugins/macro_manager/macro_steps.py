from __future__ import annotations

STEP_TYPES: list[tuple[str, str, str, list[dict]]] = [
    # ── Services ──────────────────────────────────────────────────────────────
    ("Services", "services.connect", "Connect Services", [
        {"key": "services", "type": "service_multi", "label": "Services",
         "options": ["OBS Studio", "Scene Manager", "Bots", "Chat", "Stream Stats", "Stream Info", "PNGtuber"],
         "service_ids": ["obs_studio", "scene_manager", "bot_manager", "chat_manager", "stream_stats", "stream_info", "pngtuber"],
         "default": ["obs_studio", "bot_manager", "chat_manager"]},
    ]),
    ("Services", "services.disconnect", "Disconnect Services", [
        {"key": "services", "type": "service_multi", "label": "Services",
         "options": ["OBS Studio", "Scene Manager", "Bots", "Chat", "Stream Stats", "Stream Info", "PNGtuber"],
         "service_ids": ["obs_studio", "scene_manager", "bot_manager", "chat_manager", "stream_stats", "stream_info", "pngtuber"],
         "default": []},
    ]),

    # ── Stream Info ────────────────────────────────────────────────────────────
    ("Stream Info", "stream_info.update", "Update Stream Info", [
        {"key": "title",    "type": "text",   "label": "Stream Title", "placeholder": "Tonight on stream…"},
        {"key": "category", "type": "text",   "label": "Category / Game", "placeholder": "Just Chatting"},
    ]),

    # ── OBS Studio ────────────────────────────────────────────────────────────
    ("OBS Studio", "obs.start_stream",  "Go Live",   []),
    ("OBS Studio", "obs.stop_stream",   "End Stream", []),
    ("OBS Studio", "obs.switch_scene",  "Switch Scene",  [
        {"key": "scene_name", "type": "scene_picker", "label": "Scene"},
    ]),

    # ── Music ──────────────────────────────────────────────────────────────────
    ("Music", "music.choose", "Choose Tracks", [
        {"key": "track_paths",  "type": "library_multi_picker",    "label": "Tracks"},
        {"key": "shuffle",      "type": "bool",                    "label": "Shuffle"},
        {"key": "repeat",       "type": "bool",                    "label": "Repeat"},
        {"key": "overlay_style","type": "choice",                  "label": "Overlay Style",
         "options": ["None", "Card", "Minimal", "Ticker", "Circle", "Equalizer", "Vinyl", "Corner", "Banner"],
         "default": "None"},
    ]),
    ("Music", "music.play_chosen", "Play Chosen Tracks", []),
    ("Music", "music.play_playlist", "Play Playlist", [
        {"key": "playlist_id",  "type": "library_playlist_picker", "label": "Playlist"},
        {"key": "shuffle",      "type": "bool",                    "label": "Shuffle"},
        {"key": "overlay_style","type": "choice",                  "label": "Overlay Style",
         "options": ["None", "Card", "Minimal", "Ticker", "Circle", "Equalizer", "Vinyl", "Corner", "Banner"],
         "default": "None"},
    ]),
    ("Music", "music.stop", "Stop Music", []),

    # ── Timer ──────────────────────────────────────────────────────────────────
    ("Timer", "timer.create", "Create Timer", [
        {"key": "target_timer_id",   "type": "timer_picker", "label": "Target Timer",   "optional": True, "placeholder": "Create new…"},
        {"key": "label",             "type": "text",         "label": "Timer Name",     "placeholder": "Countdown"},
        {"key": "mode",              "type": "choice",       "label": "Mode",           "options": ["Countdown", "Count Up"], "default": "Countdown"},
        {"key": "duration_source",   "type": "choice",       "label": "Duration From",  "options": ["Manual", "Music Tracks"], "default": "Manual"},
        {"key": "duration_seconds",  "type": "number_float", "label": "Duration (sec)", "default": 300.0, "min": 1.0, "max": 86400.0},
        {"key": "overlay_style",     "type": "choice",       "label": "Overlay Style",
         "options": ["None", "Card", "Minimal", "Circle", "Fullscreen", "Corner", "Split", "Neon"],
         "default": "None"},
        {"key": "wait_for_finish",   "type": "bool",         "label": "Wait for completion", "default": False},
    ]),
    ("Timer", "timer.start", "Start Timer", [
        {"key": "timer_id", "type": "timer_picker", "label": "Timer"},
    ]),
    ("Timer", "timer.stop",  "Stop Timer",  [
        {"key": "timer_id", "type": "timer_picker", "label": "Timer"},
    ]),
    ("Timer", "timer.reset", "Reset Timer", [
        {"key": "timer_id", "type": "timer_picker", "label": "Timer"},
    ]),

    # ── Chat ──────────────────────────────────────────────────────────────────
    ("Chat", "chat.send", "Send Chat Message", [
        {"key": "message", "type": "multiline_text", "label": "Message"},
    ]),
    ("Chat", "chat.raid", "Raid Channel", [
        {"key": "target", "type": "raid_target_picker", "label": "Channel"},
    ]),

    # ── Social ────────────────────────────────────────────────────────────────
    ("Social", "social.post_template", "Post to Social Media", [
        {"key": "template_id", "type": "text", "label": "Template ID",
         "placeholder": "going_live",
         "description": "The ID of a saved Social Manager template to post."},
        {"key": "platforms", "type": "choice", "label": "Platform",
         "options": ["Bluesky"], "default": "Bluesky"},
    ]),

    # ── Flow Control ──────────────────────────────────────────────────────────
    ("Flow Control", "delay",  "Wait", [
        {"key": "delay_ms", "type": "number", "label": "Duration (ms)", "default": 500, "min": 0, "max": 60000},
    ]),
    ("Flow Control", "action", "Run Action", [
        {"key": "action_id", "type": "action_picker", "label": "Action"},
    ]),
]

STEP_TYPE_BY_ID: dict[str, tuple[str, str, str, list[dict]]] = {
    entry[1]: entry for entry in STEP_TYPES
}
