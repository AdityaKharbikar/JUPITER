import sqlite3
import threading

import pytest

from jupiter.skills.registry import SkillRegistry, default_skills
from jupiter.services import briefing


@pytest.fixture
def reg():
    return SkillRegistry(default_skills())


@pytest.mark.parametrize("text,skill", [
    ("look at my screen", "vision"),
    ("what is on my screen", "vision"),
    ("look at my screen and tell me what's wrong", "vision"),
    ("what's wrong with my code", "vision"),
    ("explain this error", "vision"),
    ("summarize this page", "vision"),
    ("copy the fix", "vision"),
    ("give me my briefing", "briefing"),
    ("system briefing", "briefing"),
    ("start coding mode", "workflow"),
    ("start study mode", "workflow"),
    ("prepare for presentation", "workflow"),
])
def test_new_skills_route(reg, text, skill):
    s, _ = reg.route(text)
    assert s is not None and s.name == skill


@pytest.mark.parametrize("text", ["open chrome", "start a timer for 5 minutes", "what time is it",
                                  "system stats", "what is the weather", "battery"])
def test_old_commands_not_hijacked(reg, text):
    s, _ = reg.route(text)
    assert s is None or s.name not in {"vision", "workflow", "briefing"}


class FakeA:
    user_name = "sir"
    def __init__(self):
        self.said, self.opened, self.cmds = [], [], []
        self.http = None
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._db_lock = threading.RLock()
        self.conn.execute("CREATE TABLE tasks(id INTEGER PRIMARY KEY, title TEXT, priority INT DEFAULT 3, status TEXT DEFAULT 'open')")
        self.conn.execute("CREATE TABLE reminders(id INTEGER PRIMARY KEY, task TEXT, due_time TEXT, completed INT DEFAULT 0)")
        self.conn.execute("CREATE TABLE memory_facts(id INTEGER PRIMARY KEY, fact TEXT)")
        self.conn.execute("INSERT INTO tasks(title) VALUES ('finish demo')")
        self.conn.execute("INSERT INTO reminders(task,due_time) VALUES ('study','2026-10-08T22:00:00')")
        self.conn.execute("INSERT INTO memory_facts(fact) VALUES ('working on JUPITER')")
    def speak(self, t, wait=True): self.said.append(t); self._last_response = t
    def open_app(self, n): self.opened.append(n)
    def dispatch_command(self, c): self.cmds.append(c); return True
    def _greeting_period(self): return "evening"
    data_dir = "."


def test_briefing_text():
    text = briefing.compose(FakeA())
    assert "Good evening, sir." in text and "finish demo" in text and "10:00 PM" in text and "JUPITER" in text


def test_workflow_runs_allowed_steps(tmp_path):
    from jupiter.services.workflow import WorkflowService
    a = FakeA(); a.data_dir = str(tmp_path)
    svc = WorkflowService(a)
    svc.workflows["x"] = {"steps": [{"action": "open_app", "value": "notepad"},
                                    {"action": "shell", "value": "del *"},
                                    {"action": "command", "value": "system stats"}]}
    done, total = svc.run("x")
    assert (done, total) == (2, 3)
    assert a.opened == ["notepad"] and a.cmds == ["system stats"]


def test_vision_debug_pipeline_and_copy_fix():
    from jupiter.skills.vision import VisionSkill
    a = FakeA()

    class V:
        model, same_model = "vlm", False
        def look(self, *_a, **_k): return "for i in range(10)\n    print(i)"
        def reason(self, *_a, **_k): return "The for statement is missing a colon. Add one.\n```python\nfor i in range(10):\n    print(i)\n```"
    a.vision = V()
    sk = VisionSkill()
    res = sk.execute(sk.match("what's wrong with my code"), a)
    assert res.handled and "colon" in a.said[-1] and "```" not in a.said[-1]
    import pyperclip
    copied = {}
    pyperclip.copy = lambda t: copied.setdefault("t", t)
    sk.execute(sk.match("copy the fix"), a)
    assert copied["t"].startswith("for i in range(10):")


