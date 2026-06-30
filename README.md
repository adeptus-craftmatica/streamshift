# StreamShift

A premium PySide6 stream control surface with a plugin-based architecture. Control OBS, manage chat bots, play music, switch scenes, run macros, and more — all from one interface.

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```

## Features

### OBS Studio Integration
Connects automatically to OBS via WebSocket — no manual IP or password entry required. StreamShift reads OBS's own config file on launch so it always connects, even when your network changes.

- Live scene switching
- Audio input mute toggles
- Overlay source visibility control
- Stream and recording output status
- Scene Manager stage panel with preview thumbnails

### Stage View
A freeform drag-and-drop canvas for arranging plugin panels however you want. Place it on a second monitor for a dedicated stream control surface.

- Freely position and resize panels
- Save and load named layouts
- Fullscreen mode for secondary displays
- Quick Connect panel to connect all services at once

### Bot Manager
Multi-bot Twitch and Discord bot support with command routing, chat relay, and macro triggers.

### Raid Control
Stage View panel showing your raid target list with live Twitch status indicators. One-click raid with confirmation dialog.

### Chat Manager
Live chat display with Twitch connection.

### Macro Manager
Build multi-step automation workflows triggered by hotkeys, commands, or deck buttons.

### Music Manager
Local audio playback with playlist management and browser-source overlays for OBS.

**Supported formats:** `.mp3`, `.wav`, `.flac`, `.ogg`, `.m4a`

**Browser Source overlays:**

| Overlay | URL |
|---|---|
| Now Playing — Card | `http://localhost:47891/card` |
| Now Playing — Minimal | `http://localhost:47891/minimal` |
| Now Playing — Ticker | `http://localhost:47891/ticker` |

### Stream Info
Update Twitch title, category, tags, and language. Go Live / End Stream controls.

### Scene Manager
Visual OBS scene switcher with browser-source overlay showing the current scene name.

### Social Manager
Bluesky integration for posting stream announcements.

### Timer Manager
Countdown and stopwatch overlays for OBS browser sources.

## Settings

The Settings page uses a sidebar layout — select a section or plugin from the left to view and edit its settings. Changes are saved per-plugin with individual Save and Reset buttons.

## Architecture

StreamShift uses a plugin system where each plugin:
- Has a `manifest.json` declaring name, version, and entry point
- Receives an `AppContext` on load for registering actions, settings, UI pages, stage panels, and commands
- Is fully isolated — unloading a plugin removes all its actions, settings, and UI

Plugins live in `stream_controller/plugins/<plugin_id>/`.

## Requirements

- Python 3.11+
- OBS Studio with WebSocket server enabled (Tools → WebSocket Server Settings)
- macOS, Windows, or Linux
