from typing import Literal

from pydantic import Field

from movila import durable
from movila.tools.base import AgentTool, ToolContext, ToolInput, ToolOutcome
from movila.tools.guards import not_verified


class TicketInput(ToolInput):
    category: Literal["billing", "technical", "other"] = Field(description="Equipo que tiene que resolverlo")
    summary: str = Field(min_length=10, max_length=500, description="Resumen del problema en 1 o 2 oraciones, sin datos sensibles")


def _create_ticket(data: TicketInput, ctx: ToolContext) -> ToolOutcome:
    session = ctx.session
    if not session.customer:
        return not_verified()
    # Un ticket por categoría y turno: si el modelo repite la llamada, no se duplica.
    key = f"{session.conversation_id}:{session.turn}:{data.category}"
    return ToolOutcome(durable.create_ticket_once(ctx.api_key, key, session.customer.customer_id, data.category, data.summary))


create_ticket = AgentTool(
    name="create_ticket",
    description=(
        "Crea un ticket para que un equipo lo resuelva después, cuando el pedido no se puede resolver en la conversación "
        "(por ejemplo, un cambio de plan bloqueado por deuda va a billing). Requiere verify_customer. "
        "Contale al cliente el número de ticket."
    ),
    input_model=TicketInput,
    run=_create_ticket,
)


class TransferInput(ToolInput):
    reason: Literal["customer_request", "cancellation", "legal", "frustrated_customer", "out_of_scope"]
    summary: str = Field(min_length=10, max_length=500, description="Resumen para la persona que atiende: qué pidió el cliente y qué se hizo")


transfer_to_human = AgentTool(
    name="transfer_to_human",
    description=(
        "Deriva la conversación a una persona del equipo y la termina. Usala cuando el cliente lo pide, quiere dar de baja "
        "la línea, plantea un tema legal, sigue enojado después de intentar ayudarlo o el pedido está fuera de tu alcance."
    ),
    input_model=TransferInput,
    # No exige verificación: derivar siempre tiene que ser posible. Termina la conversación.
    run=lambda data, ctx: ToolOutcome(ctx.api.transfer_to_human(data.reason, data.summary), ctx.session.update(ended=True)),
)
