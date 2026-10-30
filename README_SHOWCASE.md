# JUPITER Showcase Pack v2

## Install
1. Unzip OVER your project root. It adds files and replaces: `jupiter/skills/registry.py`, `jupiter/core/assistant.py`, `jupiter/ui/desktop.py`, `requirements.txt`.
2. `pip install -r requirements.txt`
3. `python doctor.py`     <- checks everything + measures real speed. Fix every [FAIL] before presenting.
4. `python gui_main.py`   (Command Center)   or   `python main.py`  (console voice mode)
5. `python -m pytest jupiter/tests -q`

Vision needs NO extra download if your main model is `qwen3.5:4b` (it is natively multimodal on Ollama; doctor.py confirms).

## Speed settings (RTX 3050 6 GB) - set as Windows environment variables, then restart Ollama
OLLAMA_FLASH_ATTENTION=1      OLLAMA_KV_CACHE_TYPE=q8_0      OLLAMA_MAX_LOADED_MODELS=1
If VRAM is tight (GUI shows it): JUPITER_WHISPER=base  (smaller speech model)

## Voice / typed commands
| Say | Does |
|---|---|
| look at my screen / what is on my screen / what am I looking at | describes the screen |
| on my screen, <any question> | answers about what's visible |
| what's wrong with my code / explain this error | reads code+error on the ACTIVE window, explains, gives fix |
| copy the fix | corrected code -> clipboard |
| run the fix / test the fix | shows code, asks CONFIRM, runs in sandbox (10 s limit), reads result |
| explain / simplify / fix / rewrite / proofread / translate ... my clipboard | AI actions on copied text |
| explain this question / diagram, summarize this page, read my screen | study / diagram / summary / OCR |
| give me my briefing | time-of-day greeting, CPU/RAM, battery, tasks, next reminder, memory |
| start coding / study / presentation mode | multi-step workflow from data/workflows.json |
| end study mode / exit coding mode / end the mission | ends the workflow, returns to normal, cancels only the timer that workflow started |
| show desktop, switch window, snap left/right, maximize window, new tab, close tab, refresh | desktop control |
| scroll up/down, press enter/escape/tab/arrows | desktop control (navigation keys only) |
| take a screenshot | saved in C:\Users\VICTUS\OneDrive\Pictures\Screenshots (change with JUPITER_SCREENSHOT_DIR) |
| close this window, lock the computer | ask for CONFIRM first |
| type out <text> | pastes the text into the focused window after a 3 s countdown |
| confirm / cancel | answer a pending approval (also buttons in the GUI) |
Proactive (no command): RAM >= 88%, CPU >= 92% sustained, battery <= 20% unplugged, break reminder after 90 min of continuous use.

## GUI
Push-to-talk: Enter or Space (either one) = listen once; Esc = stop speaking. INPUT/LISTENING panel = voice, text, always-on, push-to-talk, sleep. Quick buttons = reliable fallback if the mic misbehaves.
The window is excluded from screenshots on Windows 10 2004+ (set JUPITER_SHOW_IN_CAPTURE=1 to disable).

## Safety model
- Desktop control = fixed list of named actions, no free-form "do anything".
- Risky actions (run code, close window, lock) need explicit confirmation; expires after 60 s.
- Code runner: AST scan blocks network/subprocess/file-delete/eval, runs `python -I` in data/sandbox with 10 s limit.
  This is a guard-rail, not a hardened sandbox: always read the code it shows you.
- Workflows come only from your JSON file and use an allow-list of actions.

## Optional
JUPITER_VISION_MODEL=qwen3-vl:2b   force a separate vision model
JUPITER_CODE_MODEL=qwen2.5-coder:7b   use a coding model for clipboard/debug reasoning (slower on 6 GB)

## Manual edits (only if you cannot overwrite the files)
registry.py: import and put `ConfirmSkill(),BriefingSkill(),VisionSkill(),DeveloperSkill(),ClipboardAISkill(),WorkflowSkill(),ControlSkill(),` at the START of default_skills().
assistant.py: `import time`; `from ..services.watchdog import Watchdog`; after `self.start_scheduler()` add
`self.current_mode="normal"; self.watchdog=Watchdog(self); self.watchdog.start()`; at the top of dispatch_command's body add the
`_last_turn_ts` / `_streak_start` lines (see the shipped file).


## JUPITER High-Impact Features (v3)
- **Multimodal screen intelligence:** screen description, screen Q&A, code/error diagnosis, diagram/study explanation, and local image-file analysis using a vision-capable Ollama model.
- **Mission/workflow mode:** coding, study, and presentation workflows composed from an allow-list rather than arbitrary autonomous actions.
- **Proactive watchdog:** local RAM/CPU/battery/break monitoring with cooldowns; no LLM call is used while idle.
- **Developer copilot:** corrected code extraction, copy-to-clipboard, and confirmation-gated sandbox execution with a time limit.
- **Desktop controls:** named window/tab/navigation actions, safe key presses, screenshots, active-window awareness, and confirmation for lock/close-window.
- **Health & model routing:** local service readiness checks and automatic general/coding model selection.
- **Performance design:** compact context, short spoken output, keep-alive, streaming, lazy optional features, and one-model-at-a-time specialist routing.
