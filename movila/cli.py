"""REPL de texto.

    uv run movila                    → conversación nueva
    uv run movila --thread <id>      → retoma una conversación (el estado vive en SQLite)
"""

import argparse
import sys
import uuid
from pathlib import Path

import anthropic

from movila import durable
from movila.agent import MovilaAgent, sqlite_checkpointer
from movila.env import load_env
from movila.llm import create_anthropic_model

CHECKPOINT_DB = Path(".dbos/conversations.sqlite")


def build_agent(channel: str = "chat") -> MovilaAgent:
    load_env()
    durable.launch()
    return MovilaAgent(create_anthropic_model(), channel=channel, checkpointer=sqlite_checkpointer(CHECKPOINT_DB))


def main() -> None:
    parser = argparse.ArgumentParser(description="Agente Movila por terminal")
    parser.add_argument("--thread", help="id de una conversación para retomarla")
    args = parser.parse_args()

    agent = build_agent()
    thread_id = args.thread or str(uuid.uuid4())
    print(f"Movila · conversación {thread_id}\nEscribí \"salir\" para terminar.\n")
    try:
        for line in sys.stdin if not sys.stdin.isatty() else iter(lambda: input("vos> "), None):
            text = line.strip()
            if text == "salir":
                break
            if not text:
                continue
            try:
                result = agent.send(thread_id, text)
            except anthropic.APIError as error:
                # Errores no recuperables del proveedor (credenciales, 400). Los 429/5xx ya los reintentó el SDK.
                print(f"[error] {type(error).__name__}: {error}", file=sys.stderr)
                print("movila> Tuvimos un problema técnico. Probá de nuevo en un momento.\n")
                continue
            print(f"movila> {result.reply}\n")
            if result.session.ended:
                break
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        durable.shutdown()


if __name__ == "__main__":
    main()
