"""Mermaid diagram and narrative generation from analyzed screenshots.

Converts a sequence of ScreenAnalysis results into:
1. Flowchart — shows the user's navigation path through forms/screens
2. Sequence diagram — shows user<->application interaction over time
3. State diagram — shows form/screen state transitions
4. Narrative — a readable story of what the user did
5. Excalidraw scenes — hand-drawn style diagrams via the Excalidraw MCP canvas server
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.models.schemas import FlowStep, ScreenAnalysis, SessionResult
from backend.services.excalidraw_service import ExcalidrawService

logger = logging.getLogger(__name__)


class DiagramGenerator:
    """Generates Mermaid diagrams and narrative text from analysis results."""

    def __init__(self, excalidraw: Optional[ExcalidrawService] = None) -> None:
        self.excalidraw = excalidraw or ExcalidrawService()

    def generate(
        self,
        session_id: str,
        analyses: list[ScreenAnalysis],
        title: str = "",
    ) -> SessionResult:
        flow_steps = self._build_flow_steps(analyses)
        narrative = self._build_narrative(analyses, flow_steps)
        flowchart = self._build_flowchart(flow_steps)
        sequence = self._build_sequence_diagram(analyses)
        state = self._build_state_diagram(analyses)

        return SessionResult(
            session_id=session_id,
            title=title or self._infer_title(analyses),
            narrative=narrative,
            mermaid_flowchart=flowchart,
            mermaid_sequence=sequence,
            mermaid_state=state,
            flow_steps=flow_steps,
            total_captures=len(analyses),
        )

    async def generate_with_excalidraw(
        self,
        session_id: str,
        analyses: list[ScreenAnalysis],
        title: str = "",
    ) -> SessionResult:
        """Generate Mermaid diagrams and convert them to Excalidraw scenes."""
        result = self.generate(session_id, analyses, title)

        try:
            excalidraw_scenes = await self.excalidraw.convert_mermaid_to_excalidraw(
                mermaid_flowchart=result.mermaid_flowchart,
                mermaid_sequence=result.mermaid_sequence,
                mermaid_state=result.mermaid_state,
                session_id=session_id,
            )
            result.excalidraw_flowchart = excalidraw_scenes.get("flowchart")
            result.excalidraw_sequence = excalidraw_scenes.get("sequence")
            result.excalidraw_state = excalidraw_scenes.get("state")
        except Exception:
            logger.exception(
                "Excalidraw conversion failed for session %s — Mermaid diagrams are still available",
                session_id,
            )

        return result

    def _build_flow_steps(self, analyses: list[ScreenAnalysis]) -> list[FlowStep]:
        """Collapse consecutive frames on the same form into flow steps."""
        steps: list[FlowStep] = []
        current_form = ""
        step_num = 0

        for a in analyses:
            form = a.detected_form or a.window_title or "Unknown Screen"
            if form != current_form:
                step_num += 1
                current_form = form
                action_summary = a.narrative_fragment or "Navigated to this screen"
                controls = [c.control_type for c in a.controls[:5]]
                steps.append(FlowStep(
                    step_number=step_num,
                    form_name=form,
                    action_summary=action_summary,
                    capture_ids=[a.capture_id],
                    controls_involved=controls,
                ))
            else:
                if steps:
                    steps[-1].capture_ids.append(a.capture_id)
                    if a.narrative_fragment:
                        steps[-1].action_summary += f"; {a.narrative_fragment}"
                    for c in a.controls[:3]:
                        if c.control_type not in steps[-1].controls_involved:
                            steps[-1].controls_involved.append(c.control_type)

        return steps

    def _build_narrative(
        self,
        analyses: list[ScreenAnalysis],
        flow_steps: list[FlowStep],
    ) -> str:
        """Build a human-readable narrative of the user session."""
        if not analyses:
            return "No screenshots were captured in this session."

        paragraphs: list[str] = []

        paragraphs.append(
            "## Session Narrative\n\n"
            "This document describes the user's interaction with a legacy .NET WinForms "
            "application as observed during an RDP recording session.\n"
        )

        for step in flow_steps:
            infra_controls = []
            custom_controls = []
            for a in analyses:
                if a.capture_id in step.capture_ids:
                    for c in a.controls:
                        if c.is_infragistics and c.control_type not in infra_controls:
                            infra_controls.append(c.control_type)
                        if c.is_custom and c.control_type not in custom_controls:
                            custom_controls.append(c.control_type)

            p = f"### Step {step.step_number}: {step.form_name}\n\n"
            p += f"{step.action_summary}\n\n"

            if infra_controls:
                p += f"**Infragistics Controls**: {', '.join(infra_controls)}\n\n"
            if custom_controls:
                p += f"**Custom Controls**: {', '.join(custom_controls)}\n\n"

            frame_count = len(step.capture_ids)
            p += f"*({frame_count} frame{'s' if frame_count != 1 else ''} captured on this screen)*\n"

            paragraphs.append(p)

        # Add detail section with per-frame narratives
        paragraphs.append("## Detailed Frame-by-Frame Log\n")
        for i, a in enumerate(analyses, 1):
            line = f"{i}. "
            if a.detected_form:
                line += f"**[{a.detected_form}]** "
            line += a.narrative_fragment or a.raw_description[:200] or "[No description]"
            paragraphs.append(line)

        return "\n\n".join(paragraphs)

    def _build_flowchart(self, flow_steps: list[FlowStep]) -> str:
        """Build a Mermaid flowchart showing navigation between screens."""
        if not flow_steps:
            return "flowchart TD\n    A[No data captured]"

        lines = ["flowchart TD"]

        for i, step in enumerate(flow_steps):
            node_id = f"S{step.step_number}"
            label = self._escape_mermaid(step.form_name)
            controls_hint = ""
            if step.controls_involved:
                top_controls = step.controls_involved[:3]
                controls_hint = "<br/>" + "<br/>".join(
                    self._escape_mermaid(c) for c in top_controls
                )
            lines.append(f"    {node_id}[\"{label}{controls_hint}\"]")

        for i in range(len(flow_steps) - 1):
            src = f"S{flow_steps[i].step_number}"
            dst = f"S{flow_steps[i + 1].step_number}"
            # Summarize the transition action
            action = flow_steps[i + 1].action_summary.split(";")[0][:60]
            action = self._escape_mermaid(action)
            lines.append(f"    {src} -->|\"{action}\"| {dst}")

        # Style the first and last nodes
        if flow_steps:
            lines.append(f"    style S{flow_steps[0].step_number} fill:#4CAF50,color:#fff")
        if len(flow_steps) > 1:
            lines.append(f"    style S{flow_steps[-1].step_number} fill:#2196F3,color:#fff")

        return "\n".join(lines)

    def _build_sequence_diagram(self, analyses: list[ScreenAnalysis]) -> str:
        """Build a Mermaid sequence diagram showing user<->app interactions."""
        if not analyses:
            return "sequenceDiagram\n    Note over User,App: No data captured"

        lines = [
            "sequenceDiagram",
            "    participant User",
            "    participant App as WinForms Application",
        ]

        # Add participants for distinct forms
        forms_seen: list[str] = []
        for a in analyses:
            form = a.detected_form or "Unknown"
            if form not in forms_seen:
                forms_seen.append(form)

        for form in forms_seen:
            safe = self._safe_participant(form)
            lines.append(f"    participant {safe} as {self._escape_mermaid(form)}")

        prev_form = ""
        for a in analyses:
            form = a.detected_form or "Unknown"
            safe_form = self._safe_participant(form)

            if form != prev_form:
                lines.append(
                    f"    User->>App: Navigate to {self._escape_mermaid(form)}"
                )
                lines.append(
                    f"    App->>{safe_form}: Display form"
                )
                prev_form = form

            for action in a.actions_since_previous:
                desc = self._escape_mermaid(action.description[:80]) or action.action_type
                target = ""
                if action.target_control:
                    target = f" on {self._escape_mermaid(action.target_control.label or action.target_control.control_type)}"
                lines.append(
                    f"    User->>{safe_form}: {desc}{target}"
                )

            if a.narrative_fragment and not a.actions_since_previous:
                lines.append(
                    f"    Note over User,{safe_form}: {self._escape_mermaid(a.narrative_fragment[:80])}"
                )

        return "\n".join(lines)

    def _build_state_diagram(self, analyses: list[ScreenAnalysis]) -> str:
        """Build a Mermaid state diagram showing screen state transitions."""
        if not analyses:
            return "stateDiagram-v2\n    [*] --> NoData"

        lines = ["stateDiagram-v2"]
        states_seen: set[str] = set()
        transitions: list[tuple[str, str, str]] = []

        prev_state = "[*]"
        for a in analyses:
            state = self._safe_state(a.detected_form or a.window_title or "Unknown")
            if state not in states_seen:
                states_seen.add(state)
                label = a.detected_form or a.window_title or "Unknown"
                lines.append(f"    {state} : {self._escape_mermaid(label)}")

            if prev_state != state:
                action = ""
                if a.actions_since_previous:
                    action = a.actions_since_previous[0].description[:50]
                transitions.append((prev_state, state, action))

            prev_state = state

        # Final state
        if prev_state != "[*]":
            transitions.append((prev_state, "[*]", "Session end"))

        for src, dst, label in transitions:
            if label:
                lines.append(f"    {src} --> {dst} : {self._escape_mermaid(label)}")
            else:
                lines.append(f"    {src} --> {dst}")

        return "\n".join(lines)

    def _infer_title(self, analyses: list[ScreenAnalysis]) -> str:
        """Infer a session title from the analyzed data."""
        forms = []
        for a in analyses:
            if a.detected_form and a.detected_form not in forms:
                forms.append(a.detected_form)
        if forms:
            return f"User Session: {' → '.join(forms[:4])}"
        return "RDP Recording Session"

    @staticmethod
    def _escape_mermaid(text: str) -> str:
        """Escape special characters for Mermaid labels."""
        return (
            text.replace('"', "'")
            .replace("<", "‹")
            .replace(">", "›")
            .replace("&", "+")
            .replace("\n", " ")
        )

    @staticmethod
    def _safe_participant(name: str) -> str:
        """Convert a form name to a safe Mermaid participant ID."""
        safe = "".join(c if c.isalnum() else "_" for c in name)
        return safe[:30] or "Unknown"

    @staticmethod
    def _safe_state(name: str) -> str:
        """Convert a form name to a safe Mermaid state ID."""
        safe = "".join(c if c.isalnum() else "_" for c in name)
        return safe[:30] or "Unknown"
