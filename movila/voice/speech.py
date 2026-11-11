"""Audio de entrada, todo local en la Mac (la voz del agente está en tts.py):

- STT: Whisper sobre MLX (corre en el chip Apple). Se usa large-v3-turbo porque small se come
  dígitos ("1199" → "199") y en atención al cliente los números son lo que más importa.
- Cliente simulado: `say` de macOS genera su voz, que después pasa por el STT como un micrófono.
"""

import os
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16_000
STT_MODEL = os.environ.get("MOVILA_STT_MODEL", "mlx-community/whisper-large-v3-turbo")
CALLER_VOICE = os.environ.get("MOVILA_CALLER_VOICE", "Eddy (Spanish (Mexico))")


@dataclass(frozen=True)
class Transcript:
    text: str
    latency_ms: int


def transcribe(audio: np.ndarray, language: str | None = "es") -> Transcript:
    import mlx_whisper  # import diferido: carga MLX solo si se usa la voz

    started = time.perf_counter()
    result = mlx_whisper.transcribe(audio, path_or_hf_repo=STT_MODEL, language=language)
    return Transcript(result["text"].strip(), round((time.perf_counter() - started) * 1000))


def warm_up() -> None:
    """La primera transcripción carga el modelo en memoria (y lo descarga la primera vez)."""
    transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as f:
        if f.getframerate() != SAMPLE_RATE or f.getnchannels() != 1:
            raise ValueError(f"{path}: se espera WAV mono a {SAMPLE_RATE} Hz")
        return np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def synthesize_wav(text: str, voice: str) -> Path:
    """Genera la voz del cliente simulado como WAV, para pasarla por el STT como si fuera un micrófono."""
    path = Path(tempfile.mkstemp(suffix=".wav")[1])
    subprocess.run(["say", "-v", voice, "-o", str(path), f"--data-format=LEI16@{SAMPLE_RATE}", text], check=True)
    return path


def record_push_to_talk() -> np.ndarray:
    import sounddevice as sd

    input("🎙  Enter para hablar…")
    chunks: list[np.ndarray] = []
    stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=lambda data, *_: chunks.append(data.copy()))
    with stream:
        input("   grabando… Enter para terminar")
    return np.concatenate(chunks)[:, 0] if chunks else np.zeros(0, dtype=np.float32)

