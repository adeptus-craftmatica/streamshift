from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ObsServiceError(RuntimeError):
    """Raised when the OBS service cannot complete a request."""


@dataclass(frozen=True, slots=True)
class ObsConnectionConfig:
    host: str
    port: int
    password: str
    timeout_seconds: int


@dataclass(slots=True)
class ObsSceneInfo:
    name: str
    uuid: str = ""
    is_group: bool = False


@dataclass(slots=True)
class ObsAudioInputInfo:
    name: str
    muted: bool
    kind: str = ""


@dataclass(slots=True)
class ObsOverlaySourceInfo:
    scene_name: str
    source_name: str
    scene_item_id: int | None
    enabled: bool
    available: bool = True


@dataclass(slots=True)
class ObsSnapshot:
    obs_version: str = ""
    websocket_version: str = ""
    rpc_version: int | None = None
    current_scene_name: str = ""
    scenes: list[ObsSceneInfo] = field(default_factory=list)
    audio_inputs: list[ObsAudioInputInfo] = field(default_factory=list)
    overlay_sources: list[ObsOverlaySourceInfo] = field(default_factory=list)
    stream_active: bool = False
    stream_reconnecting: bool = False
    stream_timecode: str = ""
    record_active: bool = False
    record_paused: bool = False
    record_timecode: str = ""


