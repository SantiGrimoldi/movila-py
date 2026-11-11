"""Una tool se define en un solo lugar: nombre, descripción para el modelo,
modelo Pydantic de entrada (que valida y además genera el JSON Schema) y la implementación."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from movila.mock_api import MovilaApi
from movila.session import Session


class ToolInput(BaseModel):
    """Base de las entradas: strict mode exige que no haya campos de más."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class NoInput(ToolInput):
    pass


@dataclass(frozen=True)
class ToolContext:
    api: MovilaApi
    api_key: str  # clave con la que DBOS encuentra esta API al ejecutar un paso durable
    session: Session


@dataclass(frozen=True)
class ToolOutcome:
    """Lo que devuelve una tool: el resultado para el modelo y, si cambió, la sesión nueva."""

    result: Any
    session: Session | None = None
    is_error: bool = False


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    input_model: type[ToolInput]
    run: Callable[[Any, ToolContext], ToolOutcome]


def tool_error(code: str, message: str) -> ToolOutcome:
    """Error en un formato que el modelo pueda entender y usar para corregirse."""
    return ToolOutcome(result={"error": code, "message": message}, is_error=True)
