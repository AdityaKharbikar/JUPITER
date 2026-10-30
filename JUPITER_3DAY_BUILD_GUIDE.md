# JUPITER - Practical 2-3 Day High-Impact Build Guide

## Current verified state
- 74 automated tests pass in the build environment.
- Python compilation passes.
- All 149 methods from `jupiter_try2.py` are accounted for in the modular architecture.
- Runtime hardware checks must still be run on the Windows laptop with `python self_check.py --doctor`.

## High-impact features already integrated
1. Command Center GUI (PySide6)
2. Local screen vision and screen Q&A
3. Local image-file analysis
4. Code/error diagnosis from screen content
5. Corrected-code extraction + clipboard copy
6. Confirmation-gated code sandbox
7. Mission/workflow mode
8. Proactive CPU/RAM/battery/break watchdog
9. Named desktop controls + active-window awareness
10. Health/diagnostics command
11. General-vs-coding model routing
12. Compact context + keep-alive performance tuning

## Recommended laptop model setup
General assistant:
`qwen3.5:4b`

Optional coding specialist:
`qwen2.5-coder:7b`

Vision:
Use `qwen3.5:4b` when Ollama reports vision capability; otherwise install `qwen3-vl:2b`.

Do not keep multiple specialist models intentionally warm at the same time on a 6 GB GPU.

## First run on Windows
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python self_check.py
python self_check.py --doctor
```

Install the general model:
```powershell
ollama pull qwen3.5:4b
```

Optional coding model:
```powershell
ollama pull qwen2.5-coder:7b
```

Optional fallback vision model:
```powershell
ollama pull qwen3-vl:2b
```

## Performance environment variables for the laptop
Set these before restarting Ollama:
```powershell
$env:OLLAMA_FLASH_ATTENTION="1"
$env:OLLAMA_KV_CACHE_TYPE="q8_0"
$env:OLLAMA_MAX_LOADED_MODELS="1"
```

When voice + vision feels too heavy together:
```powershell
$env:JUPITER_WHISPER="base"
```

Coding routing can be disabled without editing source:
```powershell
$env:JUPITER_ENABLE_CODER="0"
```

## Demo commands
- `give me my briefing`
- `look at my screen`
- `what's wrong with my code`
- `copy the fix`
- `run the fix`
- `start coding mode`
- `start study mode`
- `start presentation mode`
- `health check`
- `what app is active`
- `show desktop`
- `take a screenshot`

## Architecture rule
Keep the GUI thin. GUI -> Assistant API -> Router -> Skill -> Service. Never put Ollama, SQLite, Whisper or desktop-control logic directly inside the GUI.

## After the presentation
Continue the modular refactor, then add deeper semantic memory, richer RAG with citations, a proper plugin SDK, guarded visual automation, richer workflow planning, and broader productivity integrations.
