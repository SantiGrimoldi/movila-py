"""APIs simuladas de Movila. Reproducen a propósito los problemas de la consigna:

- get_invoices falla con timeout el 20% de las veces
- change_plan no es idempotente (cada llamada cobra de nuevo)

El "sistema externo" tiene estado propio: lo reemplazamos (nunca lo mutamos) en cada escritura.
"""

import json
import random
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from movila.data import SEED, SIMULATED_NOW, Customer, MovilaData, Plan


class MovilaApiError(Exception):
    def __init__(self, code: Literal["timeout", "not_found"], message: str) -> None:
        super().__init__(message)
        self.code = code


class Charge(BaseModel):
    model_config = ConfigDict(frozen=True)
    customer_id: str
    amount: int  # negativo = crédito
    reason: str


class ApiOptions(BaseModel):
    """Lo que un escenario de eval puede configurar del sistema externo."""

    model_config = ConfigDict(frozen=True)
    invoice_failure_rate: float = 0.2


class MovilaApi:
    def __init__(
        self,
        options: ApiOptions | None = None,
        data: MovilaData = SEED,
        rng: Callable[[], float] = random.random,
        ledger_file: Path | None = None,
    ) -> None:
        self._options = options or ApiOptions()
        self._data = data
        self._rng = rng
        self._charges: tuple[Charge, ...] = ()
        self._sms: tuple[dict, ...] = ()
        self._sequence = 0
        # Opcional: cobros y SMS en un archivo, para que el "sistema externo" sobreviva a que
        # se caiga nuestro proceso (lo usa la demo de recuperación con DBOS).
        self._ledger_file = ledger_file
        if ledger_file and ledger_file.exists():
            saved = json.loads(ledger_file.read_text())
            self._charges = tuple(Charge(**c) for c in saved["charges"])
            self._sms = tuple(saved["sms"])
            self._sequence = saved["sequence"]

    def _persist(self) -> None:
        if self._ledger_file:
            ledger = {"charges": [c.model_dump() for c in self._charges], "sms": list(self._sms), "sequence": self._sequence}
            self._ledger_file.write_text(json.dumps(ledger, ensure_ascii=False, indent=2))

    # ---- helpers -------------------------------------------------------------

    def _next_id(self, prefix: str) -> str:
        self._sequence += 1
        return f"{prefix}-{self._sequence:04d}"

    def _customer(self, customer_id: str) -> Customer:
        found = next((c for c in self._data.customers if c.customer_id == customer_id), None)
        if found is None:
            raise MovilaApiError("not_found", f"Cliente {customer_id} inexistente")
        return found

    def _plan(self, plan_id: str) -> Plan:
        found = next((p for p in self._data.plans if p.plan_id == plan_id), None)
        if found is None:
            raise MovilaApiError("not_found", f"Plan {plan_id} inexistente")
        return found

    # ---- lecturas ------------------------------------------------------------

    def find_customer_by_phone(self, phone: str) -> Customer | None:
        return next((c for c in self._data.customers if c.phone == phone), None)

    def verify_identity(self, customer_id: str, dni_last4: str, birth_date: str) -> bool:
        customer = self._customer(customer_id)
        return customer.dni_last4 == dni_last4 and customer.birth_date == birth_date

    def get_invoices(self, customer_id: str, limit: int = 3) -> list[dict]:
        self._customer(customer_id)
        if self._rng() < self._options.invoice_failure_rate:
            raise MovilaApiError("timeout", "El servicio de facturación no respondió a tiempo")
        own = sorted((i for i in self._data.invoices if i.customer_id == customer_id), key=lambda i: i.period, reverse=True)
        return [i.model_dump(include={"invoice_id", "period", "amount", "status", "due_date"}) for i in own[:limit]]

    def get_invoice_detail(self, invoice_id: str) -> dict:
        invoice = next((i for i in self._data.invoices if i.invoice_id == invoice_id), None)
        if invoice is None:
            raise MovilaApiError("not_found", f"Factura {invoice_id} inexistente")
        return invoice.model_dump(include={"invoice_id", "customer_id", "period", "items"})

    def list_plans(self) -> list[Plan]:
        return list(self._data.plans)

    def check_network_status(self, zip_code: str) -> dict:
        outage = next((o for o in self._data.outages if o.zip_code == zip_code), None)
        if outage is None:
            return {"outage": False}
        hours = round((SIMULATED_NOW - outage.since).total_seconds() / 3600)
        return {"outage": True, "since": outage.since.isoformat(), "eta": outage.eta.isoformat(), "hours_since_start": hours}

    # ---- escrituras ----------------------------------------------------------

    def change_plan(self, customer_id: str, new_plan_id: str) -> dict:
        """NO idempotente: cada llamada registra un cargo nuevo."""
        customer = self._customer(customer_id)
        old_plan, new_plan = self._plan(customer.plan_id), self._plan(new_plan_id)
        prorated = max(0, round((new_plan.price - old_plan.price) / 2))
        updated = customer.model_copy(update={"plan_id": new_plan_id})
        self._data = self._data.model_copy(
            update={"customers": tuple(updated if c.customer_id == customer_id else c for c in self._data.customers)}
        )
        self._charges = (*self._charges, Charge(customer_id=customer_id, amount=prorated, reason=f"Cambio a {new_plan_id}"))
        self._persist()
        return {"effective_date": "2026-11-01", "prorated_charge": prorated}

    def apply_credit(self, customer_id: str, amount: int, reason: str) -> dict:
        self._customer(customer_id)
        self._charges = (*self._charges, Charge(customer_id=customer_id, amount=-amount, reason=reason))
        credit = {"credit_id": self._next_id("CR")}
        self._persist()
        return credit

    def create_ticket(self, customer_id: str, category: str, summary: str) -> dict:
        self._customer(customer_id)
        return {"ticket_id": self._next_id("TK"), "category": category, "summary": summary}

    def transfer_to_human(self, reason: str, summary: str) -> dict:
        return {"queue_position": 3, "reason": reason, "summary": summary}

    def send_sms(self, customer_id: str, text: str) -> dict:
        self._customer(customer_id)
        self._sms = (*self._sms, {"customer_id": customer_id, "text": text})
        sms = {"sms_id": self._next_id("SMS")}
        self._persist()
        return sms

    # Solo para tests y evals: permite ver qué cambió en el "sistema externo".
    def inspect(self) -> dict:
        return {
            "charges": [c.model_dump() for c in self._charges],
            "sms": list(self._sms),
            "customers": [c.model_dump() for c in self._data.customers],
        }
