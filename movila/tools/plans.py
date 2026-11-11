"""Cambio de plan en dos pasos: preview (valida y propone, no cambia nada) y confirm (aplica).

Las guardas garantizan, en código:
- que exista una propuesta previa con ese token (no se puede saltear el preview),
- que el cliente haya escrito después de ver la propuesta (no se confirma en el mismo turno),
- que el mismo token no cobre dos veces: la sesión lo recuerda y, además, DBOS usa el token
  como clave de idempotencia (aguanta aunque se pierda la sesión o se caiga el proceso).
"""

import uuid

from pydantic import Field

from movila import durable
from movila.tools.base import AgentTool, NoInput, ToolContext, ToolInput, ToolOutcome, tool_error
from movila.session import CompletedPlanChange, PendingPlanChange
from movila.tools.guards import not_verified, with_retry


def _list_plans(_: NoInput, ctx: ToolContext) -> ToolOutcome:
    return ToolOutcome([p.model_dump() for p in ctx.api.list_plans()])


list_plans = AgentTool(
    name="list_plans",
    description=(
        "Lista los planes disponibles de Movila con nombre, datos incluidos y precio mensual. "
        "Es información pública: no requiere verificar la identidad."
    ),
    input_model=NoInput,
    run=_list_plans,
)


class PreviewInput(ToolInput):
    new_plan_id: str = Field(min_length=1, description="Id del plan nuevo tal como lo devuelve list_plans, por ejemplo P30")


def _preview(data: PreviewInput, ctx: ToolContext) -> ToolOutcome:
    session, api = ctx.session, ctx.api
    customer = session.customer
    if not customer:
        return not_verified()
    if data.new_plan_id == customer.plan_id:
        return tool_error("same_plan", "El cliente ya tiene ese plan")

    plans = {p.plan_id: p for p in api.list_plans()}
    current, new = plans.get(customer.plan_id), plans.get(data.new_plan_id)
    if not current or not new:
        return tool_error("not_found", "Ese plan no existe; consultá list_plans")

    invoices = with_retry(lambda: api.get_invoices(customer.customer_id))
    if any(i["status"] == "overdue" for i in invoices):
        return tool_error(
            "blocked_overdue_invoice",
            "El cliente tiene una factura vencida y no puede cambiar de plan. Ofrecele crear un ticket de categoría billing.",
        )

    token = str(uuid.uuid4())
    pending = PendingPlanChange(token=token, new_plan_id=new.plan_id, issued_at_turn=session.turn)
    return ToolOutcome(
        {"token": token, "current_plan": current.model_dump(), "new_plan": new.model_dump(), "monthly_difference": new.price - current.price},
        session.update(pending_plan_change=pending),
    )


preview_plan_change = AgentTool(
    name="preview_plan_change",
    description=(
        "Prepara un cambio de plan para el cliente verificado y devuelve la propuesta (plan actual, plan nuevo, precios) "
        "junto con un token. No aplica ningún cambio: mostrale la propuesta al cliente y, solo si la acepta "
        "explícitamente en su próximo mensaje, llamá a confirm_plan_change con ese token."
    ),
    input_model=PreviewInput,
    run=_preview,
)


class ConfirmInput(ToolInput):
    token: str = Field(min_length=1, description="Token devuelto por preview_plan_change")


def _confirm(data: ConfirmInput, ctx: ToolContext) -> ToolOutcome:
    session = ctx.session
    customer, pending, completed = session.customer, session.pending_plan_change, session.completed_plan_change
    if not customer:
        return not_verified()
    if completed and completed.token == data.token:
        return ToolOutcome({**completed.result, "already_applied": True})
    if not pending or pending.token != data.token:
        return tool_error("invalid_token", "No hay un cambio pendiente con ese token; volvé a llamar a preview_plan_change")
    if session.turn <= pending.issued_at_turn:
        return tool_error("confirmation_required", "Mostrale la propuesta al cliente y esperá que la acepte antes de confirmar")

    change = durable.change_plan_once(ctx.api_key, data.token, customer.customer_id, pending.new_plan_id)
    result = {"new_plan_id": pending.new_plan_id, **change}
    return ToolOutcome(
        result,
        session.update(
            customer=customer.model_copy(update={"plan_id": pending.new_plan_id}),
            pending_plan_change=None,
            completed_plan_change=CompletedPlanChange(token=data.token, result=result),
        ),
    )


confirm_plan_change = AgentTool(
    name="confirm_plan_change",
    description=(
        "Aplica el cambio de plan preparado con preview_plan_change. Usala solo después de que el cliente "
        "aceptó explícitamente la propuesta. Recibe el token que devolvió preview_plan_change."
    ),
    input_model=ConfirmInput,
    run=_confirm,
)
