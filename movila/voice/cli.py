"""Agente por voz: micrófono → Whisper → agente (LangGraph) → Piper (o `say`).

    uv run movila-voice                      → hablás vos (push-to-talk con Enter)
    uv run movila-voice --keyboard           → escribís, el agente responde hablando
    uv run movila-voice --simulate sin-senal → llamada simulada con una voz sintética
    uv run movila-voice --simulate all --mute
    MOVILA_TTS=say uv run movila-voice       → voz de macOS en lugar de Piper

Mide la latencia de cada etapa: en voz, el silencio después de que el cliente termina de
hablar es lo que se siente. Si el modelo va a usar tools, dice una frase de espera.
"""

import argparse
import uuid
from dataclasses import dataclass

from movila import durable
from movila.agent import MovilaAgent
from movila.cli import build_agent
from movila.voice import speech, tts
from movila.voice.calls import CALLS

FILLER = "Dame un segundo que lo reviso."


@dataclass(frozen=True)
class Heard:
    text: str
    stt_ms: int = 0


class VoiceSession:
    def __init__(self, agent: MovilaAgent, speaker: tts.Speaker) -> None:
        self._agent = agent
        self._speaker = speaker
        self.thread_id = str(uuid.uuid4())

    def respond(self, heard: Heard) -> bool:
        """Un turno de voz. Devuelve False si la conversación terminó."""
        print(f"\ncliente> {heard.text}")
        filler = {"said": False}

        def on_tools_started(names: list[str]) -> None:
            print(f"   ⚙ {', '.join(names)}")
            if not filler["said"]:
                filler["said"] = True
                self._speaker.say(FILLER, wait=False)

        result = self._agent.send(self.thread_id, heard.text, on_tools_started=on_tools_started)
        print(f"movila>  {result.reply}")
        playback = self._speaker.say(result.reply, wait=False)
        tts_ms = playback.first_audio_ms()
        model_calls = sum(1 for e in result.trace if e["type"] == "model_call")
        silence_ms = heard.stt_ms + result.latency_ms + (tts_ms or 0)
        print(f"   ⏱ stt {heard.stt_ms} ms · agente {result.latency_ms} ms ({model_calls} llamadas al modelo)"
              + (f" · tts {tts_ms} ms hasta el primer audio" if tts_ms is not None else "")
              + f" · silencio hasta la respuesta {silence_ms} ms"
              + (" (cubierto con frase de espera)" if filler["said"] else ""))
        self._speaker.wait()
        return not result.session.ended


def hear_from_mic() -> Heard:
    transcript = speech.transcribe(speech.record_push_to_talk())
    return Heard(transcript.text, transcript.latency_ms)


def simulate(agent: MovilaAgent, speaker: tts.Speaker, call_id: str) -> None:
    print(f"\n══ llamada simulada: {call_id} ══")
    session = VoiceSession(agent, speaker)
    for line in CALLS[call_id]:
        wav = speech.synthesize_wav(line, speech.CALLER_VOICE)
        speaker.play(wav)  # se escucha al cliente, como en una llamada
        transcript = speech.transcribe(speech.read_wav(wav))
        wav.unlink(missing_ok=True)
        if not session.respond(Heard(transcript.text, transcript.latency_ms)):
            print("   ↪ derivada a una persona")
            break


def main() -> None:
    parser = argparse.ArgumentParser(description="Agente Movila por voz")
    parser.add_argument("--keyboard", action="store_true", help="escribir en lugar de hablar")
    parser.add_argument("--simulate", choices=[*CALLS, "all"], help="correr una llamada simulada")
    parser.add_argument("--mute", action="store_true", help="no reproducir audio (solo texto y latencias)")
    args = parser.parse_args()

    agent = build_agent(channel="voice")
    speaker = tts.Speaker(None if args.mute else tts.create_engine(), muted=args.mute)
    try:
        if not args.keyboard:
            print("Cargando Whisper…")
            speech.warm_up()
        if args.simulate:
            for call_id in CALLS if args.simulate == "all" else [args.simulate]:
                simulate(agent, speaker, call_id)
            return

        session = VoiceSession(agent, speaker)
        print(f"Movila por voz · conversación {session.thread_id} · Ctrl+C para cortar")
        while True:
            heard = Heard(input("vos> ").strip()) if args.keyboard else hear_from_mic()
            if heard.text and not session.respond(heard):
                break
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        speaker.wait()
        durable.shutdown()


if __name__ == "__main__":
    main()
