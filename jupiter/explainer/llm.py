"""Ask the local Ollama model for a STRICT JSON component list. No code is ever requested or executed."""
from __future__ import annotations

import json
import re
import time

import requests

from .schema import LLM_JSON_SCHEMA, SpecError, extract_json, sanitize_llm

SYSTEM = """You help a 3D explainer app. Reply with ONE JSON object and nothing else.
Fields: kind, title, summary, components, assembly_order.
- kind: "physical" for a tangible object, machine, organ or structure; "concept" for an abstract system (protocol, algorithm, software architecture, process).
- title: short name. summary: one plain sentence (max 25 words).
- components: 6 to 12 of the MOST IMPORTANT real parts, no invented parts. Each has:
  name (short, the REAL part name e.g. "Crankshaft"), purpose (max 18 words),
  shape (box, plate, cylinder, rod, sphere, ring, cone, wheel, gear, coil, battery, chip, screen, lens, blade, pipe, dome, prism, motor, button, cable, housing - pick the one that really looks like the part),
  size (small, medium, large), aspect (cube, tall, wide, flat, long: overall proportions),
  place (where it sits relative to the centre of the object: center, top, bottom, left, right, front, back),
  inside (name of another listed part that physically contains it, or empty string),
  layer (physical: 0 outer shell/casing, 1 main structure, 2 internal mechanism, 3 small/peripheral parts; concept: 0 to 5 = tier from top to bottom),
  connects_to (names of OTHER components in your list that it directly connects to).
- Be physically faithful: real parts only, correct proportions, containers hold what is really inside them, and distinct parts get distinct places.
- assembly_order: component names in the order a person would assemble it (concept: the order data flows).
If you are unsure what the thing is, return kind "physical" with the few parts you are confident about."""

EXAMPLE_USER = "Topic: flashlight"
EXAMPLE_ASSISTANT = json.dumps({
    "kind": "physical", "title": "Flashlight", "summary": "A battery powered handheld lamp.",
    "components": [
        {"name": "Housing", "purpose": "Holds all the parts and acts as the handle.", "shape": "housing", "size": "large", "aspect": "long", "place": "center", "inside": "", "layer": 0, "connects_to": ["Batteries", "Reflector"]},
        {"name": "Batteries", "purpose": "Store the electrical energy.", "shape": "battery", "size": "medium", "aspect": "tall", "place": "center", "inside": "Housing", "layer": 1, "connects_to": ["Spring", "Switch"]},
        {"name": "Spring", "purpose": "Keeps the batteries pressed against the contacts.", "shape": "coil", "size": "small", "aspect": "tall", "place": "bottom", "inside": "Housing", "layer": 2, "connects_to": ["Batteries"]},
        {"name": "Switch", "purpose": "Opens or closes the circuit.", "shape": "button", "size": "small", "aspect": "cube", "place": "right", "inside": "", "layer": 3, "connects_to": ["Batteries", "LED"]},
        {"name": "LED", "purpose": "Converts electricity into light.", "shape": "sphere", "size": "small", "aspect": "cube", "place": "top", "inside": "Housing", "layer": 2, "connects_to": ["Switch", "Reflector"]},
        {"name": "Reflector", "purpose": "Focuses the light into a beam.", "shape": "cone", "size": "medium", "aspect": "cube", "place": "top", "inside": "", "layer": 1, "connects_to": ["LED", "Lens"]},
        {"name": "Lens", "purpose": "Protects the LED and shapes the beam.", "shape": "lens", "size": "medium", "aspect": "wide", "place": "top", "inside": "", "layer": 0, "connects_to": ["Reflector"]},
    ], "assembly_order": ["Spring", "Batteries", "Switch", "LED", "Reflector", "Lens", "Housing"]}, separators=(",", ":"))

_NAME_RE = re.compile(r'"name"\s*:\s*"([^"\n]{1,60})"')


class GenerationError(Exception):
    """Raised with a message that is safe to show/speak to the user."""


class Generator:
    def __init__(self, ollama_url: str, model: str, http=None, read_timeout: float = 120.0):
        self.url = ollama_url
        self.model = model
        self.http = http or requests.Session()
        self.read_timeout = read_timeout

    def _payload(self, topic, use_schema, strict_retry):
        user = f"Topic: {topic}"
        if strict_retry:
            user += "\nReturn ONLY valid JSON that matches the fields exactly. No commentary."
        return {
            "model": self.model, "stream": True, "think": False, "keep_alive": "15m",
            "format": LLM_JSON_SCHEMA if use_schema else "json",
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": EXAMPLE_USER}, {"role": "assistant", "content": EXAMPLE_ASSISTANT},
                         {"role": "user", "content": user}],
            "options": {"temperature": 0.15 if strict_retry else 0.3, "num_predict": 2200, "num_ctx": 6144},
        }

    def generate(self, topic: str, progress=None, cancelled=None):
        """Return (clean_data, info). progress(stage, fraction, detail) is called as components stream in."""
        progress = progress or (lambda *a: None)
        t0 = time.perf_counter()
        info = {"model": self.model, "ttfo_s": None, "total_s": None, "attempts": 0}
        last_err = "unknown error"
        use_schema = True
        for attempt in range(2):
            info["attempts"] = attempt + 1
            try:
                text = self._stream(topic, use_schema, attempt > 0, t0, info, progress, cancelled)
            except _SchemaRejected:
                use_schema = False
                try:
                    text = self._stream(topic, False, attempt > 0, t0, info, progress, cancelled)
                except _SchemaRejected as exc:
                    raise GenerationError(str(exc))
            try:
                data = sanitize_llm(extract_json(text), topic)
                info["total_s"] = time.perf_counter() - t0
                return data, info
            except SpecError as exc:
                last_err = str(exc)
                progress("retry", 0.3, f"Model reply unusable ({last_err}); retrying once")
        raise GenerationError(f"The model did not return a usable component list ({last_err}).")

    def _stream(self, topic, use_schema, strict, t0, info, progress, cancelled):
        progress("asking", 0.05, f"Asking {self.model} for the component list")
        try:
            resp = self.http.post(self.url, json=self._payload(topic, use_schema, strict), stream=True, timeout=(5, self.read_timeout))
        except requests.exceptions.ConnectionError:
            raise GenerationError("Ollama is not running, so I can only show the built-in models.")
        except requests.exceptions.Timeout:
            raise GenerationError("The language model took too long to answer.")
        with resp:
            if resp.status_code == 404:
                raise GenerationError(f"The model {self.model} is not installed. Run: ollama pull {self.model}")
            if resp.status_code == 400 and use_schema:
                raise _SchemaRejected("Ollama rejected structured output")
            if resp.status_code != 200:
                raise GenerationError(f"Ollama returned error {resp.status_code}.")
            buf, seen = "", 0
            try:
                for line in resp.iter_lines():
                    if cancelled and cancelled():
                        raise GenerationError("Cancelled.")
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except ValueError:
                        continue
                    piece = payload.get("message", {}).get("content", "")
                    if piece:
                        if info["ttfo_s"] is None:
                            info["ttfo_s"] = time.perf_counter() - t0
                            progress("streaming", 0.15, "Model is answering")
                        buf += piece
                        names = _NAME_RE.findall(buf)
                        if len(names) > seen:
                            seen = len(names)
                            progress("component", min(0.9, 0.15 + 0.07 * seen), names[-1])
                    if payload.get("done"):
                        break
            except requests.exceptions.RequestException:
                raise GenerationError("The connection to the language model dropped.")
        return buf


class _SchemaRejected(Exception):
    pass
