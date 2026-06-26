from __future__ import annotations

from typing import Callable

from stream_controller.core.twitch_auth import TwitchAuthFlow as _Base

_SCOPES = "chat:read+chat:edit+moderator:manage:banned_users+channel:moderate+moderator:read:chatters"


class TwitchAuthFlow:
    def __init__(
        self,
        client_id: str,
        on_complete: Callable[[str, str], None],
        on_error: Callable[[str], None],
    ) -> None:
        self._flow = _Base(
            client_id=client_id,
            scopes=_SCOPES,
            on_complete=on_complete,
            on_error=on_error,
            save_path="/twitch-auth-save",
        )

    def start(self) -> None:
        self._flow.start()
