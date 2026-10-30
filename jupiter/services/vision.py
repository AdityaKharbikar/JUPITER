"""Screen vision + small text-reasoning helper, all through the local Ollama server.

Speed design (RTX 3050 6 GB):
  * Qwen3.5 is natively multimodal on Ollama, so by default the SAME model that
    answers chat also looks at the screen -> no second model to load/evict.
    (Falls back to qwen3-vl:2b only if the main model has no vision.)
  * IMPORTANT: every call must use the same Ollama options that chat uses
    (we never pass num_ctx here) - changing num_ctx makes Ollama reload the model.
  * Screenshots are downscaled and sent as JPEG; the active window is cropped when
    possible (fewer image tokens = faster and sharper text).
"""
import base64
import io
import os
import re
import sys
import time

FALLBACK_VISION_MODEL = "qwen3-vl:2b"


class VisionError(Exception):
    pass


def _foreground_rect(own_pid: int):
    """(left, top, right, bottom) of the active window on Windows, or None."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == own_pid:                 # that's JUPITER's own window
            return None
        r = wintypes.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
        if w < 300 or h < 200:
            return None
        return max(r.left, 0), max(r.top, 0), r.right, r.bottom
    except Exception:
        return None


class VisionService:
    def __init__(self, assistant):
        self.a = assistant
        self.last_latency = 0.0
        self._model = None
        self._base = assistant.ollama_url.rsplit("/api/", 1)[0]

    # ---- model selection -----------------------------------------------
    @property
    def chat_model(self) -> str:
        from ..config import LLM_MODEL
        return LLM_MODEL

    def has_vision(self, model: str) -> bool:
        try:
            r = self.a.http.post(f"{self._base}/api/show", json={"model": model}, timeout=4)
            if r.status_code == 200:
                caps = r.json().get("capabilities")
                if caps is not None:
                    return "vision" in caps
        except Exception:
            pass
        return False

    @property
    def model(self) -> str:
        if self._model:
            return self._model
        forced = os.environ.get("JUPITER_VISION_MODEL")
        if forced:
            self._model = forced
        elif self.has_vision(self.chat_model):
            self._model = self.chat_model
        else:
            self._model = FALLBACK_VISION_MODEL
        return self._model

    @property
    def same_model(self) -> bool:
        return self.model == self.chat_model

    # ---- capture ---------------------------------------------------------
    def capture(self, max_width: int = 1280, active_window: bool = False) -> str:
        try:
            from PIL import ImageGrab
        except ImportError as exc:
            raise VisionError("Pillow is missing. Run: pip install pillow") from exc
        img = None
        if active_window:
            rect = _foreground_rect(os.getpid())
            if rect:
                try:
                    img = ImageGrab.grab(bbox=rect)
                except Exception:
                    img = None
        if img is None:
            img = ImageGrab.grab()
        if img.width > max_width:
            img = img.resize((max_width, int(img.height * max_width / img.width)))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=90)
        return base64.b64encode(buf.getvalue()).decode("ascii")

    # ---- model calls -----------------------------------------------------
    def _chat(self, payload: dict, timeout=(5, 150)) -> str:
        try:
            r = self.a.http.post(self.a.ollama_url, json=payload, timeout=timeout)
            if r.status_code == 400 and "think" in payload:     # model without thinking support
                payload = {k: v for k, v in payload.items() if k != "think"}
                r = self.a.http.post(self.a.ollama_url, json=payload, timeout=timeout)
        except Exception as exc:
            raise VisionError("I can't reach Ollama. Is it running?") from exc
        if r.status_code == 404:
            m = payload["model"]
            raise VisionError(f"The model {m} is not installed. Run: ollama pull {m}")
        if r.status_code != 200:
            raise VisionError(f"Ollama returned error {r.status_code}.")
        text = r.json().get("message", {}).get("content", "")
        return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()

    def look(self, prompt: str, num_predict: int = 350, max_width: int = 1280,
             active_window: bool = False, system: str | None = None) -> str:
        t0 = time.perf_counter()
        img = self.capture(max_width=max_width, active_window=active_window)
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt, "images": [img]})
        out = self._chat({
            "model": self.model, "stream": False, "think": False,
            "keep_alive": "30m" if self.same_model else "45s",
            "messages": msgs,
            "options": {"temperature": 0.2, "num_predict": num_predict, "num_ctx": 4096},
        })
        self.last_latency = time.perf_counter() - t0
        return out


    def analyze_image_file(self, path: str, prompt: str, max_width: int = 1600) -> str:
        """Analyze a user-selected local image without writing another copy to disk."""
        from pathlib import Path
        try:
            from PIL import Image
        except ImportError as exc:
            raise VisionError("Pillow is missing. Run: pip install pillow") from exc
        p = Path(path).expanduser()
        if not p.is_file():
            raise VisionError("That image file does not exist.")
        if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
            raise VisionError("I can analyse PNG, JPG, JPEG, WEBP, BMP or GIF images.")
        try:
            img = Image.open(p).convert("RGB")
        except Exception as exc:
            raise VisionError("I couldn't open that image.") from exc
        if img.width > max_width:
            img = img.resize((max_width, int(img.height * max_width / img.width)))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")
        t0 = time.perf_counter()
        out = self._chat({
            "model": self.model, "stream": False, "think": False,
            "keep_alive": "15m" if self.same_model else "30s",
            "messages": [{"role": "user", "content": prompt, "images": [encoded]}],
            "options": {"temperature": 0.2, "num_predict": 400, "num_ctx": 4096},
        })
        self.last_latency = time.perf_counter() - t0
        return out

    def reason(self, system: str, user: str, num_predict: int = 500) -> str:
        """Text-only local reasoning. Use the model router so coding uses the
        specialist only when it is actually needed and other clipboard tasks stay fast."""
        router = getattr(self.a, "model_router", None)
        if router is not None:
            model = router.choose(user)
        else:
            model = self.chat_model
        self.a.last_model = model
        return self._chat({
            "model": model, "stream": False, "think": False, "keep_alive": "15m",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": 0.25 if model != self.chat_model else 0.3, "num_predict": num_predict, "num_ctx": 4096},
        })
