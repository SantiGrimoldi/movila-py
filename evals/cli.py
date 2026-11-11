"""Corre la suite de evals contra el modelo real.

    uv run movila-eval                         → todos los escenarios, 1 intento
    uv run movila-eval --trials 3              → 3 intentos por escenario (mide estabilidad)
    uv run movila-eval --only baja,privacidad-tercero

Guarda el resultado completo (con los traces) en logs/evals/ y sale con código 1 si algún
escenario no fue estable, para poder usarlo como gate en CI.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from evals.judge import create_judge
from evals.runner import run_suite
from evals.scenarios import SCENARIOS
from evals.types import ScenarioResult
from movila import durable
from movila.env import load_env
from movila.llm import create_anthropic_model

OUTPUT_DIR = Path("logs/evals")


def select(only: str | None):
    if not only:
        return SCENARIOS
    ids = {i.strip() for i in only.split(",")}
    unknown = ids - {s.id for s in SCENARIOS}
    if unknown:
        sys.exit(f"Escenarios inexistentes: {', '.join(sorted(unknown))}")
    return tuple(s for s in SCENARIOS if s.id in ids)


def report(results: list[ScenarioResult]) -> tuple[str, bool]:
    by_scenario: dict[str, list[ScenarioResult]] = defaultdict(list)
    for r in results:
        by_scenario[r.scenario_id].append(r)
    lines = []
    for scenario_id, trials in by_scenario.items():
        passed = sum(r.passed for r in trials)
        lines.append(f"{'✓' if passed == len(trials) else '✗'} {scenario_id:<28} {passed}/{len(trials)}")
        for r in trials:
            if r.error:
                lines.append(f"    intento {r.trial}: error: {r.error}")
            for name, outcome in r.checks:
                if not outcome.passed:
                    lines.append(f"    intento {r.trial}: ✗ {name}\n        {outcome.detail[:300]}")
    stable = sum(all(r.passed for r in t) for t in by_scenario.values())
    lines.append(f"\nEscenarios estables: {stable}/{len(by_scenario)} · intentos aprobados: {sum(r.passed for r in results)}/{len(results)}")
    return "\n".join(lines), stable == len(by_scenario)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=1, choices=range(1, 11))
    parser.add_argument("--concurrency", type=int, default=4, choices=range(1, 11))
    parser.add_argument("--only")
    args = parser.parse_args()

    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Falta ANTHROPIC_API_KEY: las evals corren contra el modelo real.")
    scenarios = select(args.only)
    durable.launch()
    try:
        print(f"Corriendo {len(scenarios)} escenarios × {args.trials} intento(s)...\n")
        results = run_suite(scenarios, create_anthropic_model(), create_judge(), args.trials, args.concurrency)
    finally:
        durable.shutdown()

    text, all_stable = report(results)
    print(text)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"{datetime.now().isoformat(timespec='seconds').replace(':', '-')}.json"
    out.write_text(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2, default=str))
    print(f"\nResultados completos (con traces): {out}")
    sys.exit(0 if all_stable else 1)


if __name__ == "__main__":
    main()
