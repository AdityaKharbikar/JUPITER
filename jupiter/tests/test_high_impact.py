import os
import sqlite3
import threading

from jupiter.skills.registry import SkillRegistry, default_skills
from jupiter.core import confirm
from jupiter.core.health import HealthChecker
from jupiter.models.model_router import ModelRouter


class A:
    user_name = "sir"
    ollama_url = "http://127.0.0.1:11434/api/chat"
    def __init__(self):
        import requests
        self.http = requests.Session()
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._db_lock = threading.RLock()
        self.said = []
    def speak(self, text, wait=True): self.said.append(text)


def test_health_skill_routes():
    r = SkillRegistry(default_skills())
    s, _ = r.route("health check")
    assert s is not None and s.name == "health"


def test_active_window_routes():
    r = SkillRegistry(default_skills())
    s, _ = r.route("what app is active")
    assert s is not None and s.name == "control"


def test_image_route():
    r = SkillRegistry(default_skills())
    s, args = r.route('analyze image "photo.png"')
    assert s is not None and s.name == "vision" and args["mode"] == "image"


def test_model_router_falls_back_without_coder(monkeypatch):
    a = A()
    router = ModelRouter(a)
    monkeypatch.setattr(router, "available_models", lambda ttl=60: {"qwen3.5:4b"})
    assert router.choose("write code in python") == "qwen3.5:4b"


def test_health_report_is_human_readable():
    a = A()
    h = HealthChecker(a)
    h.check = lambda: {"python": True, "ollama": True, "sqlite": True, "whisper": False}
    h.model_status = lambda: {"installed": ["qwen3.5:4b"], "general": "qwen3.5:4b", "coding": "qwen2.5-coder:7b"}
    report = h.report()
    assert "Core health" in report and "Ollama is online" in report and "qwen3.5:4b" in report


def test_end_study_mode_resets_mode_and_only_its_own_timer():
    import threading
    import types
    from jupiter.skills.registry import SkillRegistry, default_skills
    from jupiter.skills.workflow import WorkflowSkill

    reg = SkillRegistry(default_skills())
    for phrase in ("end study mode", "exit coding mode", "stop focus mode", "finish study session"):
        skill, args = reg.route(phrase)
        assert skill is not None and skill.name == "workflow" and args["op"] == "end", phrase
    assert reg.route("quit")[0] is None and reg.route("exit strategy")[0] is None

    spoken = []
    a = types.SimpleNamespace(
        user_name="sir", current_mode="study mode", _timers_lock=threading.Lock(),
        _timers=[{"label": "dinner"}, {"label": "50 minutes", "workflow": "study mode"}],
        speak=lambda m, **k: spoken.append(m),
    )
    WorkflowSkill().execute({"op": "end", "name": "study mode"}, a)
    assert a.current_mode == "normal"
    assert [t["label"] for t in a._timers] == ["dinner"]
    WorkflowSkill().execute({"op": "end", "name": None}, a)
    assert "No mode or mission" in spoken[-1]


def test_youtube_commands_ignore_capitalisation():
    from jupiter.skills.registry import SkillRegistry, default_skills

    reg = SkillRegistry(default_skills())
    for phrase in (
        "search lofi beats on youtube", "search lofi beats on YouTube", "Search lofi beats on YouTube.",
        "search You Tube for lofi beats", "search YouTube for lofi beats", "YouTube search lofi beats",
    ):
        skill, args = reg.route(phrase)
        assert skill.name == "media" and args["op"] == "youtube", phrase
        assert args["query"].lower() == "lofi beats", (phrase, args)
    for phrase in ("open youtube", "open YouTube", "Open YouTube.", "Open You Tube"):
        skill, args = reg.route(phrase)
        assert skill.name == "media" and args == {"op": "youtube", "query": None}, phrase
    skill, args = reg.route("Play Despacito on YouTube")
    assert skill.name == "media" and args == {"op": "play", "query": "Despacito"}
    # a capital letter must never push a command to a looser skill
    assert reg.route("Translate Hello to Hindi")[0].name == "translation"
    assert reg.route("Open Notepad")[0].name == "media"
