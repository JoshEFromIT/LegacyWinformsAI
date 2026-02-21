"""Session management service — coordinates capture, analysis, and diagram generation."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.models.schemas import (
    RDPConnectionConfig,
    RecordingSession,
    ScreenCapture,
    SessionStatus,
)
from backend.services.analyzer import AnalyzerService
from backend.services.capture import CaptureService
from backend.services.diagram_generator import DiagramGenerator
from backend.services.excalidraw_service import ExcalidrawService

logger = logging.getLogger(__name__)

SESSIONS_DIR = Path("sessions")


class SessionManager:
    """Manages the lifecycle of recording sessions."""

    def __init__(self) -> None:
        self.sessions: dict[str, RecordingSession] = {}
        self.capture_service = CaptureService()
        self.analyzer = AnalyzerService()
        self.excalidraw = ExcalidrawService()
        self.diagram_gen = DiagramGenerator(excalidraw=self.excalidraw)
        self._load_existing_sessions()

    def _load_existing_sessions(self) -> None:
        """Load any previously saved sessions from disk."""
        if not SESSIONS_DIR.exists():
            return
        for session_dir in SESSIONS_DIR.iterdir():
            if not session_dir.is_dir():
                continue
            meta_file = session_dir / "session.json"
            if meta_file.exists():
                try:
                    data = json.loads(meta_file.read_text())
                    session = RecordingSession(**data)
                    self.sessions[session.session_id] = session
                except Exception:
                    logger.exception("Failed to load session %s", session_dir.name)

    def create_session(self, config: Optional[RDPConnectionConfig] = None) -> RecordingSession:
        """Create a new recording session."""
        session_id = f"ses_{uuid.uuid4().hex[:12]}"
        session = RecordingSession(
            session_id=session_id,
            config=config,
            created_at=datetime.utcnow(),
        )
        self.sessions[session_id] = session
        self._save_session(session)
        return session

    async def start_recording(self, session_id: str) -> RecordingSession:
        """Start capturing screenshots for a session."""
        session = self._get_session(session_id)
        if session.status == SessionStatus.RECORDING:
            raise ValueError("Session is already recording")

        session.status = SessionStatus.RECORDING
        session.started_at = datetime.utcnow()

        interval = 2.0
        if session.config:
            interval = session.config.capture_interval_seconds

        async def on_capture(capture_id: str, filename: str, w: int, h: int):
            cap = ScreenCapture(
                capture_id=capture_id,
                session_id=session_id,
                timestamp=datetime.utcnow(),
                filename=filename,
                width=w,
                height=h,
            )
            session.captures.append(cap)
            self._save_session(session)

        await self.capture_service.start_capture_loop(session_id, interval, on_capture)
        self._save_session(session)
        return session

    async def stop_recording(self, session_id: str) -> RecordingSession:
        """Stop capturing and finalize the session."""
        session = self._get_session(session_id)
        await self.capture_service.stop_capture_loop(session_id)
        session.status = SessionStatus.IDLE
        session.stopped_at = datetime.utcnow()
        self._save_session(session)
        return session

    async def upload_frame(self, session_id: str, image_data: bytes) -> ScreenCapture:
        """Upload a screenshot frame to a session (for manual/browser-based capture)."""
        session = self._get_session(session_id)
        capture_id, filename, w, h = await self.capture_service.ingest_frame(
            session_id, image_data
        )
        cap = ScreenCapture(
            capture_id=capture_id,
            session_id=session_id,
            timestamp=datetime.utcnow(),
            filename=filename,
            width=w,
            height=h,
        )
        session.captures.append(cap)
        if session.status == SessionStatus.IDLE:
            session.status = SessionStatus.RECORDING
            if not session.started_at:
                session.started_at = datetime.utcnow()
        self._save_session(session)
        return cap

    async def upload_base64_frame(self, session_id: str, b64_data: str) -> ScreenCapture:
        """Upload a base64-encoded screenshot frame."""
        session = self._get_session(session_id)
        capture_id, filename, w, h = await self.capture_service.ingest_base64_frame(
            session_id, b64_data
        )
        cap = ScreenCapture(
            capture_id=capture_id,
            session_id=session_id,
            timestamp=datetime.utcnow(),
            filename=filename,
            width=w,
            height=h,
        )
        session.captures.append(cap)
        if session.status == SessionStatus.IDLE:
            session.status = SessionStatus.RECORDING
            if not session.started_at:
                session.started_at = datetime.utcnow()
        self._save_session(session)
        return cap

    async def analyze_session(self, session_id: str) -> RecordingSession:
        """Run AI analysis on all captured screenshots and generate diagrams."""
        session = self._get_session(session_id)
        if not session.captures:
            raise ValueError("No captures in session to analyze")

        session.status = SessionStatus.ANALYZING
        self._save_session(session)

        try:
            # Build list of (path, capture_id) for batch analysis
            capture_pairs = []
            for cap in session.captures:
                path = self.capture_service.get_capture_path(session_id, cap.filename)
                if path.exists():
                    capture_pairs.append((path, cap.capture_id))

            # Run AI analysis
            analyses = await self.analyzer.analyze_batch(capture_pairs)

            # Attach analyses back to captures
            analysis_map = {a.capture_id: a for a in analyses}
            for cap in session.captures:
                if cap.capture_id in analysis_map:
                    cap.analysis = analysis_map[cap.capture_id]

            # Generate diagrams and narrative
            title = ""
            if session.config and session.config.display_name:
                title = session.config.display_name

            duration = 0.0
            if session.started_at and session.stopped_at:
                duration = (session.stopped_at - session.started_at).total_seconds()

            # Generate Mermaid diagrams and convert to Excalidraw scenes
            result = await self.diagram_gen.generate_with_excalidraw(
                session_id, analyses, title
            )
            result.duration_seconds = duration
            session.result = result
            session.status = SessionStatus.COMPLETE

        except Exception as e:
            logger.exception("Analysis failed for session %s", session_id)
            session.status = SessionStatus.ERROR
            session.error_message = str(e)

        self._save_session(session)
        return session

    def get_session(self, session_id: str) -> RecordingSession:
        return self._get_session(session_id)

    def list_sessions(self) -> list[RecordingSession]:
        return list(self.sessions.values())

    def delete_session(self, session_id: str) -> None:
        session = self._get_session(session_id)
        session_dir = SESSIONS_DIR / session_id
        if session_dir.exists():
            import shutil
            shutil.rmtree(session_dir)
        del self.sessions[session_id]

    def _get_session(self, session_id: str) -> RecordingSession:
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError(f"Session not found: {session_id}")
        return session

    def _save_session(self, session: RecordingSession) -> None:
        session_dir = SESSIONS_DIR / session.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        meta_file = session_dir / "session.json"
        meta_file.write_text(session.model_dump_json(indent=2))
