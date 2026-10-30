# JUPITER Ultimate v3 -> v4 fix report

## Critical bugs found in the v3 upload (all fixed here)
1. **Startup crash** - `models/llm.py`: `_get_model_router`, `_select_model`, `_generation_options` and `think` were de-indented out of
   `LLMMixin`, which turned `think_stream` and `_warm_up_ollama` into functions nested inside `think()`. Result: `Jupiter()` raised
   `AttributeError: _warm_up_ollama` at launch, and no non-skill sentence could reach the LLM. (compileall and the old tests did not notice.)
2. **Silent rollback of earlier fixes** - 14 files were an OLDER snapshot than your corrected_v3: audio/speech.py, audio/stt.py, common.py,
   services/{documents,media,notes_clipboard,web}.py, skills/{calculator,conversion,greeting,information,media,system,weather}.py.
   Effects: "JUPITER: None" came back, the greeting skill raised NameError (GREETING_REPLIES), the `open file C:\path` and Chrome/VS Code lookup
   fixes were lost, calculator false positives returned, vocabulary prompts fired on media commands, and `@staticmethod` was removed from 6 helpers
   -> TypeError in document search and unit conversion. All restored from corrected_v3.
3. **tests/test_regressions.py had been deleted** (16 tests that guard exactly the above). Restored.
4. **check_mapping.py / self_check.py gave a false PASS** because they counted nested functions as methods. check_mapping now imports the real class
   and checks hasattr. New tests/test_runtime_contract.py builds the assistant against a mock Ollama and exercises skills + blocking + streaming LLM paths.

## Optimisations / accuracy changes
- Vision look() now passes the same num_ctx (4096) as chat, so Ollama never reloads the model between chat and screen analysis.
- Coding-specialist routing is now OPT-IN (JUPITER_ENABLE_CODER=1). On 6 GB a 7B swap costs 10-20 s each way; the hint list no longer matches
  generic phrases such as "implement a ...".
- "analyze image <file>" only fires when the phrase ends in a real image path (previously "describe the image on my screen" could be misrouted).
  It is also checked before the debug pattern.

## Kept from v3 (reviewed, working)
HealthSkill, active-window query, image-file analysis, workflow step-failure reporting, ModelRouter model discovery, richer HealthChecker.

## Verify on your laptop
python self_check.py --doctor      (compile + 115 tests + method check + doctor.py)

## Later additions
- Voice tasks: "add a task ...", "what are my tasks", "complete task ..." (ProductivityService was never attached to Jupiter; now it is).
  The briefing and GUI memory panel read these tasks.
- Debug routing: "what's wrong in the code on my screen", "find the bug in my code", "why is my code not working", "what does this error mean".
- Tests no longer touch your real memory database: set JUPITER_DATA_DIR to relocate data (tests use a temp folder).
  NOTE: an earlier copy of this zip shipped with a test jupiter_memory.db - use this copy, or delete jupiter/data/jupiter_memory.db.

## GUI modes (everything is now doable from `python gui_main.py`)
Left panel -> INPUT: **Voice / Text**, LISTENING: **Always on / Push-to-talk / Sleep**, and **Auto-return to voice** (tick = one typed command then back to
the mic; untick = pinned text mode). The same modes still work by voice ("text mode", "stay in text mode", "auto voice", "walkie talkie", "always listening",
"sleep"), and the buttons follow whatever you say. The mic now runs on its own thread, so typing is never blocked while JUPITER is listening.
- Voice + Always on: mic open continuously (anything heard while JUPITER is thinking/speaking is discarded).
- Push-to-talk: mic stays closed; the mic button, Enter or Space listens once.
- Sleep: only a wake phrase is accepted ("hey jupiter ..."); pressing the mic button also wakes it.
- Text: mic closed. The mic button still lets you speak a single command.
Tests: jupiter/tests/test_gui_modes.py (headless Qt, real mode logic with a scripted microphone).

## Interrupting JUPITER ("stop", "enough")
Voice: "stop", "enough", "that's enough", "be quiet", "quiet", "shut up", "okay Jupiter stop", "stop talking/it/now", "please stop" cut the speech
mid-sentence. This is the barge-in monitor: it runs only while JUPITER is speaking, only in Voice + Always-on mode (not Text / Push-to-talk / Sleep),
and "stop the timer" / "stop playing music" are NOT treated as interrupts. Anywhere: the Stop button or Esc in the GUI.
GUI fixes: a stale Stop/Esc no longer silences the next alert (cleared at the start of every turn); the mic only reopens after speech has finished.
