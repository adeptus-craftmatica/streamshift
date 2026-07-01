"""
Centralised port constants for all StreamShift overlay and OAuth servers.

Changing a port here changes it everywhere — overlay_server.py bindings,
UI fallback URLs, and scene designer presets all read from this file.

All ports are unique — no conflicts.
"""

# ── Overlay servers (persistent, started on plugin load) ─────────────────────
MUSIC_OVERLAY_PORT    = 47891
CHAT_OVERLAY_PORT     = 47892
TIMER_OVERLAY_PORT    = 47894
SCENE_OVERLAY_PORT    = 47895
STREAM_STATS_PORT     = 47900
PNGTUBER_PORT         = 47897
ALERT_OVERLAY_PORT    = 47898

# ── OAuth callback servers (ephemeral, started only during auth flow) ─────────
CHAT_OAUTH_PORT       = 47893
BOT_OAUTH_PORT        = 47896
POLL_OAUTH_PORT       = 47901
