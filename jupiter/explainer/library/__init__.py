"""Curated 3D models. One small file per topic - add a new model by creating a file with TOPIC, ALIASES and build(),
then listing its module name in MODULES below."""
from __future__ import annotations

import difflib
import importlib
import re

MODULES = [
    "desktop_pc", "car_engine", "mechanical_keyboard", "quadcopter_drone", "smartphone", "electric_motor",
    "robotic_arm", "bicycle", "human_heart", "solar_system", "tcp_ip", "neural_network",
]

_FILLER = {"a", "an", "the", "my", "this", "that", "simple", "basic", "modern", "typical", "whole", "entire", "complete", "full",
           "internal", "internals", "inside", "of", "its", "our", "your", "3d", "model", "diagram", "structure", "parts",
           "components", "component", "working", "how", "works", "work", "is", "are", "does", "do"}
_cache: dict = {}


def _mod(name):
    if name not in _cache:
        _cache[name] = importlib.import_module(f"{__name__}.{name}")
    return _cache[name]


def normalise(text: str) -> str:
    words = re.findall(r"[a-z0-9+]+", (text or "").lower())
    return " ".join(w for w in words if w not in _FILLER)


def catalog():
    out = []
    for name in MODULES:
        try:
            m = _mod(name)
        except Exception:                      # one broken model file must never take down the others
            continue
        out.append({"key": name, "topic": m.TOPIC, "aliases": [normalise(a) for a in m.ALIASES + [m.TOPIC]]})
    return out


def find(topic: str):
    """Best curated model key for a topic, or None.  Conservative on purpose: 'quantum computer' must not match 'computer'."""
    t = normalise(topic)
    if not t:
        return None
    best, score = None, 0.0
    for entry in catalog():
        for alias in entry["aliases"]:
            if not alias:
                continue
            if alias == t:
                s = 1.0
            elif " " in alias and re.search(rf"\b{re.escape(alias)}\b", t):
                s = 0.9 + min(len(alias), 40) / 1000
            else:
                r = difflib.SequenceMatcher(None, alias, t).ratio()
                s = r if r >= 0.88 else 0.0
            if s > score:
                best, score = entry["key"], s
    return best if score >= 0.88 else None


def get_spec(key: str) -> dict:
    return _mod(key).build()


def topics() -> list[str]:
    return [e["topic"] for e in catalog()]
