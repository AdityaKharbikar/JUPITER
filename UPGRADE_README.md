# JUPITER upgrade - 3D Explainer, webcam awareness, performance metrics

## Install (Windows)
1. Unzip over / instead of your old folder. Nothing in your data folder is touched.
2. `pip install -r requirements.txt`   (no new packages are needed - PySide6 already contains the 3D-view and webcam parts)
3. `python doctor.py`  - read the new "3D viewer / QtWebEngine / webcams / curated models" lines.
4. `python gui_main.py`

If the embedded 3D window fails on your machine, JUPITER automatically opens the same page in Chrome/Edge. Force that with `set JUPITER_VIEWER=browser`.

## What is new
| Feature | How to use it | Where it lives |
|---|---|---|
| 3D exploded-view explainer | say/type: "show me how a car engine works", "explode a desktop computer", "visualize a TCP/IP network" | `jupiter/explainer/`, `jupiter/skills/explainer.py` |
| 12 hand-built models | desktop PC, car engine, mechanical keyboard, quadcopter drone, smartphone, electric motor, robotic arm, bicycle, human heart, solar system, TCP/IP, neural network ("what models do you have?") | `jupiter/explainer/library/*.py` (one file each) |
| Any other topic | "show me a 3d model of a coffee machine" -> local LLM returns a strict JSON component list, Python lays it out, honestly labelled *AI-generated / approximate* | `llm.py`, `schema.py`, `layout.py` |
| Concept diagrams | abstract topics (e.g. "visualize how DNS works") become layered, directed flow diagrams instead of fake objects | `layout.py` |
| Webcam | button **Webcam identify** (or say "open the webcam" / "what is this object") -> Start camera -> Capture & identify -> Explain / Show internal components / Find info online | `jupiter/ui/explainer_ui.py`, `explainer/camera.py` |
| Progress + status | left panel **3D EXPLAINER** card shows live stages and the components as the model streams them | `ui/explainer_ui.py` |
| Performance | say "performance report" or run `python -m jupiter.explainer.benchmark --llm` | `core/metrics.py`, `logs/metrics.jsonl` |
| Caching | curated models are pre-built at startup; generated models are cached in `data/explainer/cache` ("regenerate X" forces a fresh one) | `engine.py` |

Viewer controls: drag = rotate, wheel = zoom, right-drag = pan, hover = tooltip, click = details + connections, slider = explode,
**Assembly** button (or Space) = step-by-step assembly with captions, R auto-rotate, L labels, X x-ray, I isolate selected part.

## Files changed in your project (everything else is identical)
- `jupiter/skills/registry.py` - registers `ExplainerSkill` (priority just after Confirm, before Vision)
- `jupiter/core/assistant.py` - 5 lines at the end of `__init__`: start background pre-generation
- `jupiter/ui/desktop.py` - new signals, hook kinds (`viewer`, `camera`, `progress`), 5 quick buttons, explainer card, WebEngine flags
- `doctor.py`, `requirements.txt` - new checks / notes
New: `jupiter/explainer/**`, `jupiter/skills/explainer.py`, `jupiter/core/metrics.py`, `jupiter/ui/explainer_ui.py`, `jupiter/tests/test_explainer.py`.

## Before you present (10 minutes)
1. `ollama serve` running, `ollama pull qwen3.5:4b` done (it is also the vision model).
2. `python -m jupiter.explainer.pregen "coffee machine,washing machine"`  - caches your fallback generated topics.
3. `python -m jupiter.explainer.benchmark --llm`  - real numbers for YOUR laptop, saved to `BENCHMARK_REPORT.md`.
4. `python -m jupiter.explainer.camera` - grabs one test frame (needs `pip install opencv-python`; only for this check; delete `camera_test.jpg`).
5. Run all three demos in `DEMO_SCRIPT.md` once.

## Honest limitations
- Curated models are hand-built, stylised educational models - **not** engineering CAD. Generated models are rough sketches built from an LLM's list of parts; the label says so and the viewer never hides that.
- Object recognition quality is whatever your local vision model gives (Qwen3.5 4B). JUPITER shows the model's confidence, says "unknown" instead of guessing, and lets you correct the name.
- Nothing is sent to any cloud service. The webcam is off until you press **Start camera**, a red *CAMERA LIVE* marker is shown, it is switched off right after the capture, and frames are never saved.
- No API keys, no paid services.

## Verified vs not verified (please read)
Verified in my build environment: all 12 models render in a real WebGL browser (headless Chromium) without errors; hover, click, explode and assembly were exercised;
the generator, JSON repair, retry, cache, metrics and honest-failure paths run against a fake Ollama server; routing does not hijack your existing commands
(your 160 existing + new tests pass apart from 2 that need `pyperclip` / a Windows-only fixture, which fail identically on the original zip).
**Not** verified (no Windows machine, GPU, webcam, PySide6 or Ollama here): the Qt windows (viewer window, webcam dialog, progress card), the real webcam, real Qwen output quality, and the speed numbers on your laptop.
`doctor.py` and the benchmark are there so you can check these yourself before the presentation.
