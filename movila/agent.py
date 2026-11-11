"""Fachada del agente: un turno de conversación = una corrida del grafo sobre un thread.

El thread_id es la conversación: el checkpointer guarda mensajes y sesión entre turnos.
"""

import json
import logging
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver

from movila import durable
from movila.graph import GraphDeps, build_graph, tool_uses_of
from movila.llm import CallModel
from movila.mock_api import MovilaApi
from movila.prompt import Channel
from movila.session import Session
from movila.tools.registry import MOVILA_TOOLS

log = logging.getLogger(__name__)

# Se llama con los nombres de las tools que el modelo está por ejecutar (la voz lo usa para
# decir "dame un segundo" en lugar de quedarse en silencio).
OnToolsStarted = Callable[[list[str]], None]

# El checkpointer solo reconstruye los tipos que declaramos: un checkpoint manipulado
# no puede instanciar clases arbitrarias al deserializarse.
_CHECKPOINT_TYPES = [("movila.session", name) for name in ("Session", "VerifiedCustomer", "PendingPlanChange", "CompletedPlanChange")]


def checkpoint_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=_CHECKPOINT_TYPES)


def sqlite_checkpointer(path: Path) -> SqliteSaver:
    path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False), serde=checkpoint_serde())


@dataclass(frozen=True)
class TurnResult:
    reply: str
    stop_reason: str
    session: Session
    trace: list[dict]
    latency_ms: int


class MovilaAgent:
    def __init__(
        self,
        call_model: CallModel,
        api: MovilaApi | None = None,
        api_key: str = "default",
        channel: Channel = "chat",
        checkpointer=None,
        log_dir: Path | None = Path("logs"),
    ) -> None:
        self.api = api or MovilaApi()
        durable.register_api(api_key, self.api)
        deps = GraphDeps(call_model=call_model, api=self.api, api_key=api_key, tools=MOVILA_TOOLS, channel=channel)
        self._graph = build_graph(deps, checkpointer or InMemorySaver(serde=checkpoint_serde()))
        self._log_dir = log_dir

    def session(self, thread_id: str) -> Session | None:
        return self._graph.get_state(self._config(thread_id)).values.get("session")

    def send(self, thread_id: str, text: str, on_tools_started: OnToolsStarted | None = None) -> TurnResult:
        started = time.perf_counter()
        config = self._config(thread_id)
        turn_input: dict = {"messages": [{"role": "user", "content": text}]}
        if self.session(thread_id) is None:
            turn_input["session"] = Session(conversation_id=thread_id)

        for update in self._graph.stream(turn_input, config, stream_mode="updates"):
            agent_update = update.get("agent")
            if on_tools_started and agent_update:
                names = [b["name"] for b in tool_uses_of(agent_update["messages"][-1]["content"])]
                if names:
                    on_tools_started(names)

        state = self._graph.get_state(config).values
        result = TurnResult(
            reply=state["reply"],
            stop_reason=state["stop_reason"],
            session=state["session"],
            trace=state["turn_trace"],
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
        self._log(thread_id, text, result)
        return result

    @staticmethod
    def _config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    def _log(self, thread_id: str, text: str, result: TurnResult) -> None:
        """Un JSONL por conversación: mensajes, tools, argumentos, resultados y latencias."""
        if self._log_dir is None:
            return
        try:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            lines = [
                {"type": "user", "text": text},
                *result.trace,
                {"type": "reply", "text": result.reply, "stop_reason": result.stop_reason, "latency_ms": result.latency_ms},
            ]
            with (self._log_dir / f"{thread_id}.jsonl").open("a", encoding="utf-8") as f:
                f.writelines(json.dumps(line, ensure_ascii=False, default=str) + "\n" for line in lines)
        except OSError:
            log.exception("No se pudo escribir el log de la conversación %s", thread_id)
