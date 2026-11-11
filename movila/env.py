"""Carga el .env del proyecto (o el del agente en TypeScript, que ya tiene la key)."""

from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent


def load_env() -> None:
    for candidate in (_ROOT / ".env", _ROOT.parent / "movila" / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)
