import json
import sys
from pathlib import Path

# Evita __pycache__ dentro de lab/backend/ (Terraform zipea esa carpeta completa).
sys.dont_write_bytecode = True

import pytest  # noqa: E402
from functions_framework import create_app  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1] / "backend"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("FAILURE_RATE", "0")
    monkeypatch.setenv("EXTRA_LATENCY_MS", "0")
    app = create_app(target="handle", source=str(BACKEND / "main.py"))
    return app.test_client()


@pytest.fixture
def last_log(capsys):
    """Devuelve la última línea JSON escrita en stdout por el backend."""
    def _read():
        lines = [l for l in capsys.readouterr().out.splitlines() if l.startswith("{")]
        assert lines, "el backend no escribió ninguna línea JSON"
        return json.loads(lines[-1])
    return _read
