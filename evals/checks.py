"""Checks reutilizables. Casi todos son deterministas: miran qué tools se llamaron y cómo
quedó el sistema externo, no cómo está redactada la respuesta. Solo `judged` usa un modelo."""

import json
import re
from collections.abc import Callable

from evals.types import Check, CheckOutcome, EvalRun


def _calls_to(run: EvalRun, name: str) -> list[dict]:
    return [c for c in run.tool_calls if c["name"] == name]


def _tool_path(run: EvalRun) -> str:
    """Resumen del trace para entender un fallo sin abrir el log: "verify_customer ✓ → get_invoices ✗"."""
    return " → ".join(f"{c['name']} {'✗' if c['is_error'] else '✓'}" for c in run.tool_calls) or "(sin tools)"


def _replies(run: EvalRun) -> list[str]:
    return [reply for _, reply in run.transcript]


def called_successfully(name: str) -> Check:
    return Check(f"llama a {name} sin error", lambda run, _: CheckOutcome(any(not c["is_error"] for c in _calls_to(run, name)), _tool_path(run)))


def never_succeeded(name: str) -> Check:
    return Check(f"{name} nunca se ejecuta con éxito", lambda run, _: CheckOutcome(all(c["is_error"] for c in _calls_to(run, name)), _tool_path(run)))


def called_with(name: str, label: str, matches: Callable[[dict], bool]) -> Check:
    def evaluate(run: EvalRun, _) -> CheckOutcome:
        calls = _calls_to(run, name)
        return CheckOutcome(any(not c["is_error"] and matches(c["input"]) for c in calls), json.dumps([c["input"] for c in calls], ensure_ascii=False))
    return Check(f"llama a {name} con {label}", evaluate)


def charges_count(expected: int) -> Check:
    return Check(f"se registran {expected} movimientos en la cuenta",
                 lambda run, _: CheckOutcome(len(run.external["charges"]) == expected, json.dumps(run.external["charges"], ensure_ascii=False)))


def total_credited(expected: int) -> Check:
    def evaluate(run: EvalRun, _) -> CheckOutcome:
        credited = -sum(c["amount"] for c in run.external["charges"] if c["amount"] < 0)
        return CheckOutcome(credited == expected, f"acreditado: ${credited}")
    return Check(f"se acredita ${expected} en total", evaluate)


def conversation_ended(expected: bool = True) -> Check:
    label = "la conversación se deriva y termina" if expected else "la conversación sigue abierta"
    return Check(label, lambda run, _: CheckOutcome(run.session.ended == expected, f"stop_reasons: {', '.join(run.stop_reasons)}"))


def last_reply_matches(pattern: str) -> Check:
    def evaluate(run: EvalRun, _) -> CheckOutcome:
        last = _replies(run)[-1] if run.transcript else ""
        return CheckOutcome(bool(re.search(pattern, last, re.IGNORECASE)), last)
    return Check(f"la última respuesta menciona /{pattern}/", evaluate)


def any_reply_matches(pattern: str) -> Check:
    return Check(f"alguna respuesta menciona /{pattern}/",
                 lambda run, _: CheckOutcome(any(re.search(pattern, r, re.IGNORECASE) for r in _replies(run)), " | ".join(_replies(run))))


def no_reply_matches(pattern: str) -> Check:
    def evaluate(run: EvalRun, _) -> CheckOutcome:
        offending = next((r for r in _replies(run) if re.search(pattern, r, re.IGNORECASE)), None)
        return CheckOutcome(offending is None, offending or "")
    return Check(f"ninguna respuesta menciona /{pattern}/", evaluate)


def judged(rubric: str) -> Check:
    def evaluate(run: EvalRun, judge) -> CheckOutcome:
        return judge(rubric, "\n\n".join(f"Cliente: {u}\nAgente: {a}" for u, a in run.transcript))
    return Check(f"juez: {rubric}", evaluate)
