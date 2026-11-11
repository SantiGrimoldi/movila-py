"""Corre un escenario de punta a punta con el agente real (mismo grafo, mismas tools, mismo prompt)
y evalúa los checks sobre lo que quedó registrado."""

import uuid
from concurrent.futures import ThreadPoolExecutor

from evals.types import CheckOutcome, EvalRun, Judge, Scenario, ScenarioResult
from movila.agent import MovilaAgent
from movila.llm import CallModel
from movila.mock_api import MovilaApi


def converse(scenario: Scenario, call_model: CallModel) -> EvalRun:
    # Cada intento arranca con un sistema externo nuevo y un id único (también para las claves de DBOS).
    run_id = f"eval-{scenario.id}-{uuid.uuid4()}"
    api = MovilaApi(scenario.api)
    agent = MovilaAgent(call_model, api=api, api_key=run_id, log_dir=None)
    transcript, tool_calls, stop_reasons = [], [], []
    session = None
    for text in scenario.turns:
        if session and session.ended:
            break
        result = agent.send(run_id, text)
        session = result.session
        transcript.append((text, result.reply))
        tool_calls.extend(e for e in result.trace if e["type"] == "tool_call")
        stop_reasons.append(result.stop_reason)
    return EvalRun(transcript, tool_calls, session, api.inspect(), stop_reasons)


def run_scenario(scenario: Scenario, trial: int, call_model: CallModel, judge: Judge) -> ScenarioResult:
    try:
        run = converse(scenario, call_model)
    except Exception as error:  # un error de infraestructura falla el escenario pero no corta la suite
        return ScenarioResult(scenario.id, trial, False, [], error=f"{type(error).__name__}: {error}")
    checks = []
    for check in scenario.checks:
        try:
            checks.append((check.name, check.evaluate(run, judge)))
        except Exception as error:
            checks.append((check.name, CheckOutcome(False, f"el check falló: {error}")))
    return ScenarioResult(scenario.id, trial, all(o.passed for _, o in checks), checks, run)


def run_suite(scenarios: tuple[Scenario, ...], call_model: CallModel, judge: Judge, trials: int = 1, concurrency: int = 4) -> list[ScenarioResult]:
    jobs = [(s, t) for s in scenarios for t in range(1, trials + 1)]
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(lambda job: run_scenario(job[0], job[1], call_model, judge), jobs))
