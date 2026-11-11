"""El ciclo del agente como grafo de LangGraph.

    start_turn → agent ─┬─(texto / refusal / max_tokens)──→ END
                        └─(tool_use)→ tools ─┬─→ agent
                                             ├─(derivó)────→ handoff → END
                                             └─(límite)────→ give_up → END

Es el mismo ciclo que el agente en TypeScript, pero el estado lo guarda el checkpointer después
de cada nodo: si el proceso se cae, la conversación se retoma desde el último paso.
"""

import operator
import time
from dataclasses import dataclass
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from movila.llm import CallModel
from movila.mock_api import MovilaApi
from movila.policies import MAX_AGENT_ITERATIONS
from movila.prompt import Channel, build_system_prompt
from movila.session import Session
from movila.tools.base import AgentTool, ToolContext
from movila.tools.executor import execute_tool_call
from movila.tools.registry import to_tool_definitions

FALLBACK_REPLIES = {
    "max_iterations": "Perdón, no pude resolverlo. ¿Querés que te comunique con una persona del equipo?",
    "handoff": "Te comunico con una persona del equipo. En breve te atienden.",
    "refusal": "No puedo ayudarte con eso. ¿Querés que te comunique con una persona del equipo?",
    "max_tokens": "Perdón, se me cortó la respuesta. ¿Me repetís la consulta?",
}


def _trace_reducer(current: list[dict] | None, update: list[dict] | None) -> list[dict]:
    """None reinicia el trace (lo hace start_turn); una lista se agrega al final."""
    return [] if update is None else [*(current or []), *update]


class AgentState(TypedDict, total=False):
    messages: Annotated[list[dict], operator.add]
    session: Session
    turn_trace: Annotated[list[dict], _trace_reducer]
    iterations: int
    reply: str
    stop_reason: str | None


@dataclass(frozen=True)
class GraphDeps:
    call_model: CallModel
    api: MovilaApi
    api_key: str
    tools: tuple[AgentTool, ...]
    channel: Channel = "chat"
    max_iterations: int = MAX_AGENT_ITERATIONS


def tool_uses_of(content: list[dict]) -> list[dict]:
    return [b for b in content if b.get("type") == "tool_use"]


def text_of(content: list[dict]) -> str:
    return "\n".join(b["text"] for b in content if b.get("type") == "text").strip()


def build_graph(deps: GraphDeps, checkpointer=None):
    system = build_system_prompt(deps.channel)
    tool_definitions = to_tool_definitions(deps.tools)

    def start_turn(state: AgentState) -> dict:
        # Un mensaje nuevo del cliente = un turno nuevo. Las guardas lo usan para saber
        # si el cliente respondió después de ver una propuesta.
        session = state["session"]
        return {"session": session.update(turn=session.turn + 1), "turn_trace": None, "iterations": 0, "reply": "", "stop_reason": None}

    def agent(state: AgentState) -> dict:
        started = time.perf_counter()
        response = deps.call_model(system, state["messages"], tool_definitions)
        iteration = state["iterations"] + 1
        update: dict = {
            "messages": [{"role": "assistant", "content": response.content}],
            "iterations": iteration,
            "turn_trace": [{
                "type": "model_call", "iteration": iteration, "stop_reason": response.stop_reason,
                "latency_ms": round((time.perf_counter() - started) * 1000), "usage": response.usage,
            }],
        }
        if response.stop_reason in ("refusal", "max_tokens"):
            return {**update, "stop_reason": response.stop_reason, "reply": FALLBACK_REPLIES[response.stop_reason]}
        if not tool_uses_of(response.content):
            return {**update, "stop_reason": "end_turn", "reply": text_of(response.content)}
        return update

    def tools(state: AgentState) -> dict:
        # Ejecuta en orden, pasando la sesión de una tool a la siguiente
        # (una puede depender de lo que cambió la anterior, como la verificación).
        session = state["session"]
        results, events = [], []
        for block in tool_uses_of(state["messages"][-1]["content"]):
            executed = execute_tool_call(block, deps.tools, ToolContext(deps.api, deps.api_key, session))
            session = executed.session
            results.append(executed.result_block)
            events.append({
                "type": "tool_call", "name": block["name"], "input": block.get("input", {}),
                "result": executed.outcome.result, "is_error": executed.outcome.is_error, "latency_ms": executed.latency_ms,
            })
        # Todos los resultados van juntos en UN mensaje de usuario, cada uno con el id de su llamada.
        return {"messages": [{"role": "user", "content": results}], "session": session, "turn_trace": events}

    def finish_with(reason: str):
        return lambda _state: {"stop_reason": reason, "reply": FALLBACK_REPLIES[reason]}

    def after_agent(state: AgentState) -> str:
        return END if state.get("stop_reason") else "tools"

    def after_tools(state: AgentState) -> str:
        if state["session"].ended:
            return "handoff"
        return "give_up" if state["iterations"] >= deps.max_iterations else "agent"

    graph = StateGraph(AgentState)
    graph.add_node("start_turn", start_turn)
    graph.add_node("agent", agent)
    graph.add_node("tools", tools)
    graph.add_node("handoff", finish_with("handoff"))
    graph.add_node("give_up", finish_with("max_iterations"))
    graph.add_edge(START, "start_turn")
    graph.add_edge("start_turn", "agent")
    graph.add_conditional_edges("agent", after_agent, ["tools", END])
    graph.add_conditional_edges("tools", after_tools, ["agent", "handoff", "give_up"])
    graph.add_edge("handoff", END)
    graph.add_edge("give_up", END)
    return graph.compile(checkpointer=checkpointer)
