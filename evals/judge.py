"""Juez con modelo para lo que el código no puede medir (idioma, tono).

Una sola pregunta concreta por check, y la respuesta sale como output estructurado: el SDK
valida el JSON contra el modelo Pydantic, así no hay que parsear "PASS/FAIL" a mano.
"""

import anthropic
from pydantic import BaseModel, Field

from evals.types import CheckOutcome, Judge
from movila.llm import DEFAULT_MODEL

_SYSTEM = (
    "Evaluás conversaciones de un agente de atención al cliente contra un criterio concreto. "
    "Evaluá únicamente el criterio indicado, nada más."
)


class Verdict(BaseModel):
    reason: str = Field(description="Motivo en una oración")
    passed: bool = Field(description="true si la conversación cumple el criterio")


def create_judge(model: str = DEFAULT_MODEL) -> Judge:
    client = anthropic.Anthropic(max_retries=3, timeout=60)

    def judge(rubric: str, transcript: str) -> CheckOutcome:
        response = client.messages.parse(
            model=model,
            max_tokens=2048,
            output_config={"effort": "low"},
            system=_SYSTEM,
            messages=[{"role": "user", "content": f"<criterio>\n{rubric}\n</criterio>\n\n<conversacion>\n{transcript}\n</conversacion>"}],
            output_format=Verdict,
        )
        verdict = response.parsed_output
        # Sin veredicto válido cuenta como falla: mejor revisar a mano que aprobar de más.
        if verdict is None:
            return CheckOutcome(False, f"el juez no devolvió un veredicto (stop_reason={response.stop_reason})")
        return CheckOutcome(verdict.passed, verdict.reason)

    return judge
