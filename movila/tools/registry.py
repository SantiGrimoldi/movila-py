from movila.tools.base import AgentTool
from movila.tools.billing import get_invoice_detail, get_invoices
from movila.tools.identity import verify_customer
from movila.tools.network import apply_outage_credit, check_network_status
from movila.tools.plans import confirm_plan_change, list_plans, preview_plan_change
from movila.tools.support import create_ticket, transfer_to_human

MOVILA_TOOLS: tuple[AgentTool, ...] = (
    list_plans,
    check_network_status,
    verify_customer,
    get_invoices,
    get_invoice_detail,
    preview_plan_change,
    confirm_plan_change,
    apply_outage_credit,
    create_ticket,
    transfer_to_human,
)

# Strict mode no soporta estas restricciones (la API responde 400). Se quitan del esquema que ve
# el modelo, pero Pydantic las sigue validando en el ejecutor: si el modelo manda un dato mal
# formado, recibe invalid_input y se corrige.
_UNSUPPORTED_IN_STRICT = {
    "title", "minLength", "maxLength", "pattern", "minimum", "maximum",
    "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
}


def _strict_compatible(node: object) -> object:
    if isinstance(node, list):
        return [_strict_compatible(n) for n in node]
    if not isinstance(node, dict):
        return node
    return {
        key: ({k: _strict_compatible(v) for k, v in value.items()} if key == "properties" else _strict_compatible(value))
        for key, value in node.items()
        if key not in _UNSUPPORTED_IN_STRICT
    }


def to_tool_definitions(tools: tuple[AgentTool, ...]) -> list[dict]:
    """El modelo Pydantic es la única fuente de verdad: valida la entrada y además genera el JSON Schema."""
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": _strict_compatible(tool.input_model.model_json_schema()),
            "strict": True,
        }
        for tool in tools
    ]
