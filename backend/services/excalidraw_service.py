"""Excalidraw MCP canvas server integration service.

Communicates with the yctimlin/mcp_excalidraw canvas server REST API
to convert Mermaid diagrams into Excalidraw scenes and export them as
images or JSON.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class ExcalidrawService:
    """Client for the Excalidraw MCP canvas server REST API."""

    def __init__(self) -> None:
        self.canvas_url = os.getenv(
            "EXCALIDRAW_CANVAS_URL", "http://localhost:3000"
        )
        self.timeout = int(os.getenv("EXCALIDRAW_TIMEOUT", "60"))

    async def check_health(self) -> dict:
        """Check if the Excalidraw canvas server is reachable."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.canvas_url}/health")
                resp.raise_for_status()
                data = resp.json()
                return {
                    "excalidraw_reachable": True,
                    "excalidraw_url": self.canvas_url,
                    "elements_count": data.get("elements_count", 0),
                    "websocket_clients": data.get("websocket_clients", 0),
                }
        except httpx.ConnectError:
            return {
                "excalidraw_reachable": False,
                "excalidraw_url": self.canvas_url,
                "error": "Cannot connect to Excalidraw canvas server. Is it running?",
            }
        except Exception as e:
            return {
                "excalidraw_reachable": False,
                "excalidraw_url": self.canvas_url,
                "error": str(e),
            }

    async def clear_canvas(self) -> dict:
        """Clear all elements from the canvas."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.delete(f"{self.canvas_url}/api/elements/clear")
            resp.raise_for_status()
            return resp.json()

    async def create_from_mermaid(
        self,
        mermaid_diagram: str,
        config: Optional[dict] = None,
    ) -> dict:
        """Convert a Mermaid diagram into Excalidraw elements on the canvas.

        Args:
            mermaid_diagram: Mermaid syntax string (e.g. flowchart, sequence diagram).
            config: Optional configuration for the conversion.

        Returns:
            Response dict from the canvas server.
        """
        payload: dict[str, Any] = {"mermaidDiagram": mermaid_diagram}
        if config:
            payload["config"] = config

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.canvas_url}/api/elements/from-mermaid",
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_elements(self) -> list[dict]:
        """Get all elements currently on the canvas."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.canvas_url}/api/elements")
            resp.raise_for_status()
            data = resp.json()
            return data.get("elements", [])

    async def export_scene(self) -> dict:
        """Export the current canvas scene as an Excalidraw JSON structure."""
        elements = await self.get_elements()
        return {
            "type": "excalidraw",
            "version": 2,
            "source": "legacywinformsai",
            "elements": elements,
            "appState": {
                "viewBackgroundColor": "#ffffff",
                "gridSize": None,
            },
            "files": {},
        }

    async def export_to_image(
        self,
        fmt: str = "svg",
        background: bool = True,
    ) -> Optional[str]:
        """Export the canvas as an image (PNG base64 or SVG string).

        Args:
            fmt: Image format — "png" or "svg".
            background: Whether to include background.

        Returns:
            Base64-encoded PNG data or SVG string, or None on failure.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.canvas_url}/api/export/image",
                json={"format": fmt, "background": background},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("success"):
                return data.get("data")
            return None

    async def create_element(self, element: dict) -> dict:
        """Create a single element on the canvas."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.canvas_url}/api/elements",
                json=element,
            )
            resp.raise_for_status()
            return resp.json()

    async def batch_create_elements(self, elements: list[dict]) -> dict:
        """Create multiple elements in a single operation."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.canvas_url}/api/elements/batch",
                json={"elements": elements},
            )
            resp.raise_for_status()
            return resp.json()

    async def save_snapshot(self, name: str) -> dict:
        """Save a named snapshot of the current canvas state."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.canvas_url}/api/snapshots",
                json={"name": name},
            )
            resp.raise_for_status()
            return resp.json()

    async def convert_mermaid_to_excalidraw(
        self,
        mermaid_flowchart: str,
        mermaid_sequence: str,
        mermaid_state: str,
        session_id: str,
    ) -> dict:
        """Convert all three Mermaid diagram types to Excalidraw scenes.

        Processes each diagram type sequentially: clears the canvas, converts
        the Mermaid source, exports the scene, and collects all results.

        Returns:
            Dict with keys ``flowchart``, ``sequence``, ``state`` each
            containing the Excalidraw JSON scene.
        """
        results: dict[str, Any] = {}

        diagrams = [
            ("flowchart", mermaid_flowchart),
            ("sequence", mermaid_sequence),
            ("state", mermaid_state),
        ]

        for diagram_type, mermaid_source in diagrams:
            if not mermaid_source:
                results[diagram_type] = None
                continue

            try:
                # Clear canvas before each conversion
                await self.clear_canvas()

                # Send Mermaid to the canvas server for conversion
                await self.create_from_mermaid(mermaid_source)

                # Export the resulting scene
                scene = await self.export_scene()
                results[diagram_type] = scene

                # Save a snapshot for later retrieval
                snapshot_name = f"{session_id}_{diagram_type}"
                try:
                    await self.save_snapshot(snapshot_name)
                except Exception:
                    logger.debug(
                        "Snapshot save failed for %s (non-critical)",
                        snapshot_name,
                    )

            except Exception:
                logger.exception(
                    "Failed to convert %s Mermaid diagram to Excalidraw",
                    diagram_type,
                )
                results[diagram_type] = None

        return results
