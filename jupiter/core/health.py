import importlib.util
import os
import shutil


class HealthChecker:
    """Runtime health and readiness checks suitable for the GUI and voice mode."""

    def __init__(self, assistant=None):
        self.assistant = assistant

    def check(self):
        checks = {
            "python": True,
            "requests": self._module_or_service("requests"),
            "numpy": self._module_or_service("numpy"),
            "sqlite": self._sqlite_ok(),
        }
        checks["ollama"] = self._ollama_reachable() if self.assistant else False
        checks["whisper"] = self._module_or_service("faster_whisper")
        checks["piper"] = self._module_or_service("piper")
        checks["sounddevice"] = self._module_or_service("sounddevice")
        checks["pyside6"] = self._module_or_service("PySide6")
        checks["pyautogui"] = self._module_or_service("pyautogui")
        return checks

    def model_status(self):
        if not self.assistant:
            return {"installed": [], "general": None, "coding": None}
        try:
            base = self.assistant.ollama_url.rsplit("/api/", 1)[0]
            models = {m.get("name", "") for m in self.assistant.http.get(base + "/api/tags", timeout=2.5).json().get("models", [])}
        except Exception:
            models = set()
        general = getattr(getattr(self.assistant, "model_router", None), "GENERAL_MODEL", None)
        coding = getattr(getattr(self.assistant, "model_router", None), "CODING_MODEL", None)
        return {"installed": sorted(models), "general": general, "coding": coding}

    def report(self):
        checks = self.check()
        models = self.model_status()
        ok = sum(bool(v) for v in checks.values())
        total = len(checks)
        model_ok = bool(models["general"] and any(models["general"] == x or f"{models['general']}:latest" == x for x in models["installed"]))
        parts = [f"Core health is {ok} of {total} checks passing, {self.assistant.user_name}." if self.assistant else f"Core health is {ok} of {total} checks passing."]
        parts.append("Ollama is online." if checks.get("ollama") else "Ollama is offline.")
        parts.append(f"General model {models['general']} is ready." if model_ok else f"General model {models['general'] or 'unknown'} is not confirmed installed.")
        if checks.get("whisper") and checks.get("piper") and checks.get("sounddevice"):
            parts.append("Voice components are installed.")
        else:
            parts.append("One or more voice components are unavailable.")
        return " ".join(parts)

    def _module_or_service(self, name):
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            return False

    def _ollama_reachable(self):
        try:
            import requests
            base = self.assistant.ollama_url.rsplit("/api/", 1)[0]
            return requests.get(base, timeout=2).ok
        except Exception:
            return False

    @staticmethod
    def _sqlite_ok():
        try:
            import sqlite3
            c = sqlite3.connect(":memory:")
            c.execute("SELECT 1").fetchone()
            c.close()
            return True
        except Exception:
            return False
