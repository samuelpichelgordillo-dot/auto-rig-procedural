"""Módulo 0: verifica que Blender headless responde correctamente."""
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


def test_health_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_blender_headless_responds() -> None:
    blender_exe = shutil.which("blender")
    assert blender_exe is not None, "blender no está en el PATH"

    result = subprocess.run(
        [blender_exe, "--background", "--version"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
    assert "Blender" in result.stdout
