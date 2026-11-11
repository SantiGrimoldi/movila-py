# Movila: a voice customer-support agent in Python

Movila is a customer-support agent for a fictional Argentine mobile carrier. Customers can chat with it or call it by voice, in Spanish. It verifies who they are, explains invoices, changes plans, checks network outages and credits them, opens tickets, and hands off to a human when it should.

It's built on **LangGraph**, **Pydantic** and **DBOS**, calls Claude directly with the official Anthropic SDK, and runs voice locally with **Whisper** (speech-to-text) and **Piper** (text-to-speech). It ships with 13 LLM-judged eval scenarios and 22 offline tests.

> I first wrote the agent loop in TypeScript without any framework. This is the same agent (same rules, same 10 tools, same 13 eval scenarios) rebuilt with frameworks, to see where they pay off and where they don't.

## Quick start

Requirements: Python 3.13+, [uv](https://docs.astral.sh/uv/), and an Anthropic API key. Voice mode needs a Mac with Apple Silicon, because Whisper runs on MLX.

```bash
uv sync --all-extras
```

```bash
cp .env.example .env
```

Put your `ANTHROPIC_API_KEY` in `.env`, then:

```bash
uv run movila
```

```bash
uv run movila-voice
```

| Command | What it does |
|---|---|
| `uv run movila` | Chat in the terminal. `--thread <id>` resumes a conversation stored in SQLite. |
| `uv run movila-voice` | Push-to-talk voice (Enter to start and stop). `--keyboard` lets you type and hear the reply. `--simulate <call>\|all` plays scripted calls with a synthetic caller voice. `--mute` skips audio playback. |
| `uv run movila-eval --trials 3` | Runs the eval suite against the real model, with an LLM judge. |
| `uv run python demos/crash_recovery.py` | Kills the process between a charge and its SMS, then shows DBOS resuming without charging twice. |
| `uv run pytest` | Offline tests with a fake model. |

The model defaults to `claude-opus-5-5` with effort `low`; set `MOVILA_MODEL` to change it. The first voice run downloads Whisper large-v3-turbo (~1.6 GB) and the Piper voice `es_AR-daniela-high` (~115 MB). `MOVILA_TTS=say` uses the built-in macOS voice instead and downloads nothing.

## Architecture

| Piece | Role | Code |
|---|---|---|
| **LangGraph** | Runs the turn as a graph: `start_turn → agent ⇄ tools → handoff/give_up`. Its checkpointer saves messages and session after every node, so a conversation survives a restart. | [graph.py](movila/graph.py), [agent.py](movila/agent.py) |
| **Pydantic** | Contracts: each tool's input (validated, and turned into a strict JSON Schema for the model), the immutable session (`frozen`), the seed data, and the eval judge's structured verdict. | [tools/](movila/tools/), [session.py](movila/session.py), [evals/judge.py](evals/judge.py) |
| **DBOS** | Exactly-once execution for writes that charge, credit or notify. Each one is a workflow keyed by an idempotency key (the plan-change token, the conversation id). If the process dies halfway, it resumes from the last completed step. | [durable.py](movila/durable.py) |
| **Anthropic SDK** | Claude is called directly, not through LangChain's wrapper. LangGraph doesn't need the wrapper, and calling the SDK directly gives full control over effort, fallbacks and thinking blocks. | [llm.py](movila/llm.py) |
| **Voice** | Local STT with Whisper on MLX. Local neural TTS with Piper and a Rioplatense Spanish voice, played sentence by sentence as it's generated. When the model is about to call tools it says a short filler line, so the caller doesn't sit in silence. Latency is measured per stage. | [voice/](movila/voice/) |

**Tools:** `list_plans`, `check_network_status`, `verify_customer`, `get_invoices`, `get_invoice_detail`, `preview_plan_change`, `confirm_plan_change`, `apply_outage_credit`, `create_ticket`, `transfer_to_human`. They run against an in-memory mock carrier API ([mock_api.py](movila/mock_api.py)) seeded with fictional customers.

**Guardrails live in code, not in the prompt.** The prompt explains the rules; the code enforces them. Customer data is only shown after identity verification. Three failed verifications hand off to a human. A plan change is a two-step preview/confirm with a token, and the confirm is rejected in the same turn as the preview. Outage credits have a fixed amount and are applied once per conversation. With DBOS on top, the token can't charge twice even if the session is lost.

## Results

- **Evals: 13/13** on the first run against the real model.
- **Tests: 22/22** offline (fake model): guardrails, single charge even when the session is lost, iteration limit, resuming from SQLite, voice sentences not overlapping.
- **Crash demo** ([demos/crash_recovery.py](demos/crash_recovery.py)):

  | Scenario | Charges | SMS sent |
  |---|---|---|
  | Without DBOS, the agent retries after the crash | 3000, 3000 | 0 |
  | With DBOS, the process dies between charge and SMS | 3000 | 0 |
  | With DBOS, the process restarts | 3000 | 1 |
  | With DBOS, the model repeats the confirmation with the same token | 3000 | 1 |

- **Simulated voice calls:** all 5 are resolved (invoice question, plan change with an overdue balance, no signal, cancellation, plan change). What they showed:
  - **STT drops digits.** `whisper-small` transcribed "1199" as "199" and "5555" as "555". `large-v3-turbo` is better, but once it still produced a 9-digit phone number. The agent didn't make anything up: it asked again, the caller dictated digit by digit, and the call went on. In another run the model "filled in" the missing digit on its own. That only worked out because DNI and birth date are also required. In production, numbers should be read back for confirmation.
  - **Latency is driven by the number of model calls.** STT takes ~0.5 s. Each Opus 5.5 call at effort low takes ~2 s. A turn with 1 call leaves ~3 s of silence; one with 3 calls (verify → preview → reply) takes 6–9 s. That's what the filler line is for.
  - **TTS barely adds latency when played per sentence.** Piper synthesizes 8.5 s of audio in ~0.9 s, but the first sentence starts playing after 0.2–0.3 s (up to ~0.85 s if the first sentence is long). Waiting for the full reply would cost the whole audio length.
  - **More natural isn't easier to transcribe.** Feeding Piper's voice back through Whisper, amounts came out perfect, but "corte" became "cote" and "lleva" became "llega" (the Rioplatense "ll"). With macOS `say` everything was exact. A person wouldn't notice, but if another system transcribes calls (QA, analytics), it's worth measuring.

## Design decisions and tradeoffs

**Why frameworks here, when the TypeScript version has none?** Both are defensible. Without frameworks the whole loop fits in ~120 lines and nothing is hidden, which is best for a small, well-scoped case. Frameworks start paying off when:
- the flow grows more steps, branches or human approvals (LangGraph: the graph is explicit and can pause and resume);
- there are side effects that must not repeat and the process can crash (DBOS: durability without running a queue or Temporal, just SQLite or Postgres);
- several teams need to share contracts (Pydantic).

**LangGraph and DBOS don't overlap.** LangGraph persists *the conversation* (what was said, which node it's on). DBOS guarantees *external side effects* happen exactly once. You could use just one of them, running the whole turn as a DBOS workflow or using LangGraph's checkpointer with retries, but each would be doing a job it wasn't designed for.

**The official SDK inside a LangGraph node, without `ChatAnthropic`.** You lose LangChain's provider portability. You gain direct control over `effort`, fallbacks and thinking blocks, which must be passed back unchanged.

**Local voice.** Whisper and Piper on a Mac are right for a demo: no cost, no network, full privacy, and Piper already has a Rioplatense accent. For production I'd use a streaming STT and TTS (Deepgram, ElevenLabs or similar) or a speech-to-speech model. TTS is a swappable engine ([tts.py](movila/voice/tts.py)), so switching providers means adding one class.

## What I'd do next

- **Cut voice latency:** stream model output into TTS (TTS already plays per sentence, but waits for the full model reply), use a faster model for simple turns (`MOVILA_MODEL=claude-haiku-5-5`, checked against the evals), and merge verification and lookup into a single round trip.
- **Read numbers back** over voice ("is your number 11 5555 0001?") before verifying.
- **Real telephony:** Twilio Media Streams into this same graph, with barge-in (stop TTS when the caller talks).
- **Postgres** instead of SQLite for DBOS and the checkpointer, for running several instances.
- **Telemetry:** DBOS and LangGraph export OpenTelemetry; the missing piece is shipping traces to a backend and tracking latency per node.
