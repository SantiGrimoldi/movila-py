"""Ejecuta UNA llamada a tool pedida por el modelo: busca la tool → valida la entrada →
la ejecuta → arma el tool_result. Nunca lanza: cualquier problema vuelve al modelo como
error para que pueda corregirse o avisarle al cliente."""

import json
import logging
import time
from dataclasses import dataclass

from pydantic import ValidationError

from movila.mock_api import MovilaApiError
from movila.session import Session
from movila.tools.base import AgentTool, ToolContext, ToolOutcome, tool_error

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutedTool:
    result_block: dict
    outcome: ToolOutcome
    session: Session
    latency_ms: int


def _run_safely(tool: AgentTool, raw_input: object, ctx: ToolContext) -> ToolOutcome:
    try:
        data = tool.input_model.model_validate(raw_input)
    except ValidationError as error:
        issues = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors())
        return tool_error("invalid_input", issues)
    try:
        return tool.run(data, ctx)
    except MovilaApiError as error:
        return tool_error(error.code, str(error))
    except Exception:
        log.exception("La tool %s falló de forma inesperada", tool.name)
        return tool_error("internal_error", "La herramienta falló de forma inesperada")


def execute_tool_call(block: dict, tools: tuple[AgentTool, ...], ctx: ToolContext) -> ExecutedTool:
    started = time.perf_counter()
    tool = next((t for t in tools if t.name == block["name"]), None)
    outcome = _run_safely(tool, block.get("input", {}), ctx) if tool else tool_error("unknown_tool", f"No existe la herramienta {block['name']}")
    result_block = {
        "type": "tool_result",
        "tool_use_id": block["id"],
        "content": json.dumps(outcome.result, ensure_ascii=False, default=str),
        **({"is_error": True} if outcome.is_error else {}),
    }
    return ExecutedTool(result_block, outcome, outcome.session or ctx.session, round((time.perf_counter() - started) * 1000))
