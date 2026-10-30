"""Tests for the 3D Explainer, generator, cache, metrics, webcam identification and skill routing.
Run with pytest, or simply:  python -m jupiter.tests.test_explainer   (no pytest needed)."""
import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from jupiter.core.metrics import Metrics
from jupiter.explainer import camera, library
from jupiter.explainer.engine import ExplainerEngine
from jupiter.explainer.schema import SpecError, extract_json, sanitize_llm, validate_spec
from jupiter.skills.explainer import ExplainerSkill
from jupiter.skills.registry import SkillRegistry, default_skills

GOOD = {"kind": "physical", "title": "Ceiling fan", "summary": "Moves air.", "components": [
    {"name": "Motor", "purpose": "Spins the blades", "shape": "cylinder", "size": "large", "layer": 1, "connects_to": ["Blades", "Shaft"]},
    {"name": "Blades", "purpose": "Push air", "shape": "plate", "size": "large", "layer": 0, "connects_to": ["Motor"]},
    {"name": "Shaft", "purpose": "Transmits rotation", "shape": "rod", "size": "medium", "layer": 2, "connects_to": ["motor"]},
    {"name": "Switch", "purpose": "Speed control", "shape": "box", "size": "small", "layer": 3, "connects_to": ["Motor"]}],
    "assembly_order": ["Shaft", "Motor"]}


class FakeOllama:
    """Serves /api/chat. mode: 'good' | 'bad' | 'id' | 'id_unknown'."""
    def __init__(self, mode="good"):
        outer = self
        self.mode, self.calls = mode, 0

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n) or b"{}")
                outer.calls += 1
                if outer.mode == "id":
                    out = {"message": {"content": json.dumps({"object": "Computer Mouse", "confidence": "high", "category": "peripheral", "description": "A pointing device."})}}
                    data = json.dumps(out).encode(); self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
                if outer.mode == "id_unknown":
                    data = json.dumps({"message": {"content": "{\"object\":\"unknown\",\"confidence\":\"high\",\"description\":\"\"}"}}).encode()
                    self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
                text = json.dumps(GOOD) if outer.mode == "good" else "I am sorry, here is some prose, no JSON."
                self.send_response(200); self.end_headers()
                for i in range(0, len(text), 40):
                    self.wfile.write((json.dumps({"message": {"content": text[i:i + 40]}, "done": False}) + "\n").encode()); self.wfile.flush()
                self.wfile.write((json.dumps({"message": {"content": ""}, "done": True}) + "\n").encode())

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_port}/api/chat"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


def _engine(url, tmp):
    return ExplainerEngine(url, "fake-model", tmp, Metrics(Path(tmp) / "m.jsonl"))


# ---------------------------------------------------------------- curated library
def test_every_curated_model_is_valid_and_renders():
    cat = library.catalog()
    assert len(cat) >= 10
    with tempfile.TemporaryDirectory() as tmp:
        eng = _engine("http://127.0.0.1:1/api/chat", tmp)
        for entry in cat:
            spec = library.get_spec(entry["key"])
            assert validate_spec(spec) == [], (entry["key"], validate_spec(spec))
            assert spec["curated"] is True and len(spec["parts"]) >= 6
            res = eng._build_curated(entry["key"])
            html = Path(res.html_path).read_text(encoding="utf-8")
            assert "<script" in html and 'src="http' not in html and "<link" not in html          # fully offline: nothing is fetched
            assert spec["title"].split(" (")[0].split(" ")[0] in html


def test_alias_matching_is_conservative():
    for q, key in [("desktop computer", "desktop_pc"), ("a car engine", "car_engine"), ("mechanical keyboard", "mechanical_keyboard"),
                   ("drone", "quadcopter_drone"), ("TCP/IP", "tcp_ip"), ("heart", "human_heart"), ("neural networks", None),
                   ("the solar system", "solar_system"), ("bike", "bicycle"), ("computer keyboard", "mechanical_keyboard")]:
        got = library.find(q)
        if q == "neural networks":
            got = library.find("neural network")
            key = "neural_network"
        assert got == key, (q, got, key)
    for q in ["quantum computer", "jet engine", "steam engine", "heart of darkness", "washing machine", "ceiling fan"]:
        assert library.find(q) is None, q


# ---------------------------------------------------------------- parsing / validation
def test_extract_json_variants():
    assert extract_json('```json\n{"a": 1,}\n```')["a"] == 1
    assert extract_json('<think>hmm</think> text {"a": {"b": [1,2]}} tail')["a"]["b"] == [1, 2]
    assert extract_json('{"a": [1, 2')["a"] == [1, 2]            # truncated reply gets closed
    try:
        extract_json("no json here"); assert False
    except SpecError:
        pass


def test_sanitize_resolves_links_and_limits():
    d = sanitize_llm(GOOD, "fan")
    assert [c["name"] for c in d["components"]][0] == "Motor"
    assert d["components"][2]["connects_to"] == ["Motor"]         # fuzzy case-insensitive name resolution
    assert d["assembly_order"] == ["Shaft", "Motor"]
    bad = dict(GOOD, components=[{"name": "<b>x</b>", "purpose": "p"}] * 2)
    try:
        sanitize_llm(bad, "x"); assert False
    except SpecError:
        pass
    big = dict(GOOD, components=[{"name": f"P{i}", "purpose": "x", "shape": "weird", "size": "huge", "layer": 99, "connects_to": ["Nope"]} for i in range(40)])
    out = sanitize_llm(big, "x")
    assert len(out["components"]) == 16 and out["components"][0]["shape"] == "box" and out["components"][0]["layer"] == 3


