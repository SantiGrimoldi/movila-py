"""Voz del agente. Dos motores, se elige con MOVILA_TTS:

- piper (por defecto): TTS neuronal local con una voz argentina (es_AR-daniela-high). Genera
  oración por oración y empieza a sonar con la primera (~200 ms) mientras sintetiza el resto, así
  el TTS casi no suma al silencio. La primera vez descarga la voz (~115 MB) de Hugging Face.
- say: el de macOS. No descarga nada, pero suena robótico. Queda como respaldo.
"""

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Protocol

TTS_ENGINE = os.environ.get("MOVILA_TTS", "piper")
PIPER_VOICE = os.environ.get("MOVILA_PIPER_VOICE", "es_AR-daniela-high")
SAY_VOICE = os.environ.get("MOVILA_AGENT_VOICE", "Paulina")
VOICES_DIR = Path(".voices")
VOICES_REPO = "rhasspy/piper-voices"


class Playback(Protocol):
    def wait(self) -> None: ...
    def first_audio_ms(self) -> int | None: ...


class Engine(Protocol):
    name: str
    def start(self, text: str) -> Playback: ...


class _Silence:
    def wait(self) -> None:
        pass

    def first_audio_ms(self) -> int | None:
        return None


class _ProcessPlayback:
    def __init__(self, process: subprocess.Popen) -> None:
        self._process = process

    def wait(self) -> None:
        self._process.wait()

    def first_audio_ms(self) -> int | None:
        return None  # `say` no avisa cuándo empieza a sonar


class SayEngine:
    name = "say"

    def __init__(self, voice: str = SAY_VOICE, rate: int = 190) -> None:
        self._voice = voice
        self._rate = rate

    def start(self, text: str) -> Playback:
        return _ProcessPlayback(subprocess.Popen(["say", "-v", self._voice, "-r", str(self._rate), text]))


class _StreamPlayback:
    """Sintetiza y reproduce en otro hilo; cada oración suena apenas está lista."""

    def __init__(self, voice, text: str) -> None:
        self._voice = voice
        self._text = text
        self._started_at = time.perf_counter()
        self._first_audio = threading.Event()
        self._first_audio_ms: int | None = None
        self._error: Exception | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        import sounddevice as sd

        try:
            with sd.OutputStream(samplerate=self._voice.config.sample_rate, channels=1, dtype="int16") as stream:
                for chunk in self._voice.synthesize(self._text):
                    if not self._first_audio.is_set():
                        self._first_audio_ms = round((time.perf_counter() - self._started_at) * 1000)
                        self._first_audio.set()
                    stream.write(chunk.audio_int16_array)
        except Exception as error:  # el audio no debe tirar abajo la conversación; se informa en wait()
            self._error = error
        finally:
            self._first_audio.set()

    def wait(self) -> None:
        self._thread.join()
        if self._error:
            print(f"   ⚠ no se pudo reproducir la voz: {type(self._error).__name__}: {self._error}")
            self._error = None

    def first_audio_ms(self) -> int | None:
        self._first_audio.wait()
        return self._first_audio_ms


def piper_voice_files(name: str) -> tuple[str, str]:
    """`es_AR-daniela-high` → rutas del modelo y su config dentro del repo de voces de Piper."""
    parts = name.split("-")
    if len(parts) != 3 or "_" not in parts[0]:
        raise ValueError(f"nombre de voz de Piper inválido: {name!r} (se espera idioma_REGIÓN-nombre-calidad)")
    locale, speaker, quality = parts
    base = f"{locale.split('_')[0]}/{locale}/{speaker}/{quality}/{name}.onnx"
    return base, f"{base}.json"


class PiperEngine:
    name = "piper"

    def __init__(self, voice) -> None:
        self._voice = voice

    @classmethod
    def load(cls, name: str = PIPER_VOICE, voices_dir: Path = VOICES_DIR) -> "PiperEngine":
        from huggingface_hub import hf_hub_download
        from piper import PiperVoice

        model, config = (hf_hub_download(VOICES_REPO, f, local_dir=voices_dir) for f in piper_voice_files(name))
        return cls(PiperVoice.load(model, config_path=config))

    def start(self, text: str) -> Playback:
        return _StreamPlayback(self._voice, text)


def create_engine(name: str = TTS_ENGINE) -> Engine:
    if name == "say":
        return SayEngine()
    if name != "piper":
        raise ValueError(f"MOVILA_TTS desconocido: {name!r} (opciones: piper, say)")
    try:
        return PiperEngine.load()
    except Exception as error:  # sin red o sin el extra de voz: se sigue con `say` y se avisa
        print(f"⚠ Piper no está disponible ({type(error).__name__}: {error}); uso `say`.")
        return SayEngine()


class Speaker:
    """Habla sin bloquear, y nunca superpone dos frases: cada una espera a la anterior."""

    def __init__(self, engine: Engine | None = None, muted: bool = False) -> None:
        self._engine = engine
        self._muted = muted
        self._current: Playback | None = None

    def say(self, text: str, wait: bool = True) -> Playback:
        self.wait()
        if self._muted or not text or self._engine is None:
            return _Silence()
        self._current = self._engine.start(text)
        playback = self._current
        if wait:
            self.wait()
        return playback

    def play(self, wav: Path) -> None:
        self.wait()
        if not self._muted:
            subprocess.run(["afplay", str(wav)], check=False)

    def wait(self) -> None:
        if self._current:
            self._current.wait()
            self._current = None
