from __future__ import annotations

import logging
from pathlib import Path

from stream_controller.core.app_context import AppContext

logger = logging.getLogger(__name__)

_DATA_DIR = Path.home() / ".streamshift" / "social_manager"


class SocialManagerPlugin:
    """Post to social platforms (Bluesky) directly from StreamShift."""

    def __init__(self) -> None:
        self._app_context: AppContext | None = None
        self._repo = None
        self._client = None
        self._page_widget = None
        self._tile_widget = None

    def register(self, app_context: AppContext) -> None:
        from stream_controller.plugins.social_manager.social_repository import SocialRepository
        from stream_controller.plugins.social_manager.bluesky_client import BlueSkyClient

        self._app_context = app_context
        _DATA_DIR.mkdir(parents=True, exist_ok=True)

        self._repo = SocialRepository(_DATA_DIR / "settings.json")
        self._client = BlueSkyClient()

        # Auto-connect if credentials are saved
        self._try_auto_connect()

        self._register_page(app_context)
        self._register_actions(app_context)

        app_context.set_status("Social Manager loaded.", timeout_ms=3000)
        logger.info("Social Manager plugin registered")

    def unregister(self, app_context: AppContext) -> None:
        if self._client:
            self._client.disconnect()
        self._app_context = None

    # ── Public API (used by UI and macro steps) ───────────────────────────────

    def resolve_template(self, text: str) -> str:
        """Replace {placeholders} in template text with live values."""
        handles = self._repo.get("social_handles") or {}
        bsky_handle = self._repo.get("bluesky_handle") or ""
        bsky_url = f"https://bsky.app/profile/{bsky_handle}" if bsky_handle else ""

        stream_title = ""
        stream_category = ""
        stream_url = ""
        try:
            # Pull stream info if the stream_info plugin is available
            from stream_controller.plugins.stream_info.info_repository import InfoRepository
            info_path = Path.home() / ".streamshift" / "stream_info" / "settings.json"
            if info_path.exists():
                ir = InfoRepository(info_path)
                stream_title = ir.get("title") or ""
                stream_category = ir.get("category") or ""
                username = ir.get("username") or ""
                if username:
                    stream_url = f"https://twitch.tv/{username}"
        except Exception:
            pass

        replacements = {
            "{title}": stream_title,
            "{category}": stream_category,
            "{url}": stream_url,
            "{bluesky_handle}": bsky_handle,
            "{bluesky_url}": bsky_url,
            "{instagram_handle}": handles.get("instagram", ""),
            "{twitter_handle}": handles.get("twitter", ""),
        }
        result = text
        for key, val in replacements.items():
            result = result.replace(key, val)
        return result

    def post_template(self, template_id: str) -> tuple[bool, str]:
        """Post a saved template by ID. Returns (success, message)."""
        tmpl = self._repo.get_template(template_id)
        if not tmpl:
            return False, f"Template '{template_id}' not found."
        if not self._client or not self._client.connected:
            return False, "Not connected to Bluesky."
        text = self.resolve_template(tmpl.get("text", ""))
        image = tmpl.get("image_path", "")
        try:
            if image and Path(image).exists():
                self._client.post_with_image(text, image)
            else:
                self._client.post_text(text)
            return True, "Posted successfully."
        except Exception as exc:
            return False, str(exc)

    def sync_bot_commands(self) -> None:
        """Push social bot commands to the Bot Manager plugin if available."""
        try:
            self._do_sync_bot_commands()
        except Exception as exc:
            logger.warning("Could not sync bot commands: %s", exc)

    def _do_sync_bot_commands(self) -> None:
        commands = self._repo.list_bot_commands()
        handles = self._repo.get("social_handles") or {}
        bsky_handle = self._repo.get("bluesky_handle") or ""
        bsky_url = f"https://bsky.app/profile/{bsky_handle}" if bsky_handle else bsky_handle

        # Find the active bot manager bot and inject commands
        from stream_controller.plugins.bot_manager.plugin import BotManagerPlugin
        if not self._app_context:
            return
        pm = getattr(self._app_context, "_plugin_manager", None)
        if not pm:
            return
        for loaded in pm._loaded_plugins.values():
            inst = loaded.instance
            if isinstance(inst, BotManagerPlugin):
                for cmd_def in commands:
                    cmd = cmd_def.get("command", "").lstrip("!")
                    resp = cmd_def.get("response", "")
                    resp = resp.replace("{bluesky_url}", bsky_url)
                    resp = resp.replace("{bluesky_handle}", bsky_handle)
                    resp = resp.replace("{instagram_handle}", handles.get("instagram", ""))
                    resp = resp.replace("{twitter_handle}", handles.get("twitter", ""))
                    if cmd and resp:
                        try:
                            inst.add_chat_command(f"!{cmd}", resp)
                        except Exception:
                            pass
                break

    # ── Private helpers ───────────────────────────────────────────────────────

    def _try_auto_connect(self) -> None:
        if not self._repo.get("bluesky_enabled"):
            return
        handle = self._repo.get("bluesky_handle") or ""
        pw = self._repo.get_secret("bluesky_app_password")
        if not handle or not pw:
            return
        import threading
        def _worker():
            try:
                self._client.connect(handle, pw)
                logger.info("Social Manager: auto-connected to Bluesky as @%s", self._client.handle)
            except Exception as exc:
                logger.warning("Social Manager: auto-connect failed: %s", exc)
        threading.Thread(target=_worker, daemon=True).start()

    def _register_page(self, app_context: AppContext) -> None:
        from stream_controller.plugins.social_manager.ui.social_page import SocialPage
        from stream_controller.plugins.social_manager.ui.social_tile import SocialTile

        self._page_widget = SocialPage(self, self._repo, self._client)
        self._tile_widget = SocialTile(self, self._repo, self._client)

        app_context.register_plugin_page(
            page_id="social_manager",
            title="Social Manager",
            subtitle="Post to Bluesky and manage social handles — all without leaving StreamShift.",
            widget=self._page_widget,
            help_text=(
                "<h3>Social Manager</h3>"
                "<p>Social Manager lets you post to Bluesky directly from StreamShift — "
                "including going-live announcements, mid-stream updates, and more.</p>"
                "<h4>Setup</h4>"
                "<ol>"
                "<li>Go to <b>Accounts</b> and enter your Bluesky handle (e.g. yourname.bsky.social).</li>"
                "<li>Generate an <b>App Password</b> at bsky.app → Settings → Privacy and Security → App Passwords. "
                "Never use your real account password.</li>"
                "<li>Click <b>Save &amp; Connect</b>. The status turns green when connected.</li>"
                "</ol>"
                "<h4>Posting</h4>"
                "<p>Use the <b>Compose</b> tab to write and post directly. "
                "Load a saved template first to fill in your going-live message automatically.</p>"
                "<h4>Templates</h4>"
                "<p>Create reusable post templates with placeholders like <b>{title}</b>, <b>{url}</b>, "
                "and <b>{instagram_handle}</b> that get filled in at post time. "
                "Add a <b>Social Post</b> macro step to fire templates automatically when you go live.</p>"
                "<h4>Chat bot commands</h4>"
                "<p>Set up your social handles and bot commands under <b>Handles &amp; Bot</b>. "
                "When viewers type !bluesky or !instagram in chat, the bot responds with your link automatically.</p>"
                "<h4>Stage View card</h4>"
                "<p>The Social quick-post card in the Stage View lets you fire a template with one tap "
                "without switching pages — great for mid-stream updates.</p>"
            ),
        )

        app_context.register_stage_widget(
            panel_id="social.main",
            title="Social",
            icon="📣",
            factory=lambda: SocialTile(self, self._repo, self._client),
        )

    def _register_actions(self, app_context: AppContext) -> None:
        app_context.register_action(
            action_id="social.post_going_live",
            title="Post: Going Live",
            description="Post the Going Live template to all connected social platforms.",
            execute=lambda: self.post_template("going_live"),
            icon="📣",
            page="Social",
            group="Social Manager",
        )
        app_context.register_action(
            action_id="social.open_panel",
            title="Open Social Manager",
            description="Navigate to the Social Manager page.",
            execute=lambda: app_context.show_page("social_manager"),
            icon="🌐",
            page="Social",
            group="Social Manager",
        )
