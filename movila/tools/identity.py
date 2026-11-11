from pydantic import Field

from movila.policies import MAX_VERIFICATION_ATTEMPTS
from movila.session import VerifiedCustomer
from movila.tools.base import AgentTool, ToolContext, ToolInput, ToolOutcome


class VerifyCustomerInput(ToolInput):
    phone: str = Field(pattern=r"^\d{10}$", description="Teléfono de 10 dígitos sin espacios ni guiones, por ejemplo 1155550001")
    dni_last4: str = Field(pattern=r"^\d{4}$", description="Últimos 4 dígitos del DNI")
    birth_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="Fecha de nacimiento en formato YYYY-MM-DD")


def _verify(data: VerifyCustomerInput, ctx: ToolContext) -> ToolOutcome:
    session, api = ctx.session, ctx.api
    if session.customer:
        c = session.customer
        return ToolOutcome({"verified": True, "name": c.name, "plan_id": c.plan_id, "zip_code": c.zip_code})

    found = api.find_customer_by_phone(data.phone)
    if found and api.verify_identity(found.customer_id, data.dni_last4, data.birth_date):
        customer = VerifiedCustomer(customer_id=found.customer_id, name=found.name, plan_id=found.plan_id, zip_code=found.zip_code)
        # Devolvemos lo que el agente puede necesitar (plan, CP) para no volver a pedirlo. El DNI y la fecha nunca vuelven.
        return ToolOutcome(
            {"verified": True, "name": customer.name, "plan_id": customer.plan_id, "zip_code": customer.zip_code},
            session.update(customer=customer),
        )

    # Mismo mensaje si el teléfono no existe o si un dato no coincide: no revelamos quién es cliente.
    failed = session.failed_verifications + 1
    if failed >= MAX_VERIFICATION_ATTEMPTS:
        handoff = api.transfer_to_human("identity_verification_failed", "Falló la verificación de identidad 3 veces")
        return ToolOutcome(
            {"verified": False, "transferred_to_human": True, "queue_position": handoff["queue_position"]},
            session.update(failed_verifications=failed, ended=True),
        )
    return ToolOutcome(
        {"verified": False, "attempts_left": MAX_VERIFICATION_ATTEMPTS - failed, "message": "Los datos no coinciden"},
        session.update(failed_verifications=failed),
    )


verify_customer = AgentTool(
    name="verify_customer",
    description=(
        "Verifica la identidad del cliente con su teléfono, los últimos 4 dígitos del DNI y su fecha de nacimiento. "
        "Es obligatoria antes de consultar facturas, cambiar el plan, aplicar créditos o crear tickets. "
        f"Después de {MAX_VERIFICATION_ATTEMPTS} intentos fallidos el cliente se deriva automáticamente a una persona."
    ),
    input_model=VerifyCustomerInput,
    run=_verify,
)
