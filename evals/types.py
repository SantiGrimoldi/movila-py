from collections.abc import Callable
from dataclasses import dataclass, field

from movila.mock_api import ApiOptions
from movila.session import Session


@dataclass(frozen=True)
class EvalRun:
    """Todo lo que dejó una conversación: lo que se dijo, lo que se hizo y cómo quedó el sistema."""

    transcript: list[tuple[str, str]]  # (cliente, agente)
    tool_calls: list[dict]
    session: Session
    external: dict
    stop_reasons: list[str]


@dataclass(frozen=True)
class CheckOutcome:
    passed: bool
    detail: str = ""


Judge = Callable[[str, str], CheckOutcome]


@dataclass(frozen=True)
class Check:
    name: str
    evaluate: Callable[[EvalRun, Judge], CheckOutcome]


@dataclass(frozen=True)
class Scenario:
    id: str
    description: str
    turns: tuple[str, ...]
    checks: tuple[Check, ...]
    api: ApiOptions = field(default_factory=ApiOptions)


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    trial: int
    passed: bool
    checks: list[tuple[str, CheckOutcome]]
    run: EvalRun | None = None
    error: str | None = None
