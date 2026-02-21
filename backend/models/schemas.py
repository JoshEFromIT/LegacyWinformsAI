"""Data models for the RDP Recorder application."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SessionStatus(str, enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    ANALYZING = "analyzing"
    COMPLETE = "complete"
    ERROR = "error"


class RDPConnectionConfig(BaseModel):
    """Configuration for an RDP connection to capture."""
    host: str
    port: int = 3389
    username: str = ""
    display_name: str = ""
    capture_interval_seconds: float = Field(
        default=2.0,
        ge=0.5,
        le=30.0,
        description="Seconds between screenshot captures",
    )


class ScreenCapture(BaseModel):
    """A single captured screenshot with metadata."""
    capture_id: str
    session_id: str
    timestamp: datetime
    filename: str
    width: int = 0
    height: int = 0
    analysis: Optional[ScreenAnalysis] = None


class UIControl(BaseModel):
    """A detected UI control in a screenshot."""
    control_type: str = Field(
        description="e.g. UltraGrid, UltraTextEditor, UltraComboEditor, Button, DataGridView, custom"
    )
    label: str = ""
    bounds: Optional[dict] = None
    state: str = ""
    is_infragistics: bool = False
    is_custom: bool = False


class UserAction(BaseModel):
    """A detected user action between two frames."""
    action_type: str = Field(
        description="e.g. click, type, scroll, navigate, select, drag, resize"
    )
    target_control: Optional[UIControl] = None
    description: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ScreenAnalysis(BaseModel):
    """AI analysis of a single screenshot."""
    capture_id: str
    window_title: str = ""
    detected_form: str = ""
    controls: list[UIControl] = []
    actions_since_previous: list[UserAction] = []
    narrative_fragment: str = ""
    raw_description: str = ""


class FlowStep(BaseModel):
    """A step in the user interaction flow."""
    step_number: int
    form_name: str = ""
    action_summary: str = ""
    capture_ids: list[str] = []
    controls_involved: list[str] = []


class SessionResult(BaseModel):
    """Final output of a recording session analysis."""
    session_id: str
    title: str = ""
    narrative: str = ""
    mermaid_flowchart: str = ""
    mermaid_sequence: str = ""
    mermaid_state: str = ""
    excalidraw_flowchart: Optional[dict] = Field(
        default=None, description="Excalidraw JSON scene for the flowchart diagram"
    )
    excalidraw_sequence: Optional[dict] = Field(
        default=None, description="Excalidraw JSON scene for the sequence diagram"
    )
    excalidraw_state: Optional[dict] = Field(
        default=None, description="Excalidraw JSON scene for the state diagram"
    )
    excalidraw_ai_designed: Optional[dict] = Field(
        default=None,
        description="Excalidraw JSON scene designed directly by the AI (richer than Mermaid conversion)",
    )
    flow_steps: list[FlowStep] = []
    total_captures: int = 0
    duration_seconds: float = 0.0


class RecordingSession(BaseModel):
    """A recording session."""
    session_id: str
    status: SessionStatus = SessionStatus.IDLE
    config: Optional[RDPConnectionConfig] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    captures: list[ScreenCapture] = []
    result: Optional[SessionResult] = None
    error_message: Optional[str] = None


# Forward reference resolution
ScreenCapture.model_rebuild()
