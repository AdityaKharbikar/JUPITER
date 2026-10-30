"""Tests that actually BUILD and RUN the assistant (the earlier suite only inspected source text,
which let a de-indented llm.py - 'think', 'think_stream' and '_warm_up_ollama' missing - pass as green)."""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from jupiter.core.assistant import Jupiter

REQUIRED = ["think", "think_stream", "_warm_up_ollama", "_build_messages", "_select_model", "_generation_options",
            "speak", "dispatch_command", "listen_for_command", "run", "drain_events", "_announce", "shutdown",
            "_chunk_text", "_pack_vector", "_unpack_vector", "_cosine", "_convert_temperature", "_fmt_number"]


@pytest.mark.parametrize("name", REQUIRED)
def test_class_has_required_method(name):
    assert hasattr(Jupiter, name), f"Jupiter.{name} is missing (indentation / mixin problem?)"


def test_static_helpers_work_through_an_instance_call():
    # these are called as self._x(...) in the code; they must be @staticmethod
    j = object.__new__(Jupiter)
    assert j._convert_temperature(20, "c", "f") == 68
    assert j._fmt_number(2.0) == "2"
    assert j._cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert isinstance(j._chunk_text("hello world " * 300), list)       # must not raise TypeError


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _json(self, o):
        b = json.dumps(o).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        self._json({"models": [{"name": "qwen3.5:4b"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/api/show":
            return self._json({"capabilities": ["completion", "vision"]})
        if body.get("stream"):
            self.send_response(200); self.send_header("Content-Type", "application/x-ndjson"); self.end_headers()
            for tok in ["Volcanoes ", "form when ", "magma rises. ", "They can erupt."]:
                self.wfile.write((json.dumps({"message": {"content": tok}, "done": False}) + "\n").encode())
            self.wfile.write((json.dumps({"message": {"content": ""}, "done": True}) + "\n").encode())
            return
        self._json({"message": {"role": "assistant", "content": "Hello from the mock model."}, "done": True})


@pytest.fixture
def jupiter(monkeypatch, tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    said = []
    monkeypatch.setattr(Jupiter, "setup_audio_models", lambda self, *a, **k: None)
    monkeypatch.setattr(Jupiter, "_init_speech_engine", lambda self: setattr(self, "_interrupted", threading.Event()))
    monkeypatch.setattr(Jupiter, "_voice_possible", lambda self: False)
    monkeypatch.setattr(Jupiter, "wait_speech_done", lambda self, *a, **k: None)
    monkeypatch.setattr(Jupiter, "speak", lambda self, t, wait=True: (said.append(str(t)), setattr(self, "_last_response", str(t))))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JUPITER_DATA_DIR", str(tmp_path / "data"))      # never touch the real memory DB
    j = Jupiter()                                   # must not raise (was: missing _warm_up_ollama)
    j.ollama_url = f"http://127.0.0.1:{srv.server_port}/api/chat"
    j.said = said
    yield j
    j.watchdog.stop()
    srv.shutdown()


def test_assistant_boots_and_greets(jupiter):
    assert jupiter.said and "sir" in jupiter.said[0].lower()


def test_skill_path(jupiter):
    assert jupiter.dispatch_command(jupiter._normalise_command("what is 12 plus 30")) is True
    assert "42" in jupiter.said[-1]


def test_llm_streaming_path(jupiter):
    n = len(jupiter.said)
    assert jupiter.dispatch_command("tell me about volcanoes") is False      # no skill -> LLM
    reply = jupiter.think_stream("tell me about volcanoes")
    assert "magma rises" in reply and len(jupiter.said) > n
    assert jupiter.last_llm_latency > 0


def test_llm_blocking_path(jupiter):
    assert "mock model" in jupiter.think("hello")


def test_unit_conversion_does_not_crash(jupiter):
    assert jupiter.dispatch_command(jupiter._normalise_command("convert 20 c to f")) is True
    assert "68" in jupiter.said[-1]


def test_tasks_by_voice_and_briefing_on_the_real_assistant(jupiter):
    say = lambda c: jupiter.dispatch_command(jupiter._normalise_command(c))
    assert say("add a task finish the report") and say("add task buy milk")
    assert say("what are my tasks") and "2 open tasks" in jupiter.said[-1]
    assert say("give me my briefing") and "finish the report" in jupiter.said[-1]
    assert say("complete task buy milk") and "Marked as done" in jupiter.said[-1]
    assert say("what are my tasks") and "1 open task" in jupiter.said[-1]
