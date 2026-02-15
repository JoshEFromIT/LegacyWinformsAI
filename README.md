# RDP Session Recorder & Diagram Generator (Local AI)

A web application that records screen interactions from RDP sessions viewing .NET WinForms applications (with legacy Infragistics controls and custom components), then uses a **local AI vision model via Ollama** to generate **Mermaid diagrams** and **narrative documentation** of the user's workflow.

**No cloud API keys required** — all AI inference runs locally on your machine using [Ollama](https://ollama.com/) with [llama3.2-vision](https://ollama.com/library/llama3.2-vision).

## What It Does

1. **Capture** — Record screenshots from an RDP session, either via automatic screen capture or manual upload (drag & drop)
2. **Analyze** — A local vision model (llama3.2-vision via Ollama) examines each screenshot to identify WinForms forms, Infragistics controls (`UltraGrid`, `UltraTextEditor`, `UltraComboEditor`, etc.), custom controls, and user actions
3. **Generate** — Produces three types of Mermaid diagrams plus a written narrative:
   - **Flowchart** — Navigation path through forms/screens
   - **Sequence Diagram** — User <-> application interaction timeline
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
│  Screenshots    Ollama API        Mermaid    │
│  (PNG files)   (local LLM)      + Narrative  │
└─────────────────────────────────────────────┘
                       │
              ┌────────▼────────┐
              │     Ollama      │
              │ llama3.2-vision │
              │  (local GPU/CPU)│
              └─────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com/) installed and running
- Sufficient RAM/VRAM for the vision model (recommended: 8GB+ VRAM or 16GB+ RAM)

### 1. Install Ollama

```bash
# Linux
curl -fsSL https://ollama.com/install.sh | sh

# macOS — download from https://ollama.com/download
# Windows — download from https://ollama.com/download
```

### 2. Pull the Vision Model

```bash
ollama pull llama3.2-vision
```

This downloads the llama3.2-vision model (~7.9GB). It is Meta's latest vision-language model and the best option for screenshot analysis tasks via Ollama.

**Alternative models** (if you have hardware constraints):
```bash
ollama pull llava:13b        # Larger, more accurate
ollama pull llava:7b         # Smaller, faster
ollama pull moondream        # Very lightweight (~1.7GB)
```

### 3. Run the Application

```bash
# Clone and enter the project
cd LegacyWinformsAI

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Configure (optional — defaults work out of the box)
cp .env.example .env
# Edit .env if Ollama is running on a different host/port

# Run the application
uvicorn backend.app:app --reload --port 8000
```

Open http://localhost:8000 in your browser. The header will show the Ollama connection status.

### Docker

```bash
cp .env.example .env
docker compose up --build
```

This starts both the web application and an Ollama instance. After startup, pull the model into the Ollama container:

```bash
docker compose exec ollama ollama pull llama3.2-vision
```

To enable **NVIDIA GPU acceleration**, uncomment the GPU section in `docker-compose.yml`:

```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: all
          capabilities: [gpu]
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

Click **Analyze & Generate**. The local vision model will:
- Identify each form/screen in the WinForms application
- Detect Infragistics controls and custom components
- Determine what actions the user took between frames
- Generate Mermaid diagrams and a narrative summary

> **Note:** Analysis speed depends on your hardware. With a GPU, each frame takes ~5-15 seconds. CPU-only inference is slower.

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
| `GET` | `/api/health/ollama` | Check Ollama connection and model status |

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
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API base URL |
| `OLLAMA_MODEL` | `llama3.2-vision` | Vision model to use |
| `OLLAMA_TIMEOUT` | `300` | Request timeout in seconds |
| `SESSIONS_DIR` | `sessions` | Directory for session data |

## Hardware Recommendations

| Setup | VRAM/RAM | Performance |
|-------|----------|-------------|
| NVIDIA GPU (8GB+ VRAM) | 8-12GB VRAM | Best — ~5-15s per frame |
| Apple Silicon (M1/M2/M3) | 16GB+ unified | Good — ~10-30s per frame |
| CPU only | 16GB+ RAM | Functional — ~30-120s per frame |

For CPU-only setups, consider using a smaller model like `moondream` for faster inference.
