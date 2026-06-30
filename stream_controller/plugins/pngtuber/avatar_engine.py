from __future__ import annotations

import logging
import random
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

IDLE = "idle"
TALKING = "talking"
IDLE_BLINK = "idle_blink"
TALKING_BLINK = "talking_blink"

_SAMPLE_RATE = 48000
_CHUNK = 512


class AvatarEngine:
    def __init__(
        self,
        on_state_change: Callable[[str], None],
        on_level_change: Callable[[float], None],
    ) -> None:
        self._on_state_change = on_state_change
        self._on_level_change = on_level_change

        self.mic_device_index: int | None = None
        self.mic_threshold: float = 0.02
        self.talk_hold_frames: int = 8
        self.blink_enabled: bool = True
        self.blink_interval_avg: float = 4.0

        self._state = IDLE
        self._running = False
        self._mic_thread: threading.Thread | None = None
        self._blink_thread: threading.Thread | None = None
        self._blinking = False
        self._blink_lock = threading.Lock()

        self._talk_counter = 0
        self._silence_counter = 0

    @property
    def state(self) -> str:
        return self._state

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._state = IDLE
        self._mic_thread = threading.Thread(target=self._mic_loop, daemon=True, name="pngtuber-mic")
        self._mic_thread.start()
        if self.blink_enabled:
            self._blink_thread = threading.Thread(target=self._blink_loop, daemon=True, name="pngtuber-blink")
            self._blink_thread.start()

    def stop(self) -> None:
        self._running = False
        self._mic_thread = None
        self._blink_thread = None

    def _mic_loop(self) -> None:
        try:
            import sounddevice as sd
        except ImportError:
            logger.error("sounddevice not available")
            return

        def callback(indata, frames, time_info, status):
            if not self._running:
                return
            samples = indata[:, 0]
            rms = (sum(float(x) * float(x) for x in samples) / len(samples)) ** 0.5
            level = min(rms / 0.5, 1.0)
            self._on_level_change(float(level))

            is_loud = rms > self.mic_threshold
            if is_loud:
                self._talk_counter += 1
                self._silence_counter = 0
            else:
                self._silence_counter += 1
                self._talk_counter = 0

            was_talking = self._state in (TALKING, TALKING_BLINK)

            if not was_talking and self._talk_counter >= 2:
                self._set_base_talking(True)
            elif was_talking and self._silence_counter >= self.talk_hold_frames:
                self._set_base_talking(False)

        try:
            with sd.InputStream(
                device=self.mic_device_index,
                channels=1,
                samplerate=_SAMPLE_RATE,
                blocksize=_CHUNK,
                dtype="float32",
                callback=callback,
            ):
                while self._running:
                    time.sleep(0.05)
        except Exception as exc:
            logger.error("Mic stream error: %s", exc)

    def _set_base_talking(self, talking: bool) -> None:
        with self._blink_lock:
            if talking:
                new = TALKING_BLINK if self._blinking else TALKING
            else:
                new = IDLE_BLINK if self._blinking else IDLE
        if new != self._state:
            self._state = new
            self._on_state_change(new)

    def _blink_loop(self) -> None:
        while self._running:
            interval = self.blink_interval_avg + random.uniform(-1.5, 1.5)
            interval = max(0.5, interval)
            time.sleep(interval)
            if not self._running or not self.blink_enabled:
                continue

            with self._blink_lock:
                self._blinking = True
                talking = self._state in (TALKING, TALKING_BLINK)
                new = TALKING_BLINK if talking else IDLE_BLINK

            self._state = new
            self._on_state_change(new)

            time.sleep(0.15)

            with self._blink_lock:
                self._blinking = False
                talking = self._state in (TALKING, TALKING_BLINK)
                new = TALKING if talking else IDLE

            self._state = new
            self._on_state_change(new)
