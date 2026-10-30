# JUPITER demo script (about 5 minutes)

Rule: never fake a result. If something fails, say so and use the fallback - an honest fallback looks professional.

## Demo 1 - Universal Explainer (curated)
**Say / type:** "Show me how a car engine works"   (alternative: "Explode a desktop computer and explain its components")
**On screen:** progress card ticks -> 3D window opens, parts fly apart (14 parts), labels, dashed connection lines, pistons and crankshaft move.
Hover a part = tooltip; click **Pistons** = what it does + what it connects to; press **Assembly** (Space) = parts reassemble one by one with captions.
**Shows:** intent routing -> deterministic Python layout/rendering of a hand-built library, offline, loads in milliseconds (pre-generated).
**If it fails:** the same page opens in Chrome/Edge (`set JUPITER_VIEWER=browser`), or open `data/explainer/html/cur_car_engine.html` directly.
**Tell the evaluator:** "The model library is plain data files - one per topic. The 3D viewer is my own WebGL code, so it works with no internet."

## Demo 2 - Real-world vision
**Do:** press **Webcam identify** -> **Start camera** (red CAMERA LIVE appears) -> hold a mouse / bottle / phone -> **Capture & identify**.
**On screen:** frame freezes, camera switches off, object name + confidence appear. Then press **Show internal components**.
**Shows:** explicit-consent capture, local multimodal model (no cloud), recognition connected to the explainer.
**If it fails / low confidence:** it says so; type the name in the box (or use **Identify an image file…** with a saved photo) and continue. Phone and keyboard are the safest objects (both are in the library).
**Tell the evaluator:** "The vision model's answer is shown with its confidence; if it is not sure it says unknown instead of guessing."

## Demo 3 - Unfamiliar topic
**Say / type:** "Regenerate coffee machine"  (forces a live generation; plain "show me a 3d model of a coffee machine" loads the cache you prepared)
**On screen:** left card lists components appearing as the model streams them ("• Water tank", "• Heating element"...), then an amber **AI-GENERATED · APPROXIMATE** view with generic shapes.
**Shows:** LLM supplies only structured JSON (validated, repaired once if malformed); Python does layout and rendering; the app never executes model output.
**If it fails** (Ollama off / bad JSON): JUPITER says exactly why and offers the built-in models; open the cached topic with "show me a 3d model of a washing machine".
**Tell the evaluator:** "The AI is used where knowledge is needed; deterministic code is used where reliability is needed - and I show which is which."

## Closing numbers
Say "performance report" - it reads the measured medians (cache hit vs miss, first output, total) from `logs/metrics.jsonl`. Quote only these real numbers or `BENCHMARK_REPORT.md`.

## Engineering explanation in 30 seconds
Command -> skill router -> explainer engine (curated library | cache | LLM JSON) -> validated spec -> deterministic layout -> self-contained WebGL page -> viewer window.
Every step is timed and logged; failures are reported, not hidden.
