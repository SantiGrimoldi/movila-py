"""Guardas compartidas. Son la parte del control que vive en el código:
el prompt le explica las reglas al modelo, pero estas funciones las garantizan."""

from collections.abc import Callable
from typing import TypeVar

from movila.mock_api import MovilaApiError
from movila.policies import INVOICE_FETCH_ATTEMPTS
from movila.tools.base import ToolOutcome, tool_error

T = TypeVar("T")


def not_verified() -> ToolOutcome:
    return tool_error("not_verified", "Primero hay que verificar la identidad del cliente con verify_customer.")


def with_retry(operation: Callable[[], T], attempts: int = INVOICE_FETCH_ATTEMPTS) -> T:
    """Reintenta solo los timeouts, y solo en lecturas: reintentar una escritura
    no idempotente (como change_plan) podría cobrarle dos veces al cliente."""
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except MovilaApiError as error:
            if error.code != "timeout" or attempt >= attempts:
                raise
    raise AssertionError("inalcanzable")