class ObsStudioService:
    """Small wrapper around obsws-python to keep plugin logic tidy."""

    def __init__(self) -> None:
        self._client: Any | None = None
        self._config: ObsConnectionConfig | None = None

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    @property
    def config(self) -> ObsConnectionConfig | None:
        return self._config

    def connect(self, config: ObsConnectionConfig) -> dict[str, Any]:
        if self.is_connected:
            self.disconnect()

        client_cls = self._load_client_class()
        try:
            client = client_cls(
                host=config.host,
                port=config.port,
                password=config.password,
                timeout=config.timeout_seconds,
            )
            version_info = self._response_dict(client.get_version())
        except Exception as exc:  # pragma: no cover - exercised through integration flow
            raise ObsServiceError(self._format_error(exc)) from exc

        self._client = client
        self._config = config
        return version_info

    def disconnect(self) -> None:
        if self._client is None:
            return

        try:
            self._client.disconnect()
        except Exception:
            pass
        finally:
            self._client = None
            self._config = None

    def fetch_snapshot(
        self,
        *,
        additional_audio_inputs: list[str],
        overlay_scene_name: str | None,
        overlay_sources: list[str],
    ) -> ObsSnapshot:
        client = self._require_client()
        try:
            version_info = self._response_dict(client.get_version())
            scene_list = self._response_dict(client.get_scene_list())
            current_scene_info = self._response_dict(client.get_current_program_scene())
            stream_status = self._response_dict(client.get_stream_status())
            record_status = self._response_dict(client.get_record_status())
            scenes = self._build_scenes(scene_list)
            current_scene_name = str(
                current_scene_info.get("scene_name")
                or scene_list.get("current_program_scene_name")
                or ""
            )
            overlay_scene = overlay_scene_name or current_scene_name
            return ObsSnapshot(
                obs_version=str(version_info.get("obs_version", "")),
                websocket_version=str(version_info.get("obs_web_socket_version", "")),
                rpc_version=self._to_int(version_info.get("rpc_version")),
                current_scene_name=current_scene_name,
                scenes=scenes,
                audio_inputs=self._collect_audio_inputs(client, additional_audio_inputs),
                overlay_sources=self._collect_overlay_sources(client, overlay_scene, overlay_sources),
                stream_active=bool(stream_status.get("output_active", False)),
                stream_reconnecting=bool(stream_status.get("output_reconnecting", False)),
                stream_timecode=str(stream_status.get("output_timecode", "")),
                record_active=bool(record_status.get("output_active", False)),
                record_paused=bool(record_status.get("output_paused", False)),
                record_timecode=str(record_status.get("output_timecode", "")),
            )
        except Exception as exc:  # pragma: no cover - exercised through integration flow
            raise ObsServiceError(self._format_error(exc)) from exc

    def set_current_program_scene(self, scene_name: str) -> None:
        client = self._require_client()
        try:
            client.set_current_program_scene(scene_name)
        except Exception as exc:  # pragma: no cover - exercised through integration flow
            raise ObsServiceError(self._format_error(exc)) from exc

    def toggle_input_mute(self, input_name: str) -> bool:
        client = self._require_client()
        try:
            response = self._response_dict(client.toggle_input_mute(input_name))
            return bool(response.get("input_muted", False))
        except Exception as exc:  # pragma: no cover - exercised through integration flow
            raise ObsServiceError(self._format_error(exc)) from exc

    def toggle_scene_item_enabled(self, scene_name: str, item_id: int) -> bool:
        client = self._require_client()
        try:
            state = self._response_dict(client.get_scene_item_enabled(scene_name, item_id))
            next_state = not bool(state.get("scene_item_enabled", False))
            client.set_scene_item_enabled(scene_name, item_id, next_state)
            return next_state
        except Exception as exc:  # pragma: no cover - exercised through integration flow
            raise ObsServiceError(self._format_error(exc)) from exc

    def start_stream(self) -> None:
        client = self._require_client()
        try:
            client.start_stream()
        except Exception as exc:
            raise ObsServiceError(self._format_error(exc)) from exc

    def stop_stream(self) -> None:
        client = self._require_client()
        try:
            client.stop_stream()
        except Exception as exc:
            raise ObsServiceError(self._format_error(exc)) from exc

    def toggle_stream(self) -> bool:
        client = self._require_client()
        try:
            response = self._response_dict(client.toggle_stream())
            return bool(response.get("output_active", False))
        except Exception as exc:  # pragma: no cover - exercised through integration flow
            raise ObsServiceError(self._format_error(exc)) from exc

    def toggle_record(self) -> bool:
        client = self._require_client()
        try:
            response = self._response_dict(client.toggle_record())
            return bool(response.get("output_active", False))
        except Exception as exc:  # pragma: no cover - exercised through integration flow
            raise ObsServiceError(self._format_error(exc)) from exc

    def _collect_audio_inputs(self, client: Any, additional_audio_inputs: list[str]) -> list[ObsAudioInputInfo]:
        special_inputs = self._response_dict(client.get_special_inputs())
        input_list = self._response_dict(client.get_input_list())
        input_defs = input_list.get("inputs", []) if isinstance(input_list.get("inputs"), list) else []
        input_kinds = {
            str(item.get("inputName", "")): str(item.get("inputKind", ""))
            for item in input_defs
            if isinstance(item, dict)
        }

        ordered_names: list[str] = []
        for key in ("desktop1", "desktop2", "mic1", "mic2", "mic3", "mic4"):
            name = str(special_inputs.get(key, "")).strip()
            if name and name not in ordered_names:
                ordered_names.append(name)

        for name in additional_audio_inputs:
            if name and name not in ordered_names:
                ordered_names.append(name)

        results: list[ObsAudioInputInfo] = []
        for name in ordered_names:
            try:
                state = self._response_dict(client.get_input_mute(name))
            except Exception:
                continue
            results.append(
                ObsAudioInputInfo(
                    name=name,
                    muted=bool(state.get("input_muted", False)),
                    kind=input_kinds.get(name, ""),
                )
            )

        return results

    def _collect_overlay_sources(
        self,
        client: Any,
        scene_name: str,
        source_names: list[str],
    ) -> list[ObsOverlaySourceInfo]:
        if not scene_name or not source_names:
            return []

        overlays: list[ObsOverlaySourceInfo] = []
        for source_name in source_names:
            try:
                item_response = self._response_dict(client.get_scene_item_id(scene_name, source_name))
                item_id = self._to_int(item_response.get("scene_item_id"))
                if item_id is None:
                    raise ObsServiceError(f"Could not resolve scene item '{source_name}'.")
                state_response = self._response_dict(client.get_scene_item_enabled(scene_name, item_id))
                overlays.append(
                    ObsOverlaySourceInfo(
                        scene_name=scene_name,
                        source_name=source_name,
                        scene_item_id=item_id,
                        enabled=bool(state_response.get("scene_item_enabled", False)),
                        available=True,
                    )
                )
            except Exception:
                overlays.append(
                    ObsOverlaySourceInfo(
                        scene_name=scene_name,
                        source_name=source_name,
                        scene_item_id=None,
                        enabled=False,
                        available=False,
                    )
                )
        return overlays

    @staticmethod
    def _build_scenes(scene_list: dict[str, Any]) -> list[ObsSceneInfo]:
        scene_defs = scene_list.get("scenes", []) if isinstance(scene_list.get("scenes"), list) else []
        scenes: list[ObsSceneInfo] = []
        for item in scene_defs:
            if not isinstance(item, dict):
                continue
            scenes.append(
                ObsSceneInfo(
                    name=str(item.get("sceneName", "")),
                    uuid=str(item.get("sceneUuid", "")),
                    is_group=bool(item.get("isGroup", False)),
                )
            )
        return scenes

    def _require_client(self) -> Any:
        if self._client is None:
            raise ObsServiceError("OBS Studio is not connected.")
        return self._client

    @staticmethod
    def _response_dict(response: Any) -> dict[str, Any]:
        attrs = getattr(response, "attrs", None)
        if callable(attrs):
            return {attr: getattr(response, attr) for attr in attrs()}
        if isinstance(response, dict):
            return dict(response)
        return {}

    @staticmethod
    def _load_client_class() -> Any:
        try:
            from obsws_python import ReqClient
        except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
            raise ObsServiceError(
                "obsws-python is not installed. Install the project requirements and relaunch the app."
            ) from exc
        return ReqClient

    @staticmethod
    def _to_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_error(exc: Exception) -> str:
        message = str(exc).strip()
        return message or exc.__class__.__name__
