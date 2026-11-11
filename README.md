# Movila en Python: LangGraph + Pydantic + DBOS + voz

El mismo agente de [movila/](../movila/) (TypeScript, sin frameworks) reescrito en Python con frameworks, para validar que lo podemos correr y tener con qué responder "¿y si el flujo crece?". Mismas reglas, mismas 10 tools, mismos 13 escenarios de evals. Además se puede usar por voz.

## Cómo correrlo

```bash
uv sync --all-extras
```

```bash
uv run movila
```

```bash
uv run movila-voice
```

```bash
uv run movila-voice --simulate all
```

```bash
uv run movila-eval --trials 3
```

```bash
uv run python demos/crash_recovery.py
```

```bash
uv run pytest
```

- `movila`: chat por terminal. `--thread <id>` retoma una conversación (vive en SQLite).
- `movila-voice`: hablás con push-to-talk (Enter para empezar y para terminar). `--keyboard` para escribir y escuchar la respuesta. `--simulate <llamada>|all` corre llamadas con una voz sintética de cliente; `--mute` no reproduce audio.
- La key se toma de `.env` o, si no hay, de `../movila/.env`. El modelo es `claude-opus-5-5` con effort `low`; `MOVILA_MODEL` lo cambia.
- La primera vez que usás la voz se descargan Whisper large-v3-turbo (~1,6 GB) y la voz de Piper `es_AR-daniela-high` (~115 MB, queda en `.voices/`). `MOVILA_TTS=say` usa la voz de macOS y no descarga nada.

## Qué hace cada pieza

| Pieza | Para qué | Dónde |
|---|---|---|
| **LangGraph** | Orquesta el ciclo como grafo (`start_turn → agent ⇄ tools → handoff/give_up`). Su checkpointer guarda mensajes y sesión después de cada nodo, así una conversación sobrevive a un reinicio. | [graph.py](movila/graph.py), [agent.py](movila/agent.py) |
| **Pydantic** | Contratos: la entrada de cada tool (valida y genera el JSON Schema strict), la sesión inmutable (`frozen`), los datos semilla y el veredicto estructurado del juez de evals. | [tools/](movila/tools/), [session.py](movila/session.py), [evals/judge.py](evals/judge.py) |
| **DBOS** | Exactly-once en las escrituras que cobran, acreditan o notifican. Cada una es un workflow con una clave de idempotencia (el token del preview, la conversación). Si el proceso se cae a la mitad, al reiniciar retoma desde el último paso hecho. | [durable.py](movila/durable.py) |
| **SDK de Anthropic** | El modelo se llama directo con el SDK, no con el wrapper de LangChain. LangGraph no lo necesita, y así controlamos effort, fallbacks y bloques de thinking sin capas en el medio. | [llm.py](movila/llm.py) |
| **Voz** | STT local con Whisper sobre MLX. TTS neuronal local con Piper y una voz argentina, que reproduce cada oración apenas la genera (`say` de macOS queda de respaldo). Si el modelo va a usar tools, dice "dame un segundo que lo reviso" para no dejar silencio. Mide la latencia de cada etapa. | [voice/](movila/voice/) |

## Qué pasó al correrlo

- **Evals: 13/13** en el primer intento contra el modelo real.
- **Tests: 22/22** sin red (modelo falso): guardas, cobro único aunque se pierda la sesión, límite de iteraciones, retomar desde SQLite, que la voz no superponga frases.
- **Demo de crash** ([demos/crash_recovery.py](demos/crash_recovery.py)):

  | | Cobros | SMS |
  |---|---|---|
  | Sin DBOS, el agente reintenta después del crash | 3000, 3000 | 0 |
  | Con DBOS, el proceso muere entre el cobro y el SMS | 3000 | 0 |
  | Con DBOS, el proceso reinicia | 3000 | 1 |
  | Con DBOS, el modelo repite la confirmación con el mismo token | 3000 | 1 |

