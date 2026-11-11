import pytest

from movila.voice import tts


class FakePlayback:
    def __init__(self, log: list[str], text: str) -> None:
        self._log = log
        self._text = text

    def wait(self) -> None:
        self._log.append(f"fin:{self._text}")

    def first_audio_ms(self) -> int | None:
        return 42


class FakeEngine:
    name = "fake"

    def __init__(self) -> None:
        self.log: list[str] = []

    def start(self, text: str) -> FakePlayback:
        self.log.append(f"inicio:{text}")
        return FakePlayback(self.log, text)


def test_piper_voice_files_map_name_to_repo_paths():
    assert tts.piper_voice_files("es_AR-daniela-high") == (
        "es/es_AR/daniela/high/es_AR-daniela-high.onnx",
        "es/es_AR/daniela/high/es_AR-daniela-high.onnx.json",
    )


@pytest.mark.parametrize("name", ["daniela", "es-daniela-high", "es_AR-daniela"])
def test_piper_voice_files_reject_malformed_names(name):
    with pytest.raises(ValueError):
        tts.piper_voice_files(name)


def test_create_engine_say_and_unknown():
    assert isinstance(tts.create_engine("say"), tts.SayEngine)
    with pytest.raises(ValueError):
        tts.create_engine("elevenlabs")


def test_speaker_never_overlaps_phrases():
    engine = FakeEngine()
    speaker = tts.Speaker(engine)
    speaker.say("espera", wait=False)
    playback = speaker.say("respuesta", wait=False)
    assert playback.first_audio_ms() == 42
    speaker.wait()
    assert engine.log == ["inicio:espera", "fin:espera", "inicio:respuesta", "fin:respuesta"]


def test_muted_speaker_does_not_synthesize():
    engine = FakeEngine()
    playback = tts.Speaker(engine, muted=True).say("hola")
    assert engine.log == []
    assert playback.first_audio_ms() is None
