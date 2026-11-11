"""El grafo de punta a punta con un modelo falso (sin red)."""

import json
import uuid

from movila.agent import MovilaAgent, sqlite_checkpointer
from movila.mock_api import ApiOptions, MovilaApi
from tests.conftest import ScriptedModel, text, tool_use


class PlanChangeModel(ScriptedModel):
    """Lee el token del preview de la conversación, como haría el modelo real."""

    def __call__(self, system, messages, tools):
        response = super().__call__(system, messages, tools)
        for block in response.content:
            if block.get("name") == "confirm_plan_change":
                block["input"] = {"token": _last_preview_token(messages)}
        return response


def _last_preview_token(messages):
    for message in reversed(messages):
        if message["role"] == "user" and isinstance(message["content"], list):
            for block in message["content"]:
                if block.get("type") == "tool_result" and '"token"' in block["content"]:
                    return json.loads(block["content"])["token"]
    raise AssertionError("no hubo preview")


def make_agent(model, api_key=None, **kwargs):
    reliable = MovilaApi(ApiOptions(invoice_failure_rate=0))
    return MovilaAgent(model, api=reliable, api_key=api_key or f"test-{uuid.uuid4()}", log_dir=None, **kwargs)


def test_plan_change_across_two_turns_charges_once():
    model = PlanChangeModel(
        [tool_use("verify_customer", phone="1155550001", dni_last4="4821", birth_date="1990-03-14"),
         tool_use("preview_plan_change", new_plan_id="P30")],
        [text("El Plus 30GB cuesta $14.000, $6.000 más por mes. ¿Confirmás?")],
        [tool_use("confirm_plan_change")],
        [text("Listo, tu plan ya es Plus 30GB.")],
    )
    agent = make_agent(model)

    first = agent.send("t1", "Soy Ana... quiero el Plus 30GB")
    assert first.stop_reason == "end_turn"
    assert agent.api.inspect()["charges"] == []

    second = agent.send("t1", "Sí, confirmo")
    assert second.reply == "Listo, tu plan ya es Plus 30GB."
    assert [e["name"] for e in second.trace if e["type"] == "tool_call"] == ["confirm_plan_change"]
    assert len(agent.api.inspect()["charges"]) == 1
    # Los tool_result de un mismo turno van en un solo mensaje de usuario.
    assert len(model.calls[1][-1]["content"]) == 2


def test_handoff_ends_the_conversation():
    model = ScriptedModel([tool_use("transfer_to_human", reason="cancellation", summary="El cliente quiere dar de baja la línea")])
    result = make_agent(model).send("t2", "Quiero dar de baja la línea")
    assert result.stop_reason == "handoff"
    assert result.session.ended is True


def test_iteration_limit_gives_up():
    model = ScriptedModel(*[[tool_use("list_plans")] for _ in range(8)])
    result = make_agent(model).send("t3", "planes?")
    assert result.stop_reason == "max_iterations"


def test_tools_started_callback_fires_for_voice_filler():
    model = ScriptedModel([tool_use("list_plans")], [text("Tenemos tres planes.")])
    seen = []
    make_agent(model).send("t4", "planes?", on_tools_started=seen.append)
    assert seen == [["list_plans"]]


def test_conversation_survives_a_restart(tmp_path):
    """El checkpointer en SQLite guarda mensajes y sesión: otro proceso retoma la conversación."""
    db = tmp_path / "conversations.sqlite"
    api_key = f"test-{uuid.uuid4()}"

    def agent_with(model):
        return make_agent(model, api_key=api_key, checkpointer=sqlite_checkpointer(db))

    agent_with(ScriptedModel(
        [tool_use("verify_customer", phone="1155550003", dni_last4="1199", birth_date="2001-07-21")],
        [text("Hola Carla, ¿en qué te ayudo?")],
    )).send("t5", "Soy Carla...")

    restarted = agent_with(ScriptedModel([text("Sigo acá.")]))
    session = restarted.session("t5")
    assert session.customer.customer_id == "C003"
    result = restarted.send("t5", "¿Seguís ahí?")
    assert result.session.turn == 2
