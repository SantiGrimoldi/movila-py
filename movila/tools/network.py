from pydantic import Field

from movila import durable
from movila.policies import OUTAGE_CREDIT_AMOUNT, OUTAGE_CREDIT_MIN_HOURS
from movila.tools.base import AgentTool, NoInput, ToolContext, ToolInput, ToolOutcome, tool_error
from movila.tools.guards import not_verified


class NetworkStatusInput(ToolInput):
    zip_code: str = Field(pattern=r"^\d{4}$", description="Código postal de 4 dígitos, por ejemplo 1640")


check_network_status = AgentTool(
    name="check_network_status",
    description=(
        "Consulta si hay un corte de red activo en un código postal. "
        "Usala cuando el cliente reporta problemas de señal. Devuelve desde cuándo y la estimación de solución. "
        "Si el cliente ya está verificado, usá el zip_code que devolvió verify_customer en lugar de pedírselo."
    ),
    input_model=NetworkStatusInput,
    run=lambda data, ctx: ToolOutcome(ctx.api.check_network_status(data.zip_code)),
)


def _apply_credit(_: NoInput, ctx: ToolContext) -> ToolOutcome:
    session, customer = ctx.session, ctx.session.customer
    if not customer:
        return not_verified()
    if session.credit_applied:
        return tool_error("already_applied", "Ya se aplicó un crédito en esta conversación")

    status = ctx.api.check_network_status(customer.zip_code)
    if not status["outage"] or status.get("hours_since_start", 0) <= OUTAGE_CREDIT_MIN_HOURS:
        return tool_error(
            "not_eligible",
            f"No hay un corte de más de {OUTAGE_CREDIT_MIN_HOURS} horas en la zona del cliente, así que no corresponde el crédito",
        )

    # Clave = conversación: aunque la sesión se pierda, DBOS no acredita dos veces en la misma conversación.
    credit = durable.apply_credit_once(
        ctx.api_key, session.conversation_id, customer.customer_id, OUTAGE_CREDIT_AMOUNT, f"Corte de red en CP {customer.zip_code}"
    )
    return ToolOutcome({**credit, "amount": OUTAGE_CREDIT_AMOUNT}, session.update(credit_applied=True))


apply_outage_credit = AgentTool(
    name="apply_outage_credit",
    description=(
        f"Aplica un crédito fijo de ${OUTAGE_CREDIT_AMOUNT} al cliente verificado por un corte de red en su zona. "
        f"Solo corresponde con un corte confirmado de más de {OUTAGE_CREDIT_MIN_HOURS} horas y una vez por conversación. "
        "La herramienta usa el código postal registrado en la cuenta y verifica el corte sola: no hace falta pedirle "
        "datos al cliente ni consultar antes check_network_status. Si no corresponde, rechaza el pedido."
    ),
    # La entrada está vacía a propósito: el monto y la zona no los elige el modelo.
    input_model=NoInput,
    run=_apply_credit,
)
