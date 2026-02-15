# RDP Session Recorder & Diagram Generator

A web application that records screen interactions from RDP sessions viewing .NET WinForms applications (with legacy Infragistics controls and custom components), then uses AI vision models to generate **Mermaid diagrams** and **narrative documentation** of the user's workflow.

## What It Does

1. **Capture** — Record screenshots from an RDP session, either via automatic screen capture or manual upload (drag & drop)
2. **Analyze** — AI vision models (Claude or GPT-4o) examine each screenshot to identify WinForms forms, Infragistics controls (`UltraGrid`, `UltraTextEditor`, `UltraComboEditor`, etc.), custom controls, and user actions
3. **Generate** — Produces three types of Mermaid diagrams plus a written narrative:
   - **Flowchart** — Navigation path through forms/screens
   - **Sequence Diagram** — User ↔ application interaction timeline
   - **State Diagram** — Screen state transitions
   - **Narrative** — Human-readable documentation of the session

## Architecture

```
┌─────────────────────────────────────────────┐
│                Web Frontend                  │
│   (HTML/CSS/JS + Mermaid.js rendering)      │
└──────────────────┬──────────────────────────┘
                   │ REST API
┌──────────────────▼──────────────────────────┐
│              FastAPI Backend                  │
│                                              │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐ │
│  │ Capture   │  │ Analyzer │  │ Diagram   │ │
│  │ Service   │  │ Service  │  │ Generator │ │
│  └──────────┘  └──────────┘  └───────────┘ │
│       │              │                       │
│  Screenshots    AI Vision API     Mermaid    │
│  (PNG files)   (Claude/GPT-4o)   + Narrative │
└─────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.10+
- An API key for either [Anthropic Claude](https://console.anthropic.com/) or [OpenAI](https://platform.openai.com/)

### Setup

```bash
# Clone and enter the project
cd LegacyWinformsAI

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Configure API keys
cp .env.example .env
# Edit .env with your API key

# Run the application
uvicorn backend.app:app --reload --port 8000
```

Open http://localhost:8000 in your browser.

### Docker

```bash
cp .env.example .env
# Edit .env with your API key
docker compose up --build
```

## Usage

### 1. Create a Session

Click **Create Session** with an optional name and RDP host details.

### 2. Capture Screenshots

**Option A — Manual Upload:**
Drag and drop screenshots of your RDP session into the upload zone. This works well when the RDP client runs on a different machine.

**Option B — Auto-Capture:**
If the application runs on the same machine as the RDP client, click **Start Auto-Capture** to grab screenshots at regular intervals.

### 3. Analyze & Generate

Click **Analyze & Generate**. The AI vision model will:
- Identify each form/screen in the WinForms application
- Detect Infragistics controls and custom components
- Determine what actions the user took between frames
- Generate Mermaid diagrams and a narrative summary

### 4. View Results

Switch between tabs to see:
- **Flowchart** — Visual navigation map
- **Sequence Diagram** — Interaction timeline
- **State Diagram** — Screen transitions
- **Narrative** — Written documentation
- **Raw Mermaid** — Copy-paste ready Mermaid code for your own docs

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/sessions` | Create a new session |
| `GET` | `/api/sessions` | List all sessions |
| `GET` | `/api/sessions/{id}` | Get session details |
| `DELETE` | `/api/sessions/{id}` | Delete a session |
| `POST` | `/api/sessions/{id}/start` | Start auto-capture |
| `POST` | `/api/sessions/{id}/stop` | Stop auto-capture |
| `POST` | `/api/sessions/{id}/frames` | Upload a screenshot (multipart) |
| `POST` | `/api/sessions/{id}/frames/base64` | Upload a screenshot (base64) |
| `POST` | `/api/sessions/{id}/analyze` | Run AI analysis and generate diagrams |
| `GET` | `/api/sessions/{id}/result` | Get analysis results |
| `GET` | `/api/sessions/{id}/captures/{cid}/image` | Get a capture image |

## Recognized Infragistics Controls

The AI analyzer is specifically trained to identify:

- `UltraGrid` / `UltraWinGrid`
- `UltraTextEditor`
- `UltraComboEditor`
- `UltraDateTimeEditor`
- `UltraToolbarsManager`
- `UltraDockManager`
- `UltraTabControl` / `UltraTabStripControl`
- `UltraTree`
- `UltraStatusBar`
- `UltraMessageBox`
- Custom/composite controls

## Configuration

Set these in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_PROVIDER` | `anthropic` | `anthropic` or `openai` |
| `ANTHROPIC_API_KEY` | — | Your Anthropic API key |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Claude model to use |
| `OPENAI_API_KEY` | — | Your OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o` | OpenAI model to use |
| `SESSIONS_DIR` | `sessions` | Directory for session data |
