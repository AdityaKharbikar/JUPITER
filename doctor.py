"""JUPITER doctor - run this BEFORE you present:   python doctor.py   (add --quick to skip the speed tests)

Checks dependencies, Ollama, models (incl. vision), GPU, microphone, screenshot, clipboard,
then measures real latency of chat and screen-vision so there are no surprises on stage.
Deliberately does NOT import the jupiter package, so it still runs when something is broken.
"""
import base64
import importlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
FAILS = WARNS = 0


def out(level, msg, fix=""):
    global FAILS, WARNS
    tag = {"ok": "[ OK ]", "warn": "[WARN]", "fail": "[FAIL]", "info": "[ .. ]"}[level]
    if level == "fail":
        FAILS += 1
    elif level == "warn":
        WARNS += 1
    print(f"{tag} {msg}" + (f"\n         -> {fix}" if fix else ""))


def load_config():
    path = os.path.join(ROOT, "jupiter", "config.py")
    spec = importlib.util.spec_from_file_location("jupiter_config", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def http(url, payload=None, timeout=5):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main():
    quick = "--quick" in sys.argv
    print("=" * 56 + "\n JUPITER DOCTOR\n" + "=" * 56)
    out("ok" if sys.version_info >= (3, 10) else "fail", f"Python {sys.version.split()[0]}", "Use Python 3.10 or newer")

    # --- python packages
    pkgs = [("faster_whisper", "faster-whisper", True), ("sounddevice", "sounddevice", True), ("numpy", "numpy", True),
            ("piper", "piper-tts", True), ("requests", "requests", True), ("psutil", "psutil", True),
            ("pyperclip", "pyperclip", True), ("PIL", "pillow", True), ("PySide6", "PySide6", True),
            ("pyautogui", "pyautogui", False)]
    for mod, pipname, required in pkgs:
        try:
            importlib.import_module(mod)
            out("ok", f"package {pipname}")
        except Exception as exc:
            out("fail" if required else "warn", f"package {pipname} unavailable ({type(exc).__name__})",
                f"pip install {pipname}" + ("" if required else "   (needed only for desktop-control commands)"))

    cfg = load_config()
    base = cfg.OLLAMA_URL.rsplit("/api/", 1)[0]
    llm = cfg.LLM_MODEL


    # --- 3D Explainer + webcam (does not import the jupiter package)
    web = os.path.join(ROOT, "jupiter", "explainer", "web")
    out("ok" if os.path.exists(os.path.join(web, "viewer.js")) and os.path.exists(os.path.join(web, "template.html")) else "fail",
        "3D viewer files present (offline, no internet needed)", "re-extract the upgraded zip")
    try:
        importlib.import_module("PySide6.QtWebEngineWidgets")
        out("ok", "QtWebEngine available (3D view opens inside JUPITER)")
    except Exception as exc:
        out("warn", f"QtWebEngine unavailable ({type(exc).__name__}) - 3D views will open in Chrome/Edge instead", "pip install --upgrade PySide6")
    try:
        qm = importlib.import_module("PySide6.QtMultimedia")
        n = len(qm.QMediaDevices.videoInputs())
        out("ok" if n else "warn", f"webcams found by Qt: {n}", "" if n else "plug in / enable the webcam (Windows Settings > Privacy > Camera)")
    except Exception as exc:
        out("warn", f"QtMultimedia unavailable ({type(exc).__name__}) - webcam preview off; 'Identify an image file' still works")
    try:
        sys.path.insert(0, ROOT)
        from jupiter.explainer import library
        out("ok", f"{len(library.catalog())} curated 3D models load: " + ", ".join(library.topics()))
    except Exception as exc:
        out("fail", f"curated model library failed to load: {exc}")

    # --- ollama + models
    names = set()
    try:
        names = {m["name"] for m in http(base + "/api/tags").get("models", [])}
        out("ok", f"Ollama reachable at {base}")
    except Exception:
        out("fail", "Ollama is not reachable", "Start it:  ollama serve   (or open the Ollama app)")
    have = lambda n: n in names or f"{n}:latest" in names
    vision_model = os.environ.get("JUPITER_VISION_MODEL")
    if names:
        if have(llm):
            out("ok", f"chat model {llm} installed")
        else:
            out("fail", f"chat model {llm} missing", f"ollama pull {llm}")
        if not vision_model:
            try:
                caps = http(base + "/api/show", {"model": llm}).get("capabilities", [])
                vision_model = llm if "vision" in caps else "qwen3-vl:2b"
                out("ok" if "vision" in caps else "warn",
                    f"{llm} " + ("has native vision -> screen analysis needs no second model" if "vision" in caps
                                else "has NO vision -> will use qwen3-vl:2b for screen analysis"),
                    "" if "vision" in caps else "ollama pull qwen3-vl:2b")
            except Exception:
                vision_model = llm
        if vision_model != llm and not have(vision_model):
            out("fail", f"vision model {vision_model} missing", f"ollama pull {vision_model}")

    # --- GPU
    if shutil.which("nvidia-smi"):
        try:
            o = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
            out("ok", f"GPU: {o}")
        except Exception:
            out("warn", "nvidia-smi failed")
    else:
        out("warn", "nvidia-smi not found - GPU stats in the GUI will show n/a")

    # --- microphone / audio out
    try:
        import sounddevice as sd
        devs = sd.query_devices()
        ins = [d["name"] for d in devs if d["max_input_channels"] > 0]
        outs = [d["name"] for d in devs if d["max_output_channels"] > 0]
        out("ok" if ins else "fail", f"microphones: {len(ins)}" + (f" (default: {sd.query_devices(kind='input')['name']})" if ins else ""),
            "" if ins else "Connect a microphone / enable it in Windows privacy settings")
        out("ok" if outs else "fail", f"speakers: {len(outs)}")
    except Exception as exc:
        out("warn", f"audio check skipped ({type(exc).__name__})")

    # --- screenshot + clipboard
    try:
        from PIL import ImageGrab
        im = ImageGrab.grab()
        out("ok", f"screenshot works ({im.width}x{im.height})")
    except Exception as exc:
        out("fail", f"screenshot failed ({type(exc).__name__}: {exc})", "pip install pillow; on Linux ImageGrab needs a display")
    try:
        import pyperclip
        pyperclip.copy("jupiter-doctor"); ok = pyperclip.paste() == "jupiter-doctor"
        out("ok" if ok else "warn", "clipboard read/write")
    except Exception as exc:
        out("warn", f"clipboard unavailable ({type(exc).__name__})")

    # --- speed tests
    if names and not quick:
        print("-" * 56 + "\n Speed test (first run includes model load; run twice for real numbers)\n" + "-" * 56)
        try:
            t0 = time.perf_counter()
            http(base + "/api/chat", {"model": llm, "stream": False, "think": False, "keep_alive": "30m",
                                     "messages": [{"role": "user", "content": "Say hello in five words."}],
                                     "options": {"num_predict": 24}}, timeout=180)
            dt = time.perf_counter() - t0
            out("ok" if dt < 8 else "warn", f"chat reply in {dt:.1f}s", "" if dt < 8 else "Slow: close GPU-heavy apps, or try a smaller model")
        except Exception as exc:
            out("fail", f"chat test failed: {exc}")
        if vision_model and have(vision_model):
            try:
                from PIL import Image, ImageDraw
                img = Image.new("RGB", (900, 260), "white")
                d = ImageDraw.Draw(img)
                d.text((30, 40), "def f(x):\n    return 10 / x\nprint(f(0))", fill="black")
                d.text((30, 150), "ZeroDivisionError: division by zero", fill="red")
                img = img.resize((1800, 520))
                buf = io.BytesIO(); img.save(buf, format="JPEG", quality=90)
                t0 = time.perf_counter()
                r = http(base + "/api/chat", {"model": vision_model, "stream": False, "think": False, "keep_alive": "30m",
                                              "messages": [{"role": "user", "content": "What error message is shown? Answer briefly.",
                                                            "images": [base64.b64encode(buf.getvalue()).decode()]}],
                                              "options": {"num_predict": 60}}, timeout=240)
                dt = time.perf_counter() - t0
                txt = r.get("message", {}).get("content", "")
                read_ok = "zero" in txt.lower()
                out("ok" if read_ok else "warn", f"vision read the test error: {'yes' if read_ok else 'NO'}  ({dt:.1f}s)  -> {txt.strip()[:80]!r}")
            except Exception as exc:
                out("fail", f"vision test failed: {exc}")

    print("=" * 56)
    print(f" Result: {FAILS} failure(s), {WARNS} warning(s)")
    print(" Tip: set  OLLAMA_FLASH_ATTENTION=1  and  OLLAMA_KV_CACHE_TYPE=q8_0  (Windows env vars), then restart Ollama,\n"
          "      to cut VRAM use on a 6 GB card.")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
