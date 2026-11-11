"""Datos semilla de la consigna. Simulan la base de datos de Movila.

Todos los modelos son inmutables (frozen): el "sistema externo" se reemplaza, nunca se muta.
"""

from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict

InvoiceStatus = Literal["paid", "pending", "overdue"]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Customer(Frozen):
    customer_id: str
    name: str
    phone: str
    dni_last4: str
    birth_date: str  # YYYY-MM-DD
    plan_id: str
    zip_code: str


class Plan(Frozen):
    plan_id: str
    name: str
    data_gb: int | Literal["unlimited"]
    price: int


class InvoiceItem(Frozen):
    concept: str
    amount: int


class Invoice(Frozen):
    invoice_id: str
    customer_id: str
    period: str  # YYYY-MM
    amount: int
    status: InvoiceStatus
    due_date: str
    items: tuple[InvoiceItem, ...]


class Outage(Frozen):
    zip_code: str
    since: datetime
    eta: datetime


class MovilaData(Frozen):
    customers: tuple[Customer, ...]
    plans: tuple[Plan, ...]
    invoices: tuple[Invoice, ...]
    outages: tuple[Outage, ...]


SIMULATED_NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone(timedelta(hours=-3)))


def _hours_from_now(hours: int) -> datetime:
    return SIMULATED_NOW + timedelta(hours=hours)


def _abono(amount: int) -> InvoiceItem:
    return InvoiceItem(concept="Abono mensual", amount=amount)


SEED = MovilaData(
    customers=(
        Customer(customer_id="C001", name="Ana Pérez", phone="1155550001", dni_last4="4821", birth_date="1990-03-14", plan_id="P10", zip_code="1414"),
        Customer(customer_id="C002", name="Bruno Díaz", phone="1155550002", dni_last4="7730", birth_date="1985-11-02", plan_id="P30", zip_code="1425"),
        Customer(customer_id="C003", name="Carla Gómez", phone="1155550003", dni_last4="1199", birth_date="2001-07-21", plan_id="P10", zip_code="1640"),
    ),
    plans=(
        Plan(plan_id="P10", name="Básico 10GB", data_gb=10, price=8000),
        Plan(plan_id="P30", name="Plus 30GB", data_gb=30, price=14000),
        Plan(plan_id="P99", name="Ilimitado", data_gb="unlimited", price=22000),
    ),
    invoices=(
        Invoice(invoice_id="F-C001-2026-08", customer_id="C001", period="2026-08", amount=8000, status="paid", due_date="2026-09-10", items=(_abono(8000),)),
        Invoice(invoice_id="F-C001-2026-09", customer_id="C001", period="2026-09", amount=8000, status="paid", due_date="2026-10-10", items=(_abono(8000),)),
        Invoice(
            invoice_id="F-C001-2026-10", customer_id="C001", period="2026-10", amount=11500, status="pending", due_date="2026-11-10",
            items=(_abono(8000), InvoiceItem(concept="Roaming internacional", amount=3500)),
        ),
        Invoice(invoice_id="F-C002-2026-09", customer_id="C002", period="2026-09", amount=14000, status="overdue", due_date="2026-10-10", items=(_abono(14000),)),
        Invoice(invoice_id="F-C002-2026-10", customer_id="C002", period="2026-10", amount=14000, status="pending", due_date="2026-11-10", items=(_abono(14000),)),
        Invoice(invoice_id="F-C003-2026-10", customer_id="C003", period="2026-10", amount=8000, status="paid", due_date="2026-11-10", items=(_abono(8000),)),
    ),
    outages=(Outage(zip_code="1640", since=_hours_from_now(-30), eta=_hours_from_now(6)),),
)
