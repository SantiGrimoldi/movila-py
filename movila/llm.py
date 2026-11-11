"""Único punto de contacto con el proveedor del modelo.

LangGraph orquesta, pero el modelo se llama con el SDK oficial de Anthropic (no con un wrapper
de LangChain): así controlamos effort, fallbacks y los bloques de thinking sin capas en el medio.
El resto del código depende de `CallModel`, así que en los tests se usa un modelo falso.
"""

import os
from collections.abc import Callable
from typing import Literal

import anthropic
from pydantic import BaseModel, ConfigDict

DEFAULT_MODEL = "claude-opus-5-5"
# El fallback del servidor (si el modelo rechaza por un falso positivo de seguridad) existe en estos modelos.
_MODELS_WITH_FALLBACK = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}


class ModelResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    content: list[dict]
    stop_reason: str | None
    usage: dict = {}


CallModel = Callable[[str, list[dict], list[dict]], ModelResponse]


def create_anthropic_model(
    model: str | None = None,
    effort: Literal["low", "medium", "high"] = "low",
    max_tokens: int = 4096,
) -> CallModel:
    # El SDK toma ANTHROPIC_API_KEY del entorno y reintenta solo 429/5xx y errores de red.
    client = anthropic.Anthropic(max_retries=3, timeout=60)
    model_id = model or os.environ.get("MOVILA_MODEL", DEFAULT_MODEL)
    fallback = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"} if model_id in _MODELS_WITH_FALLBACK else {}

    def call(system: str, messages: list[dict], tools: list[dict]) -> ModelResponse:
        response = client.beta.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            # Atención al cliente: respuestas cortas, pocas vueltas. Más esfuerzo = más latencia.
            output_config={"effort": effort},
            system=system,
            messages=messages,
            **({"tools": tools} if tools else {}),
            **fallback,
        )
        return ModelResponse(
            # Se guardan los bloques completos (incluido thinking): la API exige devolverlos sin cambios.
            content=[block.model_dump(mode="json", exclude_none=True) for block in response.content],
            stop_reason=response.stop_reason,
            usage=response.usage.model_dump(mode="json", exclude_none=True),
        )

    return call