# ---------------------------------------------------------------- v2: confirm, sandbox, control, collisions
from jupiter.core import confirm
from jupiter.services import coderunner


@pytest.mark.parametrize("text,skill", [
    ("run the fix", "developer"), ("test the fix", "developer"),
    ("explain what i copied", "clipboard_ai"), ("fix the code in my clipboard", "clipboard_ai"),
    ("translate my clipboard to hindi", "clipboard_ai"),
    ("show desktop", "control"), ("switch window", "control"), ("scroll down", "control"),
    ("press enter", "control"), ("take a screenshot", "control"), ("close this window", "control"),
    ("lock the computer", "control"), ("type out hello world", "control"),
    ("on my screen what does the red text mean", "vision"),
])
def test_v2_routes(reg, text, skill):
    s, _ = reg.route(text)
    assert s is not None and s.name == skill


@pytest.mark.parametrize("text", [
    "what type of music is this", "type 2 diabetes symptoms", "press release about apple", "write a poem about the screen saver",
    "summarise my clipboard", "read my clipboard", "copy that", "what is the time", "run a marathon plan",
    "close the door", "i want to lock in and study", "yes", "no", "confirm"])
def test_v2_no_false_positives(reg, text):
    confirm.clear()
    s, _ = reg.route(text)
    assert s is None or s.name not in {"control", "developer", "clipboard_ai", "vision", "confirm", "workflow", "briefing"}, (text, s and s.name)


def test_yes_only_matches_when_pending(reg):
    confirm.clear()
    assert reg.route("yes")[0] is None
    confirm._pending = confirm.Pending("x", lambda: None, __import__("time").time())
    assert reg.route("yes")[0].name == "confirm" and reg.route("cancel")[0].name == "confirm"
    confirm.clear()


def test_confirm_flow_runs_only_after_yes():
    a = FakeA(); ran = []
    confirm.propose(a, "do thing", lambda: ran.append(1))
    assert ran == [] and confirm.current() is not None
    confirm.answer(a, False); assert ran == [] and confirm.current() is None
    confirm.propose(a, "do thing", lambda: ran.append(1)); confirm.answer(a, True); assert ran == [1]


def test_confirm_expires(monkeypatch):
    a = FakeA(); confirm.propose(a, "x", lambda: None)
    confirm._pending.created -= 120
    assert confirm.current() is None


@pytest.mark.parametrize("code,ok", [
    ("print(sum(range(10)))", True), ("import math\nprint(math.pi)", True),
    ("import os\nos.system('dir')", False), ("import subprocess", False), ("open('x.txt','w').write('a')", False),
    ("eval('1+1')", False), ("import requests", False), ("from shutil import rmtree", False),
    ("for i in range(3)\n    print(i)", False), ("print(open('x.txt').read())", True),
])
def test_scan(code, ok):
    assert coderunner.scan(code)[0] is ok


def test_runner_executes_and_times_out(tmp_path):
    r = coderunner.run("print(6*7)", str(tmp_path)); assert r["ok"] and "42" in r["output"]
    r = coderunner.run("while True: pass", str(tmp_path), timeout=1); assert not r["ok"] and "Stopped" in r["output"]
    r = coderunner.run("import socket", str(tmp_path)); assert r["refused"]


def test_control_requires_confirm_for_close_window(monkeypatch):
    from jupiter.services.control import ControlService
    a = FakeA(); c = ControlService(a); pressed = []
    monkeypatch.setattr(c, "_press", lambda keys, said: pressed.append(keys))
    confirm.clear(); c.hotkey("close_window")
    assert pressed == [] and confirm.current() is not None
    confirm.answer(a, True); assert pressed == [("alt", "f4")]
    c.hotkey("show_desktop"); assert pressed[-1] == ("winleft", "d")


