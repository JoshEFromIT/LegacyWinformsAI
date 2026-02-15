"""Screen capture service for RDP sessions.

Supports multiple capture strategies:
1. Screenshot-based: Captures the RDP client window on the host machine
2. Image upload: Accepts manually uploaded screenshots (for remote/headless scenarios)
3. VNC/RFB proxy: (future) Direct framebuffer capture
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)

SESSIONS_DIR = Path(os.getenv("SESSIONS_DIR", "sessions"))


class CaptureService:
    """Manages screen capture for recording sessions."""

    def __init__(self) -> None:
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._stop_events: dict[str, asyncio.Event] = {}

    async def start_capture_loop(
        self,
        session_id: str,
        interval: float,
        on_capture: callable,
    ) -> None:
        """Start periodic screenshot capture for a session.

        In headless/server environments, this loop waits for frames
        to be pushed via `ingest_frame` instead of grabbing the screen.
        """
        stop_event = asyncio.Event()
        self._stop_events[session_id] = stop_event

        async def _loop():
            logger.info("Capture loop started for session %s (interval=%.1fs)", session_id, interval)
            while not stop_event.is_set():
                try:
                    frame = await self._try_grab_screen(session_id)
                    if frame is not None:
                        capture_id = f"cap_{uuid.uuid4().hex[:12]}"
                        filename = f"{capture_id}.png"
                        filepath = self._session_dir(session_id) / filename
                        frame.save(str(filepath), "PNG")
                        w, h = frame.size
                        await on_capture(capture_id, filename, w, h)
                except Exception:
                    logger.exception("Capture error in session %s", session_id)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=interval)
                    break  # stop_event was set
                except asyncio.TimeoutError:
                    pass  # interval elapsed, loop again

            logger.info("Capture loop stopped for session %s", session_id)

        task = asyncio.create_task(_loop())
        self._active_tasks[session_id] = task

    async def stop_capture_loop(self, session_id: str) -> None:
        """Stop the capture loop for a session."""
        event = self._stop_events.pop(session_id, None)
        if event:
            event.set()
        task = self._active_tasks.pop(session_id, None)
        if task:
            try:
                await asyncio.wait_for(task, timeout=10)
            except asyncio.TimeoutError:
                task.cancel()

    async def ingest_frame(
        self,
        session_id: str,
        image_data: bytes,
        content_type: str = "image/png",
    ) -> tuple[str, str, int, int]:
        """Ingest a manually-uploaded screenshot frame.

        Returns (capture_id, filename, width, height).
        """
        capture_id = f"cap_{uuid.uuid4().hex[:12]}"
        filename = f"{capture_id}.png"
        filepath = self._session_dir(session_id) / filename

        img = Image.open(io.BytesIO(image_data))
        img.save(str(filepath), "PNG")
        w, h = img.size
        return capture_id, filename, w, h

    async def ingest_base64_frame(
        self,
        session_id: str,
        b64_data: str,
    ) -> tuple[str, str, int, int]:
        """Ingest a base64-encoded screenshot frame."""
        image_data = base64.b64decode(b64_data)
        return await self.ingest_frame(session_id, image_data)

    def get_capture_path(self, session_id: str, filename: str) -> Path:
        return self._session_dir(session_id) / filename

    def _session_dir(self, session_id: str) -> Path:
        d = SESSIONS_DIR / session_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    async def _try_grab_screen(self, session_id: str) -> Optional[Image.Image]:
        """Attempt to grab a screenshot from the screen.

        Returns None in headless environments (frames must be pushed via ingest_frame).
        """
        try:
            import mss

            with mss.mss() as sct:
                monitor = sct.monitors[1]  # primary monitor
                screenshot = sct.grab(monitor)
                img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
                return img
        except Exception:
            # No display available — headless mode, rely on manual uploads
            return None