- **Llamadas simuladas por voz**: las 5 se resuelven (factura, plan con deuda, sin señal, baja, cambio de plan). Lo que más sirve para la defensa:
  - **El STT se come dígitos.** `whisper-small` transcribió "1199" como "199" y "5555" como "555". `large-v3-turbo` lo hace mejor, pero igual en un caso entregó el teléfono con 9 dígitos. El agente no lo inventó: pidió que lo repitan, el cliente lo dictó dígito por dígito y siguió. En otra corrida el modelo "completó" el dígito faltante solo. Eso pasó porque igual se exige DNI y fecha, pero en producción conviene confirmar los números leyéndolos de vuelta.
  - **La latencia la manda la cantidad de llamadas al modelo.** El STT tarda ~0,5 s. Cada llamada a Opus 5.5 con effort low, ~2 s. Un turno con 1 llamada deja ~3 s de silencio. Uno con 3 (verificar → preview → responder), entre 6 y 9 s. Por eso la frase de espera.
  - **El TTS casi no suma si se reproduce por oración.** Piper sintetiza 8,5 s de audio en ~0,9 s, pero la primera oración suena a los 0,2–0,3 s. Con una primera oración larga sube a ~0,85 s. Esperar la respuesta entera para empezar a hablar costaría lo que tarda el audio completo.
  - **Más natural no es más fácil de transcribir.** Al pasar la voz de Piper por Whisper, los montos salieron perfectos, pero "corte" quedó "cote" y "lleva" quedó "llega" (la "ll" rioplatense). Con `say` salió todo exacto. A una persona no le cambia nada, pero si otro sistema transcribe la llamada (QA, analytics), conviene medirlo.

## Decisiones y tradeoffs

**¿Por qué frameworks acá si en TS fue sin frameworks?** Las dos posturas se defienden. Sin frameworks, el ciclo entra en 120 líneas y no hay nada escondido: es lo mejor para un caso acotado y para entender qué pasa. Los frameworks empiezan a pagar cuando:
- el flujo suma pasos, ramas o aprobaciones humanas (LangGraph: el grafo es explícito y se puede pausar y retomar),
- hay efectos que no se pueden repetir y el proceso se puede caer (DBOS: durabilidad sin montar una cola ni Temporal, solo una base SQLite o Postgres),
- varios equipos tienen que compartir contratos (Pydantic).

**LangGraph y DBOS no se pisan.** LangGraph guarda *la conversación* (qué se dijo, en qué nodo quedó). DBOS garantiza que *los efectos externos* ocurran una vez. Se podría usar uno solo: todo el turno como workflow de DBOS, o el checkpointer de LangGraph con reintentos. Pero entonces cada uno haría algo para lo que no está pensado.

**Las guardas siguen en el código.** Los frameworks no cambian la regla central: el prompt explica, el código garantiza. Ejemplos: verificar antes de mostrar datos, token de dos pasos, monto fijo del crédito. Con DBOS se suma una capa: aunque la sesión se pierda, el token no cobra dos veces.

**El SDK oficial dentro de un nodo de LangGraph, sin `ChatAnthropic`.** Se pierde la portabilidad entre proveedores de LangChain. A cambio se gana control directo sobre `effort`, `fallbacks` y los bloques de thinking, que tienen que volver sin cambios.

**Voz local.** Whisper y Piper en la Mac sirven para la demo: no hay costo, no hay red, la privacidad es total, y Piper ya tiene acento rioplatense. Para producción, un STT y un TTS por streaming (Deepgram, ElevenLabs o similar), o un modelo speech-to-speech. El TTS es un motor intercambiable ([tts.py](movila/voice/tts.py)), así que cambiar de proveedor es sumar una clase.

## Qué haría con más tiempo

- **Bajar la latencia de voz**: streaming del modelo → TTS (el TTS ya va por oración, pero espera la respuesta completa del modelo), un modelo más rápido para turnos simples (`MOVILA_MODEL=claude-haiku-5-5`, medido con las evals), y juntar verificación y lectura en una sola vuelta.
- **Confirmar los números leídos por voz** ("¿tu teléfono es 11 5555 0001?") antes de verificar.
- **Telefonía real**: Twilio Media Streams → este mismo grafo, con barge-in (cortar el TTS si el cliente habla).
- **Postgres** en lugar de SQLite para DBOS y el checkpointer, que es lo que se usaría con varias instancias.
- **Telemetría**: DBOS y LangGraph exportan OpenTelemetry. Faltaría mandar los traces a un backend y sacar métricas de latencia por nodo.
