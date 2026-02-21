"""AI-powered Excalidraw diagram designer.

Uses the local Ollama LLM to design architecture diagrams directly as
Excalidraw elements, giving the AI full creative control over layout,
colours, and visual hierarchy — rather than converting from Mermaid.
"""

from __future__ import annotations

import json
import logging
import math
import os
import uuid
from typing import Any, Optional

import httpx

from backend.models.schemas import ScreenAnalysis

logger = logging.getLogger(__name__)

DESIGNER_SYSTEM_PROMPT = """\
You are an expert software architect and visual diagram designer.

Given a summary of screens, UI controls, and user actions observed in a \
legacy .NET WinForms desktop application, design an architecture / workflow \
diagram.  Output a JSON object describing the diagram with these fields:

{
  "title": "short diagram title",
  "nodes": [
    {
      "id": "unique_id",
      "label": "Display Name",
      "description": "optional 1-line note shown below the label",
      "shape": "rectangle" | "ellipse" | "diamond",
      "color": "hex background colour e.g. #a5d8ff",
      "group": "optional group name to cluster related nodes"
    }
  ],
  "edges": [
    {
      "from": "source node id",
      "to": "target node id",
      "label": "optional edge label"
    }
  ]
}

Design guidelines:
- Create a node for each distinct form / screen.
- Add a START ellipse and an END ellipse.
- Use diamond nodes for decision / branch points when user actions diverge.
- Use colours to distinguish Infragistics-heavy forms (#a5d8ff blue), \
  custom-control forms (#b2f2bb green), and standard forms (#e9ecef grey).
- Edges represent user navigation or actions between screens.
- Keep labels concise (max 30 chars). Put detail in the description field.
- Respond ONLY with valid JSON — no markdown, no explanation.
"""


