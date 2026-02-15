"""AI-powered screenshot analysis service.

Uses a local vision-capable LLM via Ollama (llama3.2-vision by default) to analyze
screenshots of .NET WinForms applications with Infragistics and custom controls.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Optional

import httpx

from backend.models.schemas import ScreenAnalysis, UIControl, UserAction

logger = logging.getLogger(__name__)

ANALYSIS_SYSTEM_PROMPT = """\
You are an expert analyst for legacy .NET WinForms desktop applications that use Infragistics \
controls (UltraGrid, UltraTextEditor, UltraComboEditor, UltraToolbarsManager, UltraDockManager, etc.) \
and custom-built controls.

You will receive screenshots from an RDP session showing a WinForms application. \
Your job is to analyze each screenshot and identify:

1. **Window/Form Title**: The title bar text of the active window.
2. **Form Name**: Infer the logical form or screen name (e.g., "Customer Search", "Order Entry").
3. **UI Controls**: List all visible controls with:
   - control_type: Specific Infragistics control name if recognizable, otherwise standard WinForms type
   - label: Any visible label/text associated with the control
   - state: Current state (focused, disabled, populated, empty, expanded, collapsed, etc.)
   - is_infragistics: true if it appears to be an Infragistics component
   - is_custom: true if it appears to be a non-standard custom control
4. **User Actions**: If a previous screenshot description is provided, describe what the user did \
between the previous state and the current state.
5. **Narrative**: A concise sentence describing what the user is doing in this screenshot.
6. **Raw Description**: A detailed description of everything visible on screen.

Respond ONLY with valid JSON matching this structure:
{
  "window_title": "string",
  "detected_form": "string",
  "controls": [
    {
      "control_type": "string",
      "label": "string",
      "state": "string",
      "is_infragistics": bool,
      "is_custom": bool
    }
  ],
  "actions_since_previous": [
    {
      "action_type": "string",
      "description": "string",
      "confidence": float,
      "target_control": {"control_type": "string", "label": "string"} | null
    }
  ],
  "narrative_fragment": "string",
  "raw_description": "string"
}
"""


class AnalyzerService:
    """Analyzes screenshots using a local vision-capable LLM via Ollama."""

    def __init__(self) -> None:
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.model = os.getenv("OLLAMA_MODEL", "llama3.2-vision")
        self.timeout = int(os.getenv("OLLAMA_TIMEOUT", "300"))

    async def analyze_screenshot(
        self,
        image_path: Path,
        capture_id: str,
        previous_analysis: Optional[ScreenAnalysis] = None,
    ) -> ScreenAnalysis:
        """Analyze a single screenshot using the local Ollama vision model."""
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

        raw = await self._call_ollama(image_b64, user_prompt)
        return self._parse_response(raw, capture_id)

    async def analyze_batch(
        self,
        captures: list[tuple[Path, str]],
    ) -> list[ScreenAnalysis]:
        """Analyze a sequence of screenshots, threading context between frames."""
        results: list[ScreenAnalysis] = []
        prev: Optional[ScreenAnalysis] = None

        for image_path, capture_id in captures:
            try:
                analysis = await self.analyze_screenshot(image_path, capture_id, prev)
                results.append(analysis)
                prev = analysis
            except Exception:
                logger.exception("Failed to analyze capture %s", capture_id)
                results.append(ScreenAnalysis(
                    capture_id=capture_id,
                    narrative_fragment="[Analysis failed for this frame]",
                ))
                # Keep prev as-is so next frame still has context

        return results

    def _encode_image(self, path: Path) -> str:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    async def _call_ollama(self, image_b64: str, user_prompt: str) -> dict:
        """Call the local Ollama API with a vision model request."""
        url = f"{self.ollama_base_url}/api/chat"

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": ANALYSIS_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                    "images": [image_b64],
                },
            ],
            "stream": False,
            "options": {
                "num_predict": 4096,
                "temperature": 0.1,
            },
            "format": "json",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            text = data["message"]["content"]
            return self._extract_json(text)

    async def check_health(self) -> dict:
        """Check if Ollama is reachable and the configured model is available."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Check Ollama is running
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
                }
        except httpx.ConnectError:
            return {
                "ollama_reachable": False,
                "ollama_url": self.ollama_base_url,
                "configured_model": self.model,
                "model_ready": False,
                "available_models": [],
                "error": "Cannot connect to Ollama. Is it running?",
            }
        except Exception as e:
            return {
                "ollama_reachable": False,
                "ollama_url": self.ollama_base_url,
                "configured_model": self.model,
                "model_ready": False,
                "available_models": [],
                "error": str(e),
            }

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from LLM response, handling markdown code blocks."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (``` markers)
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
