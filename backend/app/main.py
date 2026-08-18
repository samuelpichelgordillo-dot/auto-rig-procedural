"""FastAPI app entrypoint. Módulo 0: solo health-check, sin lógica de negocio."""
from fastapi import FastAPI

app = FastAPI(title="Auto-Rig & Animación Procedural")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
