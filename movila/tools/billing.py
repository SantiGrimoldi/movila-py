from pydantic import Field

from movila.tools.base import AgentTool, NoInput, ToolContext, ToolInput, ToolOutcome, tool_error
from movila.tools.guards import not_verified, with_retry


def _get_invoices(_: NoInput, ctx: ToolContext) -> ToolOutcome:
    if not ctx.session.customer:
        return not_verified()
    customer_id = ctx.session.customer.customer_id
    return ToolOutcome({"invoices": with_retry(lambda: ctx.api.get_invoices(customer_id))})


get_invoices = AgentTool(
    name="get_invoices",
    description=(
        "Devuelve las últimas 3 facturas del cliente verificado (período, monto, estado y vencimiento). "
        "Requiere verify_customer. Para ver de qué se compone una factura, usá get_invoice_detail."
    ),
    input_model=NoInput,
    run=_get_invoices,
)


class InvoiceDetailInput(ToolInput):
    invoice_id: str = Field(min_length=1, description="Id de la factura tal como lo devuelve get_invoices")


def _get_invoice_detail(data: InvoiceDetailInput, ctx: ToolContext) -> ToolOutcome:
    if not ctx.session.customer:
        return not_verified()
    detail = with_retry(lambda: ctx.api.get_invoice_detail(data.invoice_id))
    # Privacidad: una factura ajena se responde igual que una inexistente.
    if detail["customer_id"] != ctx.session.customer.customer_id:
        return tool_error("not_found", "No hay una factura con ese id entre las del cliente")
    return ToolOutcome({"invoice_id": data.invoice_id, "period": detail["period"], "items": detail["items"]})


get_invoice_detail = AgentTool(
    name="get_invoice_detail",
    description=(
        "Devuelve los conceptos que componen una factura del cliente verificado. "
        "Usala cuando el cliente pregunta por qué una factura vino más alta. El invoice_id sale de get_invoices."
    ),
    input_model=InvoiceDetailInput,
    run=_get_invoice_detail,
)
