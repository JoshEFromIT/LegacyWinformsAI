"""AI-powered screenshot analysis service.

Uses a local LLM via Ollama to analyze screenshots of .NET WinForms applications
with Infragistics and custom controls. Supports loading custom GGUF model files.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
from pathlib import Path
from typing import Optional

import httpx
from PIL import Image

from backend.models.schemas import ScreenAnalysis, UIControl, UserAction

logger = logging.getLogger(__name__)

ANALYSIS_SYSTEM_PROMPT = """\
You are analyzing screenshots of a legacy .NET WinForms application. Extract:
- window_title: window title bar text
- detected_form: logical form/screen name (e.g., "Customer Search")
- controls: array of visible UI controls with control_type, label, state, is_infragistics, is_custom
- actions_since_previous: array of user actions (type, description, target_control) compared to previous state
- narrative_fragment: 1-2 sentence description of what user is doing
- raw_description: detailed description of everything visible

Output ONLY valid JSON (no markdown, no explanation).
"""

# Default directory where users drop .gguf files
MODELS_DIR = Path(os.getenv("MODELS_DIR", "models"))


class AnalyzerService:
    """Analyzes screenshots using a local LLM via Ollama.

    Supports two modes:
    1. Pre-pulled Ollama models (e.g. ``ollama pull llama3.2-vision``)
    2. Custom GGUF files placed in the ``models/`` directory and registered
       automatically with Ollama via its ``/api/create`` endpoint.
    """

    def __init__(self) -> None:
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.model = os.getenv("OLLAMA_MODEL", "llama3.2-vision")
        self.timeout = int(os.getenv("OLLAMA_TIMEOUT", "300"))

        # GGUF configuration
        self.gguf_path = os.getenv("OLLAMA_GGUF_PATH", "")
        self.gguf_projector_path = os.getenv("OLLAMA_GGUF_PROJECTOR_PATH", "")
        self.gguf_model_name = os.getenv("OLLAMA_GGUF_MODEL_NAME", "")

        self._gguf_registered = False

    async def ensure_gguf_model(self) -> None:
        """If a GGUF path is configured, register it with Ollama as a custom model.

        This creates an Ollama model from the .gguf file using the /api/create
        endpoint.  The model is only created once per service lifetime (or when
        explicitly re-registered via the API).
        """
        gguf_file = self._resolve_gguf_path()
        if not gguf_file:
            return

        if self._gguf_registered:
            return

        model_name = self.gguf_model_name or gguf_file.stem.lower().replace(" ", "-")

        # Build the Modelfile content
        modelfile_lines = [f"FROM {gguf_file}"]

        # If a vision projector GGUF is provided, add it as an adapter
        projector = self._resolve_projector_path()
        if projector:
            modelfile_lines.append(f"ADAPTER {projector}")

        max_tokens = int(os.getenv("OLLAMA_MAX_TOKENS", "1024"))
        modelfile_lines.extend([
            f'SYSTEM """{ANALYSIS_SYSTEM_PROMPT}"""',
            "PARAMETER temperature 0.1",
            f"PARAMETER num_predict {max_tokens}",
        ])

        modelfile_content = "\n".join(modelfile_lines)

        logger.info(
            "Registering GGUF model with Ollama: name=%s, gguf=%s",
            model_name, gguf_file,
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.ollama_base_url}/api/create",
                    json={
                        "model": model_name,
                        "modelfile": modelfile_content,
                        "stream": False,
                    },
                )
                resp.raise_for_status()
                logger.info("GGUF model '%s' registered successfully with Ollama", model_name)
                self.model = model_name
                self._gguf_registered = True
        except Exception:
            logger.exception("Failed to register GGUF model '%s' with Ollama", model_name)
            raise

    def _resolve_gguf_path(self) -> Optional[Path]:
        """Resolve the GGUF file path from env var or auto-detect from models/ dir."""
        # Explicit path from env
        if self.gguf_path:
            p = Path(self.gguf_path)
            if p.exists():
                return p
            logger.warning("OLLAMA_GGUF_PATH set to '%s' but file not found", p)
            return None

        # Auto-detect: look for a single .gguf in the models directory
        if MODELS_DIR.exists():
            gguf_files = sorted(MODELS_DIR.glob("*.gguf"))
            if len(gguf_files) == 1:
                logger.info("Auto-detected GGUF model: %s", gguf_files[0])
                return gguf_files[0]
            elif len(gguf_files) > 1:
                logger.warning(
                    "Multiple .gguf files found in %s — set OLLAMA_GGUF_PATH to choose one: %s",
                    MODELS_DIR,
                    [f.name for f in gguf_files],
                )

        return None

    def _resolve_projector_path(self) -> Optional[Path]:
        """Resolve the vision projector GGUF path."""
        if self.gguf_projector_path:
            p = Path(self.gguf_projector_path)
            if p.exists():
                return p
            logger.warning("OLLAMA_GGUF_PROJECTOR_PATH set to '%s' but file not found", p)

        # Auto-detect: look for mmproj/projector gguf in models dir
        if MODELS_DIR.exists():
            for pattern in ["*mmproj*.gguf", "*projector*.gguf"]:
                matches = sorted(MODELS_DIR.glob(pattern))
                if matches:
                    logger.info("Auto-detected vision projector: %s", matches[0])
                    return matches[0]

        return None

    async def analyze_screenshot(
        self,
        image_path: Path,
        capture_id: str,
        previous_analysis: Optional[ScreenAnalysis] = None,
        on_thinking: Optional[object] = None,
    ) -> ScreenAnalysis:
        """Analyze a single screenshot using the local Ollama model.

        ``on_thinking`` is an optional async callback:
            ``async on_thinking(capture_id, partial_text, is_complete)``
        Called with streamed token chunks as the model generates its response.
        """
        await self.ensure_gguf_model()

        image_b64 = self._encode_image(image_path)

        context_msg = ""
        if previous_analysis:
            context_msg = (
                f"\n\nPrevious screenshot context:\n"
                f"- Form: {previous_analysis.detected_form}\n"
                f"- Window: {previous_analysis.window_title}\n"
                f"- Description: {previous_analysis.raw_description}\n"
                f"Compare the current screenshot against this previous state to identify user actions."
            )

        user_prompt = f"Analyze this screenshot of a .NET WinForms application.{context_msg}"

        raw = await self._call_ollama(image_b64, user_prompt, capture_id=capture_id, on_thinking=on_thinking)
        return self._parse_response(raw, capture_id)

    async def analyze_batch(
        self,
        captures: list[tuple[Path, str]],
        on_progress: Optional[object] = None,
        on_thinking: Optional[object] = None,
    ) -> list[ScreenAnalysis]:
        """Analyze screenshots in parallel for much faster throughput.

        Uses a semaphore to limit concurrent Ollama requests (default 4).
        Calls ``on_progress(completed, total, capture_id, narrative, analysis)``
        after each screenshot finishes — the full ``ScreenAnalysis`` result is
        included so callers can build live play-by-play and diagrams.
        Calls ``on_thinking(capture_id, partial_text, is_complete)`` as the
        model streams tokens for each screenshot.
        """
        await self.ensure_gguf_model()

        concurrency = int(os.getenv("OLLAMA_CONCURRENCY", "4"))
        sem = asyncio.Semaphore(concurrency)
        completed_count = 0
        total = len(captures)

        async def _analyze_one(image_path: Path, capture_id: str) -> ScreenAnalysis:
            nonlocal completed_count
            async with sem:
                try:
                    result = await self.analyze_screenshot(
                        image_path, capture_id, on_thinking=on_thinking,
                    )
                except Exception:
                    logger.exception("Failed to analyze capture %s", capture_id)
                    result = ScreenAnalysis(
                        capture_id=capture_id,
                        narrative_fragment="[Analysis failed for this frame]",
                    )
                completed_count += 1
                if on_progress:
                    await on_progress(
                        completed_count, total, capture_id,
                        result.narrative_fragment or "",
                        result,
                    )
                return result

        tasks = [
            _analyze_one(image_path, capture_id)
            for image_path, capture_id in captures
        ]
        results = await asyncio.gather(*tasks)
        return list(results)

    def _encode_image(self, path: Path) -> str:
        """Encode image to base64, resizing large images for faster inference."""
        max_dim = int(os.getenv("IMAGE_MAX_DIM", "1280"))
        img = Image.open(path)

        # Resize if either dimension exceeds max_dim
        if img.width > max_dim or img.height > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)
            buf = io.BytesIO()
            fmt = "PNG" if path.suffix.lower() == ".png" else "JPEG"
            img.save(buf, format=fmt, quality=85)
            return base64.b64encode(buf.getvalue()).decode("utf-8")

        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    async def _call_ollama(
        self,
        image_b64: str,
        user_prompt: str,
        capture_id: str = "",
        on_thinking: Optional[object] = None,
    ) -> dict:
        """Call the local Ollama API with a model request.

        When ``on_thinking`` is provided the Ollama request is streamed so that
        partial token output can be forwarded in real-time.  Otherwise the
        request is non-streaming for simplicity.
        """
        url = f"{self.ollama_base_url}/api/chat"

        user_message: dict = {
            "role": "user",
            "content": user_prompt,
            "images": [image_b64],
        }

        max_tokens = int(os.getenv("OLLAMA_MAX_TOKENS", "1024"))
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": ANALYSIS_SYSTEM_PROMPT,
                },
                user_message,
            ],
            "stream": bool(on_thinking),
            "options": {
                "num_predict": max_tokens,
                "temperature": 0.1,
            },
            "format": "json",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            if not on_thinking:
                # Non-streaming path (original behaviour)
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                text = data["message"]["content"]
                return self._extract_json(text)

            # Streaming path — forward tokens via on_thinking callback
            full_text = ""
            last_callback_time = 0.0
            import time

            async with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        full_text += token

                    # Throttle callbacks to ~every 0.4s to avoid flooding
                    now = time.monotonic()
                    is_done = chunk.get("done", False)
                    if is_done or (now - last_callback_time >= 0.4 and full_text):
                        try:
                            await on_thinking(capture_id, full_text, is_done)
                        except Exception:
                            pass  # don't let callback errors break analysis
                        last_callback_time = now

            return self._extract_json(full_text)

    async def check_health(self) -> dict:
        """Check if Ollama is reachable, the model is available, and GGUF status."""
        gguf_file = self._resolve_gguf_path()
        projector_file = self._resolve_projector_path()

        gguf_info = {
            "gguf_configured": bool(gguf_file),
            "gguf_path": str(gguf_file) if gguf_file else None,
            "gguf_projector_path": str(projector_file) if projector_file else None,
            "gguf_registered": self._gguf_registered,
        }

        # Scan models/ dir for available GGUF files
        available_gguf: list[str] = []
        if MODELS_DIR.exists():
            available_gguf = [f.name for f in sorted(MODELS_DIR.glob("*.gguf"))]
        gguf_info["available_gguf_files"] = available_gguf

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.ollama_base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()

                available_models = [m["name"] for m in data.get("models", [])]
                model_ready = any(
                    self.model in name for name in available_models
                )

                return {
                    "ollama_reachable": True,
                    "ollama_url": self.ollama_base_url,
                    "configured_model": self.model,
                    "model_ready": model_ready,
                    "available_models": available_models,
                    **gguf_info,
                }
        except httpx.ConnectError:
            return {
                "ollama_reachable": False,
                "ollama_url": self.ollama_base_url,
                "configured_model": self.model,
                "model_ready": False,
                "available_models": [],
                "error": "Cannot connect to Ollama. Is it running?",
                **gguf_info,
            }
        except Exception as e:
            return {
                "ollama_reachable": False,
                "ollama_url": self.ollama_base_url,
                "configured_model": self.model,
                "model_ready": False,
                "available_models": [],
                "error": str(e),
                **gguf_info,
            }

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from LLM response, handling markdown code blocks."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to find JSON object in the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

        # Return a minimal fallback structure
        logger.warning("Could not parse JSON from LLM response, using fallback")
        return {
            "window_title": "",
            "detected_form": "",
            "controls": [],
            "actions_since_previous": [],
            "narrative_fragment": text[:200] if text else "[No response from model]",
            "raw_description": text,
        }

    def _parse_response(self, raw: dict, capture_id: str) -> ScreenAnalysis:
        controls = []
        for c in raw.get("controls", []):
            controls.append(UIControl(
                control_type=c.get("control_type", "Unknown"),
                label=c.get("label", ""),
                state=c.get("state", ""),
                is_infragistics=c.get("is_infragistics", False),
                is_custom=c.get("is_custom", False),
            ))

        actions = []
        for a in raw.get("actions_since_previous", []):
            target = None
            if a.get("target_control"):
                target = UIControl(
                    control_type=a["target_control"].get("control_type", ""),
                    label=a["target_control"].get("label", ""),
                )
            actions.append(UserAction(
                action_type=a.get("action_type", "unknown"),
                description=a.get("description", ""),
                confidence=a.get("confidence", 0.5),
                target_control=target,
            ))

        return ScreenAnalysis(
            capture_id=capture_id,
            window_title=raw.get("window_title", ""),
            detected_form=raw.get("detected_form", ""),
            controls=controls,
            actions_since_previous=actions,
            narrative_fragment=raw.get("narrative_fragment", ""),
            raw_description=raw.get("raw_description", ""),
        )
