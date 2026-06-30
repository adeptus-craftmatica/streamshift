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
    ("OBS Studio", "obs.toggle_source", "Toggle Source Visibility", [
        {"key": "source_name", "type": "text", "label": "Source Name", "required": True, "placeholder": "e.g. Webcam"},
        {"key": "visible",     "type": "bool", "label": "Make Visible", "default": True},
    ]),
    ("OBS Studio", "obs.set_mute", "Set Audio Mute", [
        {"key": "source_name", "type": "text", "label": "Source Name", "required": True},
        {"key": "muted",       "type": "bool", "label": "Muted", "default": False},
    ]),
    ("OBS Studio", "obs.set_volume", "Set Volume", [
        {"key": "source_name", "type": "text",         "label": "Source Name", "required": True},
        {"key": "volume_db",   "type": "number_float", "label": "Volume (dB)", "default": -10.0, "min": -100.0, "max": 0.0},
    ]),
    ("OBS Studio", "obs.start_recording", "Start Recording", []),
    ("OBS Studio", "obs.stop_recording",  "Stop Recording",  []),

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
         "options": ["None", "Card", "Minimal", "Circle", "Orbit", "Surge", "Fullscreen", "Corner", "Split", "Neon"],
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
    ("Chat", "chat.timed_sequence", "Send Chat Messages Over Time", [
        {"key": "use_pool",        "type": "bool",           "label": "Draw from Message Pool", "default": True},
        {"key": "pool_count",      "type": "number",         "label": "How many from pool", "default": 3, "min": 1, "max": 50},
        {"key": "extra_messages",  "type": "multiline_text", "label": "Stream-specific messages (always included, one per line)",
         "placeholder": "Tonight we are painting Mechanicus Skitarii!\nSpecial giveaway happening this stream — stay tuned!"},
        {"key": "duration_seconds","type": "number_float",   "label": "Spread over (seconds)", "default": 600.0, "min": 10.0, "max": 86400.0},
        {"key": "spread",          "type": "choice",          "label": "Timing",
         "options": ["Random", "Even"], "default": "Random"},
        {"key": "wait_for_finish", "type": "bool",            "label": "Wait before next step", "default": True},
    ]),
    ("Chat", "chat.raid", "Raid Channel", [
        {"key": "target", "type": "raid_target_picker", "label": "Channel"},
    ]),
    ("Chat", "chat.announcement", "Chat Announcement", [
        {"key": "message", "type": "text",   "label": "Message", "required": True},
        {"key": "color",   "type": "choice", "label": "Color",
         "options": ["primary", "blue", "green", "orange", "purple"], "default": "primary"},
    ]),
    ("Chat", "chat.shoutout", "Shoutout", [
        {"key": "username", "type": "text", "label": "Username", "required": True, "placeholder": "@username or username"},
    ]),
    ("Chat", "chat.timeout", "Timeout User", [
        {"key": "username",         "type": "text",   "label": "Username", "required": True},
        {"key": "duration_seconds", "type": "number", "label": "Duration (seconds)", "default": 60, "min": 1, "max": 1209600},
        {"key": "reason",           "type": "text",   "label": "Reason", "default": ""},
    ]),

    # ── Social ────────────────────────────────────────────────────────────────
    ("Social", "social.post_template", "Post to Social Media", [
        {"key": "template_id", "type": "text", "label": "Template ID",
         "placeholder": "going_live",
         "description": "The ID of a saved Social Manager template to post."},
        {"key": "platforms", "type": "choice", "label": "Platform",
         "options": ["Bluesky"], "default": "Bluesky"},
    ]),
    ("Social", "social.post_text", "Post Custom Text to Social", [
        {"key": "text", "type": "multiline_text", "label": "Message",
         "placeholder": "Going live now! Come hang out →  {url}"},
        {"key": "platforms", "type": "choice", "label": "Platform",
         "options": ["Bluesky"], "default": "Bluesky"},
    ]),
    ("Social", "social.connect", "Connect Social Media", [
        {"key": "platforms", "type": "choice", "label": "Platform",
         "options": ["Bluesky"], "default": "Bluesky"},
    ]),
    ("Social", "social.disconnect", "Disconnect Social Media", [
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
    ("Flow Control", "flow.condition", "Condition (If / Else)", [
        {"key": "predicate_type",  "type": "choice", "label": "Condition",
         "options": ["stream.is_live", "stream.is_offline", "viewer_count.gte", "viewer_count.lte",
                     "time.between", "variable.equals", "variable.contains", "service.connected", "always"],
         "default": "stream.is_live"},
        {"key": "predicate_value", "type": "text", "label": "Value / Threshold", "default": "",
         "placeholder": "e.g. 50 for viewer count, HH:MM-HH:MM for time, varname=value for variable"},
    ]),
    ("Flow Control", "flow.repeat", "Repeat", [
        {"key": "count", "type": "number", "label": "Repeat count", "default": 3, "min": 1, "max": 100},
    ]),
    ("Flow Control", "flow.wait_until", "Wait Until", [
        {"key": "predicate_type",   "type": "choice", "label": "Condition",
         "options": ["stream.is_live", "stream.is_offline", "viewer_count.gte", "viewer_count.lte",
                     "service.connected", "variable.equals", "always"],
         "default": "stream.is_live"},
        {"key": "predicate_value",  "type": "text",   "label": "Value / Threshold", "default": ""},
        {"key": "timeout_seconds",  "type": "number", "label": "Timeout (s)", "default": 30, "min": 1, "max": 3600},
        {"key": "on_timeout",       "type": "choice", "label": "On timeout", "options": ["skip", "abort"], "default": "skip"},
    ]),
    ("Flow Control", "flow.delay_random", "Random Delay", [
        {"key": "min_ms", "type": "number", "label": "Min (ms)", "default": 1000, "min": 0},
        {"key": "max_ms", "type": "number", "label": "Max (ms)", "default": 5000, "min": 0},
    ]),

    # ── Variables ─────────────────────────────────────────────────────────────
    ("Variables", "variable.set", "Set Variable", [
        {"key": "name",  "type": "text", "label": "Variable name", "required": True, "placeholder": "e.g. greeting"},
        {"key": "value", "type": "text", "label": "Value",         "required": True, "placeholder": "e.g. Hello {viewer_count} viewers!"},
    ]),
    ("Variables", "variable.clear", "Clear Variable", [
        {"key": "name", "type": "text", "label": "Variable name", "required": True},
    ]),

    # ── HTTP / Webhooks ───────────────────────────────────────────────────────
    ("HTTP / Webhooks", "http.request", "HTTP Request", [
        {"key": "method",       "type": "choice",         "label": "Method",
         "options": ["GET", "POST", "PUT", "DELETE"], "default": "POST"},
        {"key": "url",          "type": "text",           "label": "URL", "required": True, "placeholder": "https://..."},
        {"key": "body",         "type": "multiline_text", "label": "Body (JSON)", "default": ""},
        {"key": "headers",      "type": "multiline_text", "label": "Headers (JSON)", "default": ""},
        {"key": "wait",         "type": "bool",           "label": "Wait for response", "default": True},
        {"key": "response_var", "type": "text",           "label": "Store response in variable", "default": ""},
    ]),

    # ── Notifications ─────────────────────────────────────────────────────────
    ("Notifications", "notify.desktop", "Desktop Notification", [
        {"key": "title",   "type": "text", "label": "Title",   "required": True, "placeholder": "StreamShift"},
        {"key": "message", "type": "text", "label": "Message", "required": True},
    ]),
]

STEP_TYPE_BY_ID: dict[str, tuple[str, str, str, list[dict]]] = {
    entry[1]: entry for entry in STEP_TYPES
}