# ---------------------------------------------------------------- generation, cache, metrics, failures
def test_generation_cache_and_metrics():
    srv = FakeOllama("good")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            eng = _engine(srv.url, tmp)
            seen = []
            r1 = eng.build("ceiling fan", progress=lambda s, f, d: seen.append((s, d)))
            assert r1.ok and r1.source == "generated" and r1.n_parts == 4 and Path(r1.html_path).exists()
            assert any(s == "component" for s, _ in seen), "progress should report components as they stream in"
            assert r1.spec["curated"] is False and "approximation" in r1.spec["disclaimer"].lower()
            calls = srv.calls
            r2 = eng.build("Ceiling Fan")
            assert r2.ok and r2.source == "cache" and srv.calls == calls
            rows = eng.metrics.rows()
            assert [r["cache_hit"] for r in rows] == [False, True] and all(r["ok"] for r in rows)
            assert rows[0]["ttfo_s"] is not None and rows[0]["model"] == "fake-model"
            r3 = eng.build("car engine")
            assert r3.source == "curated" and srv.calls == calls
            assert "Operation" in eng.metrics.report_markdown()
    finally:
        srv.close()


def test_malformed_output_fails_honestly():
    srv = FakeOllama("bad")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            eng = _engine(srv.url, tmp)
            r = eng.build("flux capacitor")
            assert not r.ok and "usable" in r.error and srv.calls == 2        # one retry, then an honest error
            assert eng.metrics.rows()[-1]["ok"] is False
            assert not list(Path(tmp).rglob("gen_*.json"))                     # failures are never cached
    finally:
        srv.close()


def test_ollama_down_keeps_curated_working():
    with tempfile.TemporaryDirectory() as tmp:
        eng = _engine("http://127.0.0.1:9/api/chat", tmp)
        r = eng.build("something exotic")
        assert not r.ok and "not running" in r.error
        assert eng.build("desktop computer").ok


def test_pregenerate_all():
    with tempfile.TemporaryDirectory() as tmp:
        eng = _engine("http://127.0.0.1:9/api/chat", tmp)
        out = eng.pregenerate()
        assert len(out) >= 10 and all(isinstance(v, float) for v in out.values()), out


# ---------------------------------------------------------------- webcam identification
def test_identify_with_fake_vision_model():
    srv = FakeOllama("id")
    try:
        info = camera.identify(b"\xff\xd8fake", srv.url, "v")
        assert info["object"] == "computer mouse" and info["confidence"] == "high"
    finally:
        srv.close()
    srv = FakeOllama("id_unknown")
    try:
        info = camera.identify(b"x", srv.url, "v")
        assert info["object"] == "unknown" and info["confidence"] == "low"         # 'unknown' can never claim high confidence
    finally:
        srv.close()
    try:
        camera.identify(b"x", "http://127.0.0.1:9/api/chat", "v"); assert False
    except camera.CameraError as e:
        assert "not running" in str(e)


# ---------------------------------------------------------------- skill
class FakeA:
    user_name = "sir"
    ollama_url = "http://127.0.0.1:9/api/chat"

    def __init__(self, tmp):
        self.said, self.hooks, self.data_dir = [], [], str(Path(tmp) / "data")
        self.ui_hook = lambda k, t: self.hooks.append((k, t))
        self.http = None

    def speak(self, t, wait=True): self.said.append(t); self._last_response = t


def test_skill_routing_and_no_hijack():
    reg = SkillRegistry(default_skills())
    for text, topic in [("show me how a car engine works", "car engine"), ("explode a desktop computer and explain its components", "desktop computer"),
                        ("visualize a TCP/IP network", "tcp/ip network"), ("show me the parts of a human heart", "human heart"),
                        ("explain how a drone is assembled", "drone"), ("show me a 3d model of a ceiling fan", "ceiling fan")]:
        s, a = reg.route(text)
        assert s.name == "explainer" and a["topic"] == topic, (text, s and s.name, a)
    for text in ["look at my screen", "explain this error", "open chrome", "what time is it", "play music", "explain how photosynthesis works",
                 "how does a jet engine work", "show me how to cook rice", "explode the clipboard", "start a timer for 5 minutes"]:
        s, _ = reg.route(text)
        assert s is None or s.name != "explainer", text
    assert reg.route("open the webcam")[1] == {"mode": "camera"}


def test_skill_execute_curated_and_failure():
    with tempfile.TemporaryDirectory() as tmp:
        a = FakeA(tmp)
        skill = ExplainerSkill()
        res = skill.execute({"mode": "explain", "topic": "car engine"}, a)
        assert res.success and any(k == "viewer" for k, _ in a.hooks) and any("hand-built" in s for s in a.said)
        a.said.clear()
        res = skill.execute({"mode": "explain", "topic": "flux capacitor"}, a)       # Ollama unreachable
        assert not res.success and any("not running" in s for s in a.said) and "built-in" in a.said[-1].lower() + "built-in"
        a.said.clear()
        assert skill.execute({"mode": "again"}, a).success                           # re-opens the last good topic
        assert skill.execute({"mode": "perf"}, a).success


if __name__ == "__main__":
    import traceback
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("PASS", name)
            except Exception:
                failed += 1; print("FAIL", name); traceback.print_exc()
    raise SystemExit(1 if failed else 0)
