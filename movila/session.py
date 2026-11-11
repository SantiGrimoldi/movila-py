"""Estado de la conversación que NO vive en el historial de mensajes.

El modelo no lo puede modificar: solo el código de las tools lo cambia, y siempre
devolviendo una copia nueva (los modelos son frozen; se usa model_copy).

Cada campo sale de una regla de negocio: verificar antes de datos personales,
3 intentos, confirmar el cambio de plan, crédito una sola vez, la derivación termina la conversación.
"""

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class VerifiedCustomer(_Frozen):
    """Solo existe si la identidad se verificó: "verificado" y "qué cliente es" no pueden contradecirse."""

    customer_id: str
    name: str
    plan_id: str
    zip_code: str


class PendingPlanChange(_Frozen):
    token: str
    new_plan_id: str
    issued_at_turn: int  # para exigir que el cliente haya respondido antes de confirmar


class CompletedPlanChange(_Frozen):
    token: str
    result: dict


class Session(_Frozen):
    conversation_id: str
    turn: int = 0  # cantidad de mensajes del cliente; lo incrementa el grafo
    customer: VerifiedCustomer | None = None
    failed_verifications: int = 0
    pending_plan_change: PendingPlanChange | None = None
    completed_plan_change: CompletedPlanChange | None = None
    credit_applied: bool = False
    ended: bool = False

    def update(self, **changes: object) -> "Session":
        return self.model_copy(update=changes)
