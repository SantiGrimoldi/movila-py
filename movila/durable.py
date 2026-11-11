"""Escrituras durables con DBOS: cada efecto sobre un sistema externo corre UNA sola vez.

Reparto de responsabilidades:
- LangGraph orquesta la conversación y guarda su estado (checkpointer).
- DBOS garantiza exactly-once en las escrituras que cobran, acreditan o notifican.

Cómo: cada escritura es un workflow de DBOS con un ID determinista (clave de idempotencia).
- Si el mismo ID se ejecuta dos veces (el modelo repite la tool, un reintento, un doble click),
  DBOS devuelve el resultado guardado sin volver a ejecutar los pasos.
- Si el proceso se cae a mitad de un workflow, al reiniciar DBOS lo retoma desde el último
  paso completado: no repite el cobro y sí manda el SMS que faltaba.
"""

import os
from pathlib import Path

from dbos import DBOS, SetWorkflowID

from movila.mock_api import MovilaApi

DEFAULT_DB_PATH = Path(".dbos/movila.sqlite")

# Los pasos reciben una clave en lugar del objeto API: los argumentos de un workflow
# se guardan en la base para poder recuperarlo, así que tienen que ser serializables.
_APIS: dict[str, MovilaApi] = {}
_launched = False


def register_api(key: str, api: MovilaApi) -> str:
    _APIS[key] = api
    return key


def launch(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Inicializa DBOS una vez por proceso. Al lanzar, retoma los workflows que quedaron a medias."""
    global _launched
    if _launched:
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)
    DBOS(config={
        "name": "movila",
        "system_database_url": f"sqlite:///{db_path}",
        "console_log_level": os.environ.get("DBOS_LOG_LEVEL", "ERROR"),
    })
    DBOS.launch()
    _launched = True


def shutdown() -> None:
    global _launched
    if _launched:
        DBOS.destroy()
        _launched = False


# ---- pasos (cada uno se registra en la base al terminar) ---------------------

@DBOS.step()
def _change_plan_step(api_key: str, customer_id: str, new_plan_id: str) -> dict:
    return _APIS[api_key].change_plan(customer_id, new_plan_id)


@DBOS.step()
def _send_sms_step(api_key: str, customer_id: str, text: str) -> dict:
    if os.environ.get("MOVILA_CRASH_BEFORE_SMS") == "1":
        os._exit(1)  # solo para la demo de recuperación: simula que el proceso muere acá
    return _APIS[api_key].send_sms(customer_id, text)


@DBOS.step()
def _apply_credit_step(api_key: str, customer_id: str, amount: int, reason: str) -> dict:
    return _APIS[api_key].apply_credit(customer_id, amount, reason)


@DBOS.step()
def _create_ticket_step(api_key: str, customer_id: str, category: str, summary: str) -> dict:
    return _APIS[api_key].create_ticket(customer_id, category, summary)


# ---- workflows ---------------------------------------------------------------

@DBOS.workflow()
def change_plan_workflow(api_key: str, customer_id: str, new_plan_id: str) -> dict:
    change = _change_plan_step(api_key, customer_id, new_plan_id)
    sms = _send_sms_step(api_key, customer_id, f"Tu plan cambia a {new_plan_id} desde el {change['effective_date']}.")
    return {**change, **sms}


@DBOS.workflow()
def apply_credit_workflow(api_key: str, customer_id: str, amount: int, reason: str) -> dict:
    return _apply_credit_step(api_key, customer_id, amount, reason)


@DBOS.workflow()
def create_ticket_workflow(api_key: str, customer_id: str, category: str, summary: str) -> dict:
    return _create_ticket_step(api_key, customer_id, category, summary)


# ---- API para las tools: siempre con clave de idempotencia ----------------------

def change_plan_once(api_key: str, idempotency_key: str, customer_id: str, new_plan_id: str) -> dict:
    with SetWorkflowID(f"plan-change:{idempotency_key}"):
        return change_plan_workflow(api_key, customer_id, new_plan_id)


def apply_credit_once(api_key: str, idempotency_key: str, customer_id: str, amount: int, reason: str) -> dict:
    with SetWorkflowID(f"credit:{idempotency_key}"):
        return apply_credit_workflow(api_key, customer_id, amount, reason)


def create_ticket_once(api_key: str, idempotency_key: str, customer_id: str, category: str, summary: str) -> dict:
    with SetWorkflowID(f"ticket:{idempotency_key}"):
        return create_ticket_workflow(api_key, customer_id, category, summary)
