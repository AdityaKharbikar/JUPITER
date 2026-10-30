# JUPITER module-by-module organization guide

## 1. What you should keep
Keep `jupiter_try2_reference.py` untouched. It is the exact reference snapshot of the uploaded `jupiter_try2.py`.

The modular project uses the extracted implementation as mixins. This is intentional: it lets you modularize without rewriting 149 methods at once.

## 2. Core
`jupiter/core/assistant.py` — composes the JUPITER object from the modules. This is the only place that should assemble the whole system.

`core/skill.py` — common contract for every command skill: `match()` + `execute()` + `SkillResult`.

`core/router.py` — future home for the hybrid deterministic/LLM router. `skills/registry.py` is the currently active registry during migration.

`core/legacy_actions.py` — original `handle_action()` fallback. Do not delete this until all direct-action commands are migrated and tested.

`core/conversation.py` — SQLite conversations, summaries, persistent facts, conversation storage.

`core/settings.py` — user name, input mode and persisted preferences.

`core/vocabulary.py` — learned words and Whisper initial-prompt hints.

`core/time_utils.py` — IST timestamp helper.

`core/phrases.py` — greetings, acknowledgements and sign-offs.

`core/security.py` — future confirmation/sandbox boundary for sensitive OS actions.

`core/health.py` — health checks for dependencies and services.

`core/telemetry.py` — structured performance logging.

`core/api.py` — stable facade that GUI/CLI/tests can call.

## 3. Services: original functionality moved out of the giant class
`services/calculator.py` — safe math evaluator.

`services/weather.py` — weather lookup.

`services/system.py` — system stats, network, battery and volume.

`services/media.py` — YouTube, songs, File Explorer and app launching.

`services/navigation.py` — location/geocoding.

`services/web.py` — translation, conversion, currency, news and sky information.

`services/timers.py` — timers and stopwatch.

`services/reminders.py` — reminders and natural-language time parsing.

`services/scheduler.py` — background timer/reminder event scheduler.

`services/notes_clipboard.py` — notes and clipboard actions.

`services/documents.py` — embeddings, chunking and local document indexing/Q&A.

`services/usage.py` — usage statistics.

`services/productivity.py` — new task-manager foundation for the next phase.

## 4. Audio
`audio/speech.py` — Piper synthesis, playback queue, playback stream and interruption.

`audio/stt.py` — faster-whisper transcription, audio cleanup and microphone capture.

`audio/barge_in.py` — spoken STOP detection and interruption monitor.

`audio/modes.py` — active / push-to-talk / sleep listening modes.

Do not put GUI logic here.

## 5. Models
`models/llm.py` — existing Ollama conversation/streaming implementation.

`models/model_router.py` — future selection between general Qwen3.5 4B and coding-specialist Qwen2.5-Coder 7B.

## 6. Skills
A skill should describe a command domain, not own the whole application.

`calculator.py` -> math
`weather.py` -> weather
`reminders.py` -> reminders
`timers.py` -> timers/stopwatch
`media.py` -> music/YouTube/apps
`browser.py` -> web search
`navigation.py` -> places/directions
`system.py` -> CPU/RAM/network/battery/volume
`documents.py` -> local document actions
`productivity.py` -> notes/clipboard/usage for now; later add tasks/projects
`conversion.py` -> unit/currency conversion
`information.py` -> time/date/news/sun/moon
`translation.py` -> translation
`memory.py` -> explicit memory
`conversation.py` -> conversation controls
`modes.py` -> voice/text/listening modes
`greeting.py` -> greetings/identity

The skills call extracted implementation methods during the first migration. Later you can make them truly independent services with dependency injection.

## 7. The safest migration sequence
1. Run the modular copy and make sure basic commands work.
2. Keep `legacy_actions.py` as fallback.
3. Move calculator first.
4. Then timer -> reminder -> weather -> system -> media -> browser/navigation -> documents -> notes -> conversion/info/translation -> memory/conversation -> modes.
5. After every move, run `pytest -q` and a small manual smoke-test list.
6. Only after direct commands are stable, remove their equivalent blocks from `handle_action()`.
7. Then make the hybrid router responsible for the remaining ambiguous natural-language requests.

## 8. GUI rule
The GUI should call `core/api.py` or `assistant.dispatch_command()`.
It should NEVER contain weather, Ollama, SQLite, Whisper, timer or media implementation.

Good:
`GUI -> AssistantAPI -> Router -> Skill -> Service`

Bad:
`GUI button -> directly call requests / sqlite / subprocess / Whisper`

## 9. Future target
Input -> wake/VAD/STT -> hybrid router -> permission check -> skill/service OR model -> response manager -> GUI/TTS -> memory/logging.
