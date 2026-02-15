"""FastAPI application entry point."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(
    title="RDP Recorder & Diagram Generator",
    description=(
        "Records screen interactions from RDP sessions viewing .NET WinForms "
        "applications with Infragistics controls, then uses AI vision to generate "
        "Mermaid diagrams and narrative documentation."
    ),
    version="1.0.0",
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
