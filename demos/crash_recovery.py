"""Demo: el proceso se cae a mitad de un cambio de plan y nadie cobra dos veces.

    uv run python demos/crash_recovery.py

El workflow de cambio de plan tiene dos pasos: cobrar (change_plan, NO idempotente) y mandar
el SMS de confirmación. Forzamos que el proceso muera entre los dos y comparamos:

  sin DBOS  → al reintentar, se cobra de nuevo
  con DBOS  → al reiniciar, retoma desde el SMS; reintentar con el mismo token no cobra
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from movila import durable
from movila.mock_api import MovilaApi

TOKEN = "demo-token-plan-P30"
API_KEY = "demo"


def child(phase: str, workdir: Path) -> None:
    """Corre en un proceso aparte: así el crash es un crash de verdad (os._exit)."""
    api = durable.register_api(API_KEY, MovilaApi(ledger_file=workdir / "ledger.json"))
    if phase == "naive":
        # Lo que haría un agente sin durabilidad: reintentar la llamada que "falló".
        MovilaApi(ledger_file=workdir / "naive.json").change_plan("C001", "P30")
        return
    # Al lanzar, DBOS retoma solo los workflows que quedaron a medias (fase "recover").
    durable.launch(workdir / "dbos.sqlite")
    if phase in ("crash", "retry"):
        print("   resultado:", durable.change_plan_once(api, TOKEN, "C001", "P30"))
    if phase == "recover":
        from dbos import DBOS
        print("   resultado:", DBOS.retrieve_workflow(f"plan-change:{TOKEN}").get_result())
    durable.shutdown()


def run_phase(phase: str, workdir: Path, crash: bool = False) -> None:
    env = {**os.environ, "MOVILA_CRASH_BEFORE_SMS": "1" if crash else "0"}
    sys.stdout.flush()  # que lo que imprimió este proceso salga antes que lo del hijo
    code =subprocess.run([sys.executable, __file__, "--child", phase, str(workdir)], env=env).returncode
    if code != 0:
        print(f"   💥 el proceso murió (exit {code})")


def show(workdir: Path, file: str = "ledger.json") -> None:
    api = MovilaApi(ledger_file=workdir / file)
    state = api.inspect()
    print(f"   cobros: {[c['amount'] for c in state['charges']]} · SMS enviados: {len(state['sms'])}")


def main() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="movila-crash-"))

    print("\n── Sin DBOS: el cobro se hizo, el proceso murió, el agente reintenta ──")
    run_phase("naive", workdir)
    run_phase("naive", workdir)
    show(workdir, "naive.json")

    print("\n── Con DBOS · 1) cobra y muere antes del SMS ──")
    run_phase("crash", workdir, crash=True)
    show(workdir)

    print("\n── Con DBOS · 2) el proceso reinicia: DBOS retoma el workflow desde el paso que faltaba ──")
    run_phase("recover", workdir)
    show(workdir)

    print("\n── Con DBOS · 3) el modelo repite confirm_plan_change con el mismo token ──")
    run_phase("retry", workdir)
    show(workdir)
    print()


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        child(sys.argv[2], Path(sys.argv[3]))
    else:
        main()
