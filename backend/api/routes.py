"""FastAPI routes for the RDP Recorder application."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from backend.models.schemas import RDPConnectionConfig, RecordingSession, ScreenCapture
from backend.services.session_manager import SessionManager
from backend.services.analyzer import AnalyzerService

router = APIRouter(prefix="/api")

# Singleton session manager
_manager: Optional[SessionManager] = None


def get_manager() -> SessionManager:
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager


class CreateSessionRequest(BaseModel):
    host: str = ""
    port: int = 3389
    username: str = ""
    display_name: str = ""
    capture_interval_seconds: float = 2.0


class UploadFrameBase64Request(BaseModel):
    image_base64: str


# --- Session CRUD ---

@router.post("/sessions", response_model=RecordingSession)
async def create_session(req: CreateSessionRequest):
    """Create a new recording session."""
    config = None
    if req.host:
        config = RDPConnectionConfig(
            host=req.host,
            port=req.port,
            username=req.username,
            display_name=req.display_name,
            capture_interval_seconds=req.capture_interval_seconds,
        )
    return get_manager().create_session(config)


@router.get("/sessions", response_model=list[RecordingSession])
async def list_sessions():
    """List all recording sessions."""
    return get_manager().list_sessions()


@router.get("/sessions/{session_id}", response_model=RecordingSession)
async def get_session(session_id: str):
    """Get a specific session."""
    try:
        return get_manager().get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and its data."""
    try:
        get_manager().delete_session(session_id)
        return {"status": "deleted"}
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


# --- Recording Control ---

@router.post("/sessions/{session_id}/start", response_model=RecordingSession)
async def start_recording(session_id: str):
    """Start screen capture recording."""
    try:
        return await get_manager().start_recording(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sessions/{session_id}/stop", response_model=RecordingSession)
async def stop_recording(session_id: str):
    """Stop screen capture recording."""
    try:
        return await get_manager().stop_recording(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


# --- Frame Upload ---

@router.post("/sessions/{session_id}/frames", response_model=ScreenCapture)
async def upload_frame(session_id: str, file: UploadFile = File(...)):
    """Upload a screenshot frame (PNG/JPG)."""
    try:
        image_data = await file.read()
        return await get_manager().upload_frame(session_id, image_data)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


@router.post("/sessions/{session_id}/frames/base64", response_model=ScreenCapture)
async def upload_frame_base64(session_id: str, req: UploadFrameBase64Request):
    """Upload a base64-encoded screenshot frame."""
    try:
        return await get_manager().upload_base64_frame(session_id, req.image_base64)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


# --- Analysis ---

@router.post("/sessions/{session_id}/analyze", response_model=RecordingSession)
async def analyze_session(session_id: str):
    """Run AI analysis on captured screenshots and generate diagrams."""
    try:
        return await get_manager().analyze_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Results ---

@router.get("/sessions/{session_id}/result")
async def get_result(session_id: str):
    """Get the analysis result (diagrams and narrative) for a session."""
    try:
        session = get_manager().get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.result:
        raise HTTPException(status_code=404, detail="No analysis results yet. Run /analyze first.")

    return session.result


@router.get("/sessions/{session_id}/captures/{capture_id}/image")
async def get_capture_image(session_id: str, capture_id: str):
    """Serve a captured screenshot image."""
    from fastapi.responses import FileResponse

    try:
        session = get_manager().get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    for cap in session.captures:
        if cap.capture_id == capture_id:
            path = get_manager().capture_service.get_capture_path(session_id, cap.filename)
            if path.exists():
                return FileResponse(str(path), media_type="image/png")
            raise HTTPException(status_code=404, detail="Image file not found")

    raise HTTPException(status_code=404, detail="Capture not found")


# --- Ollama Health Check ---

@router.get("/health/ollama")
async def ollama_health():
    """Check Ollama connectivity, model availability, and GGUF status."""
    analyzer = AnalyzerService()
    return await analyzer.check_health()


# --- GGUF Model Management ---

@router.post("/models/register-gguf")
async def register_gguf_model():
    """Register a GGUF model file with Ollama.

    Detects .gguf files in the models/ directory (or from OLLAMA_GGUF_PATH)
    and creates an Ollama model from the Modelfile.
    """
    analyzer = AnalyzerService()
    analyzer._gguf_registered = False  # Force re-registration
    try:
        await analyzer.ensure_gguf_model()
        if analyzer._gguf_registered:
            return {
                "status": "registered",
                "model_name": analyzer.model,
                "message": f"GGUF model registered as '{analyzer.model}' in Ollama",
            }
        else:
            raise HTTPException(
                status_code=404,
                detail="No .gguf file found. Place a .gguf file in the models/ directory or set OLLAMA_GGUF_PATH.",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to register GGUF model: {e}")
