"""Glue between the assistant and the explainer: owns the engine + metrics, speaks results, opens the viewer."""
from __future__ import annotations

import os
import threading
import webbrowser
from pathlib import Path

from ..core.hooks import emit
from ..core.metrics import Metrics
from .camera import CameraError, capture_with_opencv, identify, search_url
from .engine import BuildResult, ExplainerEngine


VIEW_PARTS: list = []      # lower-case part names of the model on screen (for "select <part>")
VIEW_ACTIVE = False       # becomes True once a 3D model has been opened (enables voice viewer commands)


class ExplainerService:
    def __init__(self, assistant):
        self.a = assistant
        data_dir = getattr(assistant, "data_dir", None) or os.path.join(os.getcwd(), "data")
        logs = Path(data_dir).parent / "logs"
        self.metrics = Metrics(logs / "metrics.jsonl")
        model = getattr(assistant, "model_router", None)
        model = model.GENERAL_MODEL if model else os.environ.get("JUPITER_MODEL", "qwen3.5:4b")
        self.engine = ExplainerEngine(assistant.ollama_url, model, data_dir, self.metrics, http=getattr(assistant, "http", None))
        self.last_topic = ""
        self.last_html = ""
        self._pregen_started = False

    # ---- startup ---------------------------------------------------------
    def start_pregen(self):
        """Pre-build every curated model in the background so the first request is instant."""
        if self._pregen_started:
            return
        self._pregen_started = True
        threading.Thread(target=self.engine.pregenerate, name="explainer-pregen", daemon=True).start()

    # ---- progress -> GUI ---------------------------------------------------
    def _progress(self, stage, frac, detail):
        emit(self.a, "progress", f"{frac:.2f}|{stage}|{detail}")

    # ---- main entry ----------------------------------------------------------
    def explain(self, topic: str, force_new=False) -> BuildResult:
        a, who = self.a, getattr(self.a, "user_name", "sir")
        curated = self.engine.match_curated(topic) is not None and not force_new
        emit(a, "state", "THINKING")
        emit(a, "progress", f"0.02|start|Request: {topic}")
        if curated:
            a.speak(f"Opening the {topic} model, {who}.", wait=False)
        else:
            a.speak(f"That's not in my built-in library, {who}. I'll ask my language model for the components and build an approximate view.", wait=False)
        res = self.engine.build(topic, progress=self._progress, force_new=force_new)
        if not res.ok:
            emit(a, "progress", f"1.00|failed|{res.error}")
            msg = res.error or "I couldn't build that."
            lib = ", ".join(self.engine.curated_topics()[:6])
            a.speak(f"{msg} I can always show my built-in models, for example: {lib}.")
            a._last_full_text = f"{msg}\n\nBuilt-in models: {', '.join(self.engine.curated_topics())}"
            return res
        self.last_topic, self.last_html = topic, res.html_path
        self._open(res)
        names = [p["name"] for p in res.spec["parts"][:4]]
        if res.source == "curated":
            honesty = "This is a hand-built educational model."
        elif res.source == "cache":
            honesty = "This is an AI-generated approximation, loaded from cache."
        else:
            honesty = f"This is an AI-generated approximation, built in {res.seconds:.0f} seconds. Treat it as a sketch, not an accurate model."
        a._last_full_text = (f"**{res.title}** - {res.n_parts} parts ({res.source}, {res.seconds:.2f}s)\n\n{res.spec.get('summary', '')}\n\n"
                             f"Parts: {', '.join(p['name'] for p in res.spec['parts'])}\n\n{honesty}")
        a.speak(f"{res.spec.get('summary', '')} It has {res.n_parts} parts, including {', '.join(names)}. {honesty} "
                f"Hover or click any part to see what it does.")
        return res

    def _open(self, res: BuildResult):
        global VIEW_ACTIVE, VIEW_PARTS
        VIEW_ACTIVE = True
        VIEW_PARTS = [p["name"].lower() for p in res.spec.get("parts", [])]
        emit(self.a, "viewer", f"{res.html_path}|{res.title}")
        if getattr(self.a, "ui_hook", None) is None:           # console mode: use the default browser (Chrome/Edge)
            try:
                webbrowser.open(Path(res.html_path).resolve().as_uri())
            except Exception:
                pass

    def reopen_last(self):
        if not self.last_html or not os.path.exists(self.last_html):
            return False
        emit(self.a, "viewer", f"{self.last_html}|{self.last_topic}")
        if getattr(self.a, "ui_hook", None) is None:
            webbrowser.open(Path(self.last_html).resolve().as_uri())
        return True

    # ---- webcam ---------------------------------------------------------------
    def identify_console(self):
        """Console/voice path: spoken countdown, then ONE frame (user explicitly asked), then identify."""
        a, who = self.a, getattr(self.a, "user_name", "sir")
        a.speak(f"Hold the object up to the camera. Capturing in three seconds, {who}.")
        import time
        time.sleep(3)
        try:
            jpeg = capture_with_opencv(int(os.environ.get("JUPITER_CAMERA", "0")))
            vision_model = self._vision_model()
            t0 = time.perf_counter()
            info = identify(jpeg, a.ollama_url, vision_model, http=getattr(a, "http", None))
            self.metrics.record("vision.identify", model=vision_model, cache_hit=False, total_s=time.perf_counter() - t0,
                                ok=info["object"] != "unknown", detail=info["object"])
        except CameraError as exc:
            a.speak(str(exc))
            return None
        if info["object"] == "unknown":
            a.speak(f"I can't tell what that is, {who}. Try better light, or tell me its name.")
            return info
        self.last_topic = info["object"]
        a.speak(f"I think this is a {info['object']}, with {info['confidence']} confidence. {info['description']} "
                f"Say 'show its internal components' to see inside it.")
        return info

    def _vision_model(self):
        v = getattr(self.a, "vision", None)
        if v is None:
            from ..services.vision import VisionService
            v = self.a.vision = VisionService(self.a)
        return v.model

    def search_online(self, topic):
        webbrowser.open(search_url(topic))
