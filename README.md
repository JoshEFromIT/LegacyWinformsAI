# RDP Session Recorder & Diagram Generator (Local AI)

A web application that records screen interactions from RDP sessions viewing .NET WinForms applications (with legacy Infragistics controls and custom components), then uses a **local AI model via Ollama** to generate **Mermaid diagrams** and **narrative documentation** of the user's workflow.

**No cloud API keys required** — all AI inference runs locally on your machine using [Ollama](https://ollama.com/). Supports both pre-built Ollama models and **custom GGUF files**.

## What It Does

1. **Capture** — Record screenshots from an RDP session, either via automatic screen capture or manual upload (drag & drop)
2. **Analyze** — A local model via Ollama examines each screenshot to identify WinForms forms, Infragistics controls (`UltraGrid`, `UltraTextEditor`, `UltraComboEditor`, etc.), custom controls, and user actions
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
              │  Custom .gguf   │
              │  or pulled model│
              │  (local GPU/CPU)│
              └─────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com/) installed and running
- A model — either pull one from Ollama or use your own `.gguf` file

### 1. Install Ollama

```bash
# Linux
curl -fsSL https://ollama.com/install.sh | sh

# macOS — download from https://ollama.com/download
# Windows — download from https://ollama.com/download
```

### 2. Get a Model

**Option A — Pull a pre-built model:**
```bash
ollama pull llama3.2-vision
```

**Option B — Use your own GGUF file:**
```bash
# Just drop the .gguf file into the models/ directory
cp /path/to/your-model.gguf models/
```

The app auto-detects `.gguf` files in `models/` and registers them with Ollama on first use.

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

# Run the application
uvicorn backend.app:app --reload --port 8000
```

Open http://localhost:8000 in your browser. The header will show the Ollama connection status and GGUF detection status.

### Docker

```bash
cp .env.example .env
docker compose up --build
```

This starts both the web application and an Ollama instance. The `models/` directory is mounted into both containers.

**To use a pre-built model:**
```bash
docker compose exec ollama ollama pull llama3.2-vision
```

**To use a GGUF file:**
```bash
# Just place the .gguf in the models/ directory — it's auto-detected
cp /path/to/your-model.gguf models/
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

## Using GGUF Models

GGUF is the standard format for quantized LLM weights used by llama.cpp and Ollama. You can use any `.gguf` file with this application.

### Simple Usage (Auto-Detection)

1. Place your `.gguf` file in the `models/` directory
2. Start the app — it detects the file and registers it with Ollama automatically
3. The model name is derived from the filename (e.g., `openai_gpt-oss-20b-Q8_0.gguf` becomes `openai_gpt-oss-20b-q8_0`)

### Explicit Configuration

Set these in `.env` for full control:

```bash
# Point to a specific GGUF file
OLLAMA_GGUF_PATH=models/openai_gpt-oss-20b-Q8_0.gguf

# Custom name for the model in Ollama
OLLAMA_GGUF_MODEL_NAME=gpt-oss-20b

# For vision GGUF models, also provide the projector file
OLLAMA_GGUF_PROJECTOR_PATH=models/mmproj-model.gguf
```

### Vision vs. Text-Only Models

For **screenshot analysis** (the primary use case), you need a **vision-capable** model that can process images. If your GGUF is a text-only model (like `openai_gpt-oss-20b-Q8_0.gguf`), the image data will be sent but the model may not be able to interpret it visually.

**Vision-capable GGUF models:**
- LLaVA 1.5/1.6 (requires both base `.gguf` + `mmproj-*.gguf` projector)
- llama3.2-vision GGUF variants
- MoonDream GGUF variants

**Text-only GGUF models** (work but without image understanding):
- GPT-OSS, Mistral, Qwen, LLaMA text-only variants

### Multiple GGUF Files

If you have multiple `.gguf` files in `models/`, set `OLLAMA_GGUF_PATH` to choose which one to use. Otherwise the app logs a warning and falls back to the `OLLAMA_MODEL` setting.

### Manual Registration via API

You can also register a GGUF model at any time via the API:

```bash
curl -X POST http://localhost:8000/api/models/register-gguf
```

Or click the "Click to register GGUF" link in the status bar in the web UI.

## Usage

### 1. Create a Session

Click **Create Session** with an optional name and RDP host details.

### 2. Capture Screenshots

**Option A — Manual Upload:**
Drag and drop screenshots of your RDP session into the upload zone.

**Option B — Auto-Capture:**
Click **Start Auto-Capture** to grab screenshots at regular intervals.

### 3. Analyze & Generate

Click **Analyze & Generate**. The local model will:
- Identify each form/screen in the WinForms application
- Detect Infragistics controls and custom components
- Determine what actions the user took between frames
- Generate Mermaid diagrams and a narrative summary

> **Note:** Analysis speed depends on your hardware and model size.

### 4. View Results

Switch between tabs to see:
- **Flowchart** — Visual navigation map
- **Sequence Diagram** — Interaction timeline
- **State Diagram** — Screen transitions
- **Narrative** — Written documentation
- **Raw Mermaid** — Copy-paste ready Mermaid code

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
| `GET` | `/api/health/ollama` | Check Ollama connection, model, and GGUF status |
| `POST` | `/api/models/register-gguf` | Register a GGUF model with Ollama |

## Configuration

Set these in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API base URL |
| `OLLAMA_MODEL` | `llama3.2-vision` | Model name (overridden when using GGUF) |
| `OLLAMA_TIMEOUT` | `300` | Request timeout in seconds |
| `OLLAMA_GGUF_PATH` | *(empty)* | Path to a `.gguf` file (auto-detected from `models/`) |
| `OLLAMA_GGUF_MODEL_NAME` | *(empty)* | Custom Ollama model name for the GGUF |
| `OLLAMA_GGUF_PROJECTOR_PATH` | *(empty)* | Path to vision projector `.gguf` (auto-detected) |
| `MODELS_DIR` | `models` | Directory for `.gguf` model files |
| `SESSIONS_DIR` | `sessions` | Directory for session data |

## Hardware Recommendations

| Setup | VRAM/RAM | Performance |
|-------|----------|-------------|
| NVIDIA GPU (8GB+ VRAM) | 8-12GB VRAM | Best — ~5-15s per frame |
| Apple Silicon (M1/M2/M3) | 16GB+ unified | Good — ~10-30s per frame |
| CPU only | 16GB+ RAM | Functional — ~30-120s per frame |

Larger quantized models (Q8_0) need more memory but produce better results. Smaller quantizations (Q4_K_M, Q5_K_M) are faster and lighter.