class ExcalidrawDesigner:
    """Asks the LLM to design a diagram, then builds Excalidraw elements."""

    def __init__(self) -> None:
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.model = os.getenv("OLLAMA_MODEL", "llama3.2-vision")
        self.timeout = int(os.getenv("OLLAMA_TIMEOUT", "300"))

    async def design_diagram(
        self,
        analyses: list[ScreenAnalysis],
    ) -> Optional[dict]:
        """Ask the LLM to design a diagram and return an Excalidraw scene.

        Returns an Excalidraw-format dict with ``type``, ``elements``, etc.,
        or ``None`` if generation fails.
        """
        summary = self._build_analysis_summary(analyses)
        diagram_spec = await self._call_ollama(summary)
        if not diagram_spec or not diagram_spec.get("nodes"):
            logger.warning("LLM returned empty diagram spec")
            return None

        elements = self._build_excalidraw_elements(diagram_spec)
        return {
            "type": "excalidraw",
            "version": 2,
            "source": "legacywinformsai-ai-designer",
            "elements": elements,
            "appState": {
                "viewBackgroundColor": "#ffffff",
                "gridSize": None,
            },
            "files": {},
        }

    # ------------------------------------------------------------------
    # Analysis → prompt
    # ------------------------------------------------------------------

    def _build_analysis_summary(self, analyses: list[ScreenAnalysis]) -> str:
        """Condense the screen analyses into a textual summary for the LLM."""
        lines: list[str] = []
        seen_forms: dict[str, dict[str, Any]] = {}

        for a in analyses:
            form = a.detected_form or a.window_title or "Unknown"
            if form not in seen_forms:
                seen_forms[form] = {
                    "controls": [],
                    "actions": [],
                    "has_infragistics": False,
                    "has_custom": False,
                }

            info = seen_forms[form]
            for c in a.controls:
                ctrl_desc = c.control_type
                if c.label:
                    ctrl_desc += f" ({c.label})"
                if ctrl_desc not in info["controls"]:
                    info["controls"].append(ctrl_desc)
                if c.is_infragistics:
                    info["has_infragistics"] = True
                if c.is_custom:
                    info["has_custom"] = True

            for act in a.actions_since_previous:
                info["actions"].append(act.description or act.action_type)

        lines.append(f"Application has {len(seen_forms)} distinct screens:\n")
        for form_name, info in seen_forms.items():
            tag = ""
            if info["has_infragistics"]:
                tag = " [Infragistics]"
            elif info["has_custom"]:
                tag = " [Custom Controls]"
            lines.append(f"## {form_name}{tag}")
            if info["controls"]:
                lines.append(f"  Controls: {', '.join(info['controls'][:10])}")
            if info["actions"]:
                unique = list(dict.fromkeys(info["actions"]))[:5]
                lines.append(f"  User actions: {'; '.join(unique)}")
            lines.append("")

        # Navigation order
        nav = []
        prev = ""
        for a in analyses:
            form = a.detected_form or a.window_title or "Unknown"
            if form != prev:
                nav.append(form)
                prev = form
        lines.append(f"Navigation order: {' → '.join(nav)}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Ollama call
    # ------------------------------------------------------------------

    async def _call_ollama(self, user_prompt: str) -> dict:
        url = f"{self.ollama_base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": DESIGNER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {
                "num_predict": 4096,
                "temperature": 0.3,
            },
            "format": "json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                text = data["message"]["content"]
                return self._extract_json(text)
        except Exception:
            logger.exception("Ollama call for Excalidraw design failed")
            return {}

    # ------------------------------------------------------------------
    # Diagram spec → Excalidraw elements
    # ------------------------------------------------------------------

    def _build_excalidraw_elements(self, spec: dict) -> list[dict]:
        """Convert the LLM's diagram spec into Excalidraw element dicts."""
        nodes = spec.get("nodes", [])
        edges = spec.get("edges", [])

        if not nodes:
            return []

        # Assign layout positions using a simple top-down flow
        positions = self._layout_nodes(nodes)

        elements: list[dict] = []
        node_elements: dict[str, dict] = {}

        for node in nodes:
            nid = node.get("id", str(uuid.uuid4())[:8])
            label = node.get("label", "?")
            desc = node.get("description", "")
            shape = node.get("shape", "rectangle")
            color = node.get("color", "#e9ecef")
            x, y = positions.get(nid, (0, 0))

            # Size depends on content
            text_len = max(len(label), len(desc) if desc else 0)
            width = max(160, text_len * 9 + 40)
            height = 70 if not desc else 90

            el = self._make_shape(nid, shape, x, y, width, height, color)
            elements.append(el)
            node_elements[nid] = el

            # Label text
            text_el = self._make_text(
                f"{nid}_label", label,
                x + width / 2, y + (20 if desc else height / 2),
                font_size=16, bold=True,
            )
            elements.append(text_el)

            # Description text
            if desc:
                desc_el = self._make_text(
                    f"{nid}_desc", desc,
                    x + width / 2, y + 50,
                    font_size=12, color="#555555",
                )
                elements.append(desc_el)

        # Edges (arrows)
        for edge in edges:
            src_id = edge.get("from", "")
            dst_id = edge.get("to", "")
            edge_label = edge.get("label", "")

            src_el = node_elements.get(src_id)
            dst_el = node_elements.get(dst_id)
            if not src_el or not dst_el:
                continue

            arrow_el, label_el = self._make_arrow(
                src_el, dst_el, edge_label
            )
            elements.append(arrow_el)
            if label_el:
                elements.append(label_el)

        return elements

    def _layout_nodes(self, nodes: list[dict]) -> dict[str, tuple[float, float]]:
        """Simple top-down layout with grouping support."""
        positions: dict[str, tuple[float, float]] = {}

        # Group nodes
        groups: dict[str, list[dict]] = {}
        ungrouped: list[dict] = []
        for node in nodes:
            group = node.get("group", "")
            if group:
                groups.setdefault(group, []).append(node)
            else:
                ungrouped.append(node)

        y_cursor = 60.0
        x_center = 400.0
        y_step = 140.0
        x_gap = 240.0

        # Layout ungrouped nodes in a column
        for node in ungrouped:
            nid = node.get("id", "")
            positions[nid] = (x_center - 80, y_cursor)
            y_cursor += y_step

        # Layout groups side-by-side
        for group_name, group_nodes in groups.items():
            total_width = len(group_nodes) * x_gap
            x_start = x_center - total_width / 2
            for i, node in enumerate(group_nodes):
                nid = node.get("id", "")
                positions[nid] = (x_start + i * x_gap, y_cursor)
            y_cursor += y_step

        return positions

    # ------------------------------------------------------------------
    # Excalidraw element factories
    # ------------------------------------------------------------------

    @staticmethod
    def _make_shape(
        nid: str, shape: str, x: float, y: float,
        width: float, height: float, bg_color: str,
    ) -> dict:
        etype = "rectangle"
        if shape == "ellipse":
            etype = "ellipse"
        elif shape == "diamond":
            etype = "diamond"

        return {
            "id": nid,
            "type": etype,
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "strokeColor": "#1e1e1e",
            "backgroundColor": bg_color,
            "fillStyle": "solid",
            "strokeWidth": 2,
            "roughness": 1,
            "opacity": 100,
            "angle": 0,
            "groupIds": [],
            "roundness": {"type": 3} if etype == "rectangle" else None,
            "isDeleted": False,
            "boundElements": [],
            "locked": False,
        }

    @staticmethod
    def _make_text(
        tid: str, text: str, cx: float, cy: float,
        font_size: int = 16, color: str = "#1e1e1e", bold: bool = False,
    ) -> dict:
        # Estimate text width
        char_width = font_size * 0.6
        text_width = len(text) * char_width
        text_height = font_size * 1.4

        return {
            "id": tid,
            "type": "text",
            "x": cx - text_width / 2,
            "y": cy - text_height / 2,
            "width": text_width,
            "height": text_height,
            "text": text,
            "fontSize": font_size,
            "fontFamily": 1,
            "textAlign": "center",
            "verticalAlign": "middle",
            "strokeColor": color,
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 1,
            "roughness": 0,
            "opacity": 100,
            "angle": 0,
            "groupIds": [],
            "isDeleted": False,
            "boundElements": [],
            "locked": False,
        }

    @staticmethod
    def _make_arrow(
        src: dict, dst: dict, label: str = "",
    ) -> tuple[dict, Optional[dict]]:
        """Create an arrow from the bottom-center of src to the top-center of dst."""
        src_cx = src["x"] + src["width"] / 2
        src_bottom = src["y"] + src["height"]
        dst_cx = dst["x"] + dst["width"] / 2
        dst_top = dst["y"]

        dx = dst_cx - src_cx
        dy = dst_top - src_bottom

        arrow_id = f"arrow_{src['id']}_{dst['id']}"

        arrow = {
            "id": arrow_id,
            "type": "arrow",
            "x": src_cx,
            "y": src_bottom,
            "width": dx,
            "height": dy,
            "points": [[0, 0], [dx, dy]],
            "strokeColor": "#1e1e1e",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "roughness": 1,
            "opacity": 100,
            "angle": 0,
            "groupIds": [],
            "roundness": {"type": 2},
            "isDeleted": False,
            "boundElements": [],
            "locked": False,
            "startBinding": {
                "elementId": src["id"],
                "focus": 0,
                "gap": 4,
            },
            "endBinding": {
                "elementId": dst["id"],
                "focus": 0,
                "gap": 4,
            },
            "startArrowhead": None,
            "endArrowhead": "arrow",
        }

        label_el = None
        if label:
            mid_x = src_cx + dx / 2
            mid_y = src_bottom + dy / 2
            label_el = ExcalidrawDesigner._make_text(
                f"{arrow_id}_label", label,
                mid_x + 10, mid_y,
                font_size=12, color="#666666",
            )

        return arrow, label_el

    # ------------------------------------------------------------------
    # JSON parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json(text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

        logger.warning("Could not parse JSON from LLM diagram design response")
        return {}
