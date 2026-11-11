"""Las reglas duras viven en el código: se prueban sin modelo."""

from movila.policies import OUTAGE_CREDIT_AMOUNT
from movila.tools.billing import get_invoice_detail, get_invoices
from movila.tools.identity import verify_customer
from movila.tools.network import apply_outage_credit
from movila.tools.plans import confirm_plan_change, preview_plan_change
from movila.tools.registry import MOVILA_TOOLS, to_tool_definitions
from movila.tools.executor import execute_tool_call
from tests.conftest import ANA, BRUNO, CARLA, ctx_for, new_session


def run(tool, api, api_key, session, **input_):
    return tool.run(tool.input_model.model_validate(input_), ctx_for(api, api_key, session))


def test_verification_succeeds_and_never_returns_dni(api, api_key):
    out = run(verify_customer, api, api_key, new_session(), phone="1155550001", dni_last4="4821", birth_date="1990-03-14")
    assert out.result["verified"] is True
    assert out.session.customer.customer_id == "C001"
    assert "dni" not in str(out.result).lower()


def test_three_failed_verifications_hand_off(api, api_key):
    session = new_session()
    for _ in range(3):
        out = run(verify_customer, api, api_key, session, phone="1155550001", dni_last4="0000", birth_date="1990-03-14")
        session = out.session
    assert session.ended is True
    assert out.result["transferred_to_human"] is True


def test_invoices_require_verification(api, api_key):
    out = run(get_invoices, api, api_key, new_session())
    assert out.is_error and out.result["error"] == "not_verified"


def test_other_customers_invoice_looks_missing(api, api_key):
    out = run(get_invoice_detail, api, api_key, new_session(ANA), invoice_id="F-C002-2026-09")
    assert out.is_error and out.result["error"] == "not_found"


def test_overdue_invoice_blocks_plan_change(api, api_key):
    out = run(preview_plan_change, api, api_key, new_session(BRUNO), new_plan_id="P99")
    assert out.result["error"] == "blocked_overdue_invoice"


def test_confirm_in_same_turn_is_rejected(api, api_key):
    preview = run(preview_plan_change, api, api_key, new_session(ANA, turn=1), new_plan_id="P30")
    out = run(confirm_plan_change, api, api_key, preview.session, token=preview.result["token"])
    assert out.result["error"] == "confirmation_required"
    assert api.inspect()["charges"] == []


def test_plan_change_charges_once_even_if_session_is_lost(api, api_key):
    preview = run(preview_plan_change, api, api_key, new_session(ANA, turn=1), new_plan_id="P30")
    token = preview.result["token"]
    next_turn = preview.session.update(turn=2)

    first = run(confirm_plan_change, api, api_key, next_turn, token=token)
    # Se pierde la sesión (el modelo reintenta con la sesión vieja): la guarda en memoria no alcanza,
    # pero DBOS ya registró el workflow con ese token y devuelve el resultado guardado.
    again = run(confirm_plan_change, api, api_key, next_turn, token=token)

    assert first.result["prorated_charge"] == again.result["prorated_charge"] == 3000
    assert len(api.inspect()["charges"]) == 1
    assert len(api.inspect()["sms"]) == 1


def test_credit_only_with_long_outage_and_once(api, api_key):
    no_outage = run(apply_outage_credit, api, api_key, new_session(ANA))
    assert no_outage.result["error"] == "not_eligible"

    first = run(apply_outage_credit, api, api_key, new_session(CARLA))
    second = run(apply_outage_credit, api, api_key, first.session)
    assert first.result["amount"] == OUTAGE_CREDIT_AMOUNT
    assert second.result["error"] == "already_applied"
    assert [c["amount"] for c in api.inspect()["charges"]] == [-OUTAGE_CREDIT_AMOUNT]


def test_invalid_input_returns_error_to_model(api, api_key):
    block = {"type": "tool_use", "id": "t1", "name": "verify_customer", "input": {"phone": "123", "dni_last4": "4821", "birth_date": "x"}}
    executed = execute_tool_call(block, MOVILA_TOOLS, ctx_for(api, api_key, new_session()))
    assert executed.result_block["is_error"] is True
    assert "invalid_input" in executed.result_block["content"]


def test_tool_schemas_are_strict_compatible():
    for definition in to_tool_definitions(MOVILA_TOOLS):
        schema = definition["input_schema"]
        assert schema["additionalProperties"] is False
        assert "pattern" not in str(schema) and "title" not in schema
