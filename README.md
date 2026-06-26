# StreamShift

Premium PySide6 stream control surface with a plugin-based architecture.

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```

## Plugins

### Music Manager

Local audio playback, playlist management, and browser-source Now Playing overlays.

#### Setup

1. Open **Music Manager** from the sidebar.
2. Click **+ Add Folder** to add a folder of music files.
3. Tracks are indexed automatically. Double-click any track to play it.

#### Supported Formats

`.mp3`, `.wav`, `.flac`, `.ogg`, `.m4a`

#### Playlists

- Click **+ New Playlist** to create a playlist.
- Select a track in the library and click **Add to Playlist**.
- Double-click a playlist track to start playback from that position.
- Reorder tracks with the ▲ ▼ buttons.

#### Control Deck Actions

The following actions can be placed on any Control Deck page:

| Action | ID |
|---|---|
| Open Music Player | `music.open_control_panel` |
| Play / Pause | `music.play_pause` |
| Play | `music.play` |
| Pause | `music.pause` |
| Stop | `music.stop` |
| Next Track | `music.next_track` |
| Previous Track | `music.previous_track` |
| Shuffle Toggle | `music.toggle_shuffle` |
| Loop Mode Cycle | `music.cycle_loop_mode` |
| Volume Up | `music.volume_up` |
| Volume Down | `music.volume_down` |
| Mute Toggle | `music.toggle_mute` |

#### Browser Source Overlays

Start the app and add these URLs in OBS/Streamlabs as **Browser Sources**:

| Overlay | URL |
|---|---|
| Now Playing — Card | `http://localhost:47891/card` |
| Now Playing — Minimal | `http://localhost:47891/minimal` |
| Now Playing — Ticker | `http://localhost:47891/ticker` |
| State API (JSON) | `http://localhost:47891/api/state` |

Overlays update automatically as tracks change. Set **Width** to 380 and **Height** to 110 for the card overlay.

#### Output Device Selection

Output device routing is **not yet supported** by the pygame audio backend. The architecture supports adding per-device routing by swapping in a `sounddevice`-based backend. This will be a future enhancement.

#### Known Limitations

- pygame.mixer does not support audio output device selection. Use your OS audio settings to route output.
- Seeking accuracy depends on the codec and pygame version.
- Overlay server runs on port **47891** by default. Ensure that port is available.

#### Future Ideas

- Twitch Channel Points integration for viewer track requests
- Crossfade between tracks
- Last.fm scrobbling
- Lyrics display overlay
- Album art extraction and display in overlays

### OBS Studio

Real OBS Studio integration. Requires OBS WebSocket enabled on port 4455.

## Architecture

StreamShift uses a plugin system where each plugin:
- Has a `manifest.json` declaring name, version, and entry point
- Receives an `AppContext` on load for registering actions, settings, UI pages, and commands
- Is fully isolated — unloading a plugin removes all its actions, settings, and UI

Plugins live in `stream_controller/plugins/<plugin_id>/`.
