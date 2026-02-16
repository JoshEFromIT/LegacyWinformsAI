"""FastAPI application entry point."""

from __future__ import annotations

import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router
from backend.services.analyzer import AnalyzerService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-warm the Ollama model on startup so the first analysis is fast."""
    analyzer = AnalyzerService()
    await analyzer.warm_up()
    yield


app = FastAPI(
    title="RDP Recorder & Diagram Generator",
    description=(
        "Records screen interactions from RDP sessions viewing .NET WinForms "
        "applications with Infragistics controls, then uses a local AI vision model "
        "via Ollama to generate Mermaid diagrams and narrative "
        "documentation. No cloud API keys required."
    ),
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# Serve the frontend
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
