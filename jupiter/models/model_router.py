import os
import time


class ModelRouter:
    """Choose a model from the actual installed Ollama models.

    The router is intentionally conservative on a 6 GB GPU: normal conversation
    stays on the 4B general model; the 7B coding model is used only when it is
    installed and the request clearly needs coding. Specialist routing is OFF by default (a 7B model swap
    costs 10-20 s on 6 GB); set JUPITER_ENABLE_CODER=1 to enable it.
    """

    GENERAL_MODEL = os.environ.get("JUPITER_GENERAL_MODEL", os.environ.get("JUPITER_MODEL", "qwen3.5:4b"))
    CODING_MODEL = os.environ.get("JUPITER_CODE_MODEL", "qwen2.5-coder:7b")
    ENABLE_CODER = os.environ.get("JUPITER_ENABLE_CODER", "0").strip().lower() not in {"0", "false", "no", "off"}

    CODING_HINTS = (
        "write code", "write a program", "generate code", "fix this code", "debug this code",
        "debug my code", "refactor this code", "code review",
        "python code", "java code", "c++ code", "javascript code", "compile error", "stack trace",
        "traceback", "syntax error", "runtime error", "bug in my code", "class in python",
        "function in python", "leetcode", "hackerrank", "programming problem",
    )

    def __init__(self, assistant):
        self.assistant = assistant
        self._available = set()
        self._checked_at = 0.0

    def available_models(self, ttl: float = 60.0):
        now = time.time()
        if now - self._checked_at < ttl:
            return self._available
        try:
            base = self.assistant.ollama_url.rsplit("/api/", 1)[0]
            r = self.assistant.http.get(base + "/api/tags", timeout=2.5)
            if r.ok:
                self._available = {m.get("name", "") for m in r.json().get("models", [])}
                self._checked_at = now
        except Exception:
            # Keep the last known set. An unavailable Ollama should not make
            # every command wait for model discovery.
            self._checked_at = now
        return self._available

    @staticmethod
    def _present(models, wanted: str) -> bool:
        return wanted in models or f"{wanted}:latest" in models

    def choose(self, text: str) -> str:
        models = self.available_models()
        general = self.GENERAL_MODEL
        if not self._present(models, general) and models:
            # Prefer the configured model even when tags were returned without
            # a matching entry; the LLM layer will provide a useful 404 message.
            return general
        t = text.lower().strip()
        needs_code = self.ENABLE_CODER and any(h in t for h in self.CODING_HINTS)
        if needs_code and self._present(models, self.CODING_MODEL):
            return self.CODING_MODEL
        return general

    def profile(self, text: str = "") -> dict:
        model = self.choose(text)
        return {
            "model": model,
            "is_coding": model == self.CODING_MODEL,
            "coder_enabled": self.ENABLE_CODER,
            "installed": sorted(self.available_models()),
        }