def test_control_refuses_dangerous_keys():
    from jupiter.services.control import ControlService, SAFE_KEYS
    a = FakeA(); ControlService(a).press_key("delete" if "delete" not in SAFE_KEYS else "f4")
    assert any("only allowed" in s for s in a.said) or "delete" in SAFE_KEYS


def test_routing_is_fast(reg):
    import time
    t = time.perf_counter()
    for _ in range(200):
        reg.route("tell me something interesting about volcanoes")
    assert (time.perf_counter() - t) / 200 < 0.005     # < 5 ms per command


@pytest.mark.parametrize("text", [
    "what's wrong in the code on my screen", "what is wrong in the code on my screen", "find the bug in my code",
    "why is my code not working", "what does this error mean", "debug the code on my screen",
    "is there an error on my screen", "fix the error on my screen", "what's wrong with my code"])
def test_debug_phrases(reg, text):
    s, a = reg.route(text)
    assert s is not None and s.name == "vision" and a["mode"] == "debug", (text, s and s.name, a)


@pytest.mark.parametrize("text,mode", [
    ("describe the image on my screen", "screen"), ("look at my screen", "screen"), ("what's on my screen", "screen"),
    ("explain the code on my screen", "ask"), ("read the text on my screen", "read")])
def test_screen_phrases(reg, text, mode):
    s, a = reg.route(text)
    assert s is not None and s.name == "vision" and a["mode"] == mode


@pytest.mark.parametrize("text", ["what is the error rate of this model", "how do i write a function in python",
                                  "write a poem about the screen saver", "what is a syntax error"])
def test_debug_no_false_positive_on_general_questions(reg, text):
    s, a = reg.route(text)
    assert s is None or s.name != "vision" or a["mode"] != "debug", (text, a)


# ---------------------------------------------------------------- tasks by voice
@pytest.mark.parametrize("text,op", [
    ("add a task finish the report", "add"), ("add task buy milk", "add"), ("add call mom to my to do list", "add"),
    ("what are my tasks", "list"), ("show my tasks", "list"), ("list my to do list", "list"),
    ("complete task buy milk", "done"), ("mark task 2 as done", "done"), ("i finished the task buy milk", "done")])
def test_task_routing(reg, text, op):
    s, a = reg.route(text)
    assert s is not None and s.name == "tasks" and a["op"] == op, (text, s and s.name, a)


@pytest.mark.parametrize("text", ["take a note buy milk", "what is my favorite language", "what is the weather",
                                  "remind me to drink water in 5 minutes", "tell me a task management tip"])
def test_task_no_false_positive(reg, text):
    s, _ = reg.route(text)
    assert s is None or s.name != "tasks"


def test_task_flow():
    from jupiter.skills.tasks import TasksSkill
    a = FakeA(); a.conn.execute("DELETE FROM tasks")
    def add_task(title, **k): a.conn.execute("INSERT INTO tasks(title) VALUES (?)", (title,))
    a.add_task = add_task
    a.list_tasks = lambda: a.conn.execute("SELECT id,NULL,title FROM tasks WHERE status='open' ORDER BY id").fetchall()
    a.complete_task = lambda i: a.conn.execute("UPDATE tasks SET status='done' WHERE id=?", (i,))
    sk = TasksSkill()
    sk.execute(sk.match("add a task finish the report"), a); sk.execute(sk.match("add task buy milk"), a)
    sk.execute(sk.match("what are my tasks"), a)
    assert "2 open tasks" in a.said[-1] and "finish the report" in a.said[-1]
    sk.execute(sk.match("complete task buy milk"), a); assert "Marked as done" in a.said[-1]
    sk.execute(sk.match("what are my tasks"), a); assert "1 open task" in a.said[-1]
    sk.execute(sk.match("complete task 1"), a); sk.execute(sk.match("what are my tasks"), a)
    assert "no open tasks" in a.said[-1]
    sk.execute(sk.match("complete task nonexistent thing"), a); assert "couldn't find" in a.said[-1]
