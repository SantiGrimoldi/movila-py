import itertools
import uuid

import pytest

from movila import durable
from movila.llm import ModelResponse
from movila.mock_api import ApiOptions, MovilaApi
from movila.session import Session, VerifiedCustomer
from movila.tools.base import ToolContext


@pytest.fixture(scope="session", autouse=True)
def dbos(tmp_path_factory):
    durable.launch(tmp_path_factory.mktemp("dbos") / "test.sqlite")
    yield
    durable.shutdown()


@pytest.fixture
def api() -> MovilaApi:
    return MovilaApi(ApiOptions(invoice_failure_rate=0))


@pytest.fixture
def api_key(api) -> str:
    return durable.register_api(f"test-{uuid.uuid4()}", api)


def ctx_for(api: MovilaApi, api_key: str, session: Session) -> ToolContext:
    return ToolContext(api=api, api_key=api_key, session=session)


ANA = VerifiedCustomer(customer_id="C001", name="Ana Pérez", plan_id="P10", zip_code="1414")
BRUNO = VerifiedCustomer(customer_id="C002", name="Bruno Díaz", plan_id="P30", zip_code="1425")
CARLA = VerifiedCustomer(customer_id="C003", name="Carla Gómez", plan_id="P10", zip_code="1640")


def new_session(customer: VerifiedCustomer | None = None, turn: int = 1) -> Session:
    return Session(conversation_id=str(uuid.uuid4()), turn=turn, customer=customer)


_ids = itertools.count()


def tool_use(name: str, **input_: object) -> dict:
    return {"type": "tool_use", "id": f"toolu_{next(_ids)}", "name": name, "input": input_}


def text(value: str) -> dict:
    return {"type": "text", "text": value}


class ScriptedModel:
    """Modelo falso: devuelve las respuestas en orden y registra qué mensajes recibió."""

    def __init__(self, *responses: list[dict]) -> None:
        self._responses = list(responses)
        self.calls: list[list[dict]] = []

    def __call__(self, system: str, messages: list[dict], tools: list[dict]) -> ModelResponse:
        self.calls.append(messages)
        content = self._responses.pop(0)
        stop = "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"
        return ModelResponse(content=content, stop_reason=stop)
