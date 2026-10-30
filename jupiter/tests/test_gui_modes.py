"""Headless (offscreen) tests of the GUI mode controls: voice/text, always-on/push-to-talk/sleep, one-shot typing."""
import os
import queue
import sqlite3
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

import requests  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import jupiter.ui.desktop as desktop  # noqa: E402
from jupiter.audio.modes import AudioModesMixin  # noqa: E402
from jupiter.common import LISTEN_ACTIVE, LISTEN_PTT, LISTEN_SLEEP  # noqa: E402
from jupiter.core.router import HybridRouter  # noqa: E402
from jupiter.core.settings import SettingsMixin  # noqa: E402


class FakeJ(AudioModesMixin, SettingsMixin):
    """Real mode logic (AudioModesMixin + ModeSkill) on a stub with a scripted microphone."""
    user_name = "sir"
    is_running = True
    ollama_url = "http://127.0.0.1:1/api/chat"
    data_dir = "."
    _last_response = None
    _previous_response = ""

    def __init__(self):
        self.http = requests.Session()
        self.router = HybridRouter(self)
        self._interrupted = threading.Event()
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._db_lock = threading.RLock()
        for q in ("CREATE TABLE tasks(id INTEGER PRIMARY KEY,title TEXT,priority INT DEFAULT 3,status TEXT DEFAULT 'open')",
                  "CREATE TABLE reminders(id INTEGER PRIMARY KEY,task TEXT,due_time TEXT,completed INT DEFAULT 0)",
                  "CREATE TABLE memory_facts(id INTEGER PRIMARY KEY,fact TEXT)"):
            self.conn.execute(q)
        self._events = queue.Queue()
        self.input_mode, self.listen_mode, self.auto_return_to_voice = "voice", LISTEN_ACTIVE, True
        self.script, self.listen_calls, self.said, self.settings = [], 0, [], {}

    def _save_setting(self, k, v): self.settings[k] = v
    def _voice_possible(self): return True
    def _pick(self, x, **k): return x[0]
    def speak(self, t, wait=True):
        if self._interrupted.is_set():              # same as the real speak(): an interrupted turn says nothing more
            return
        self.said.append(str(t)); self._last_response = str(t)
    def _normalise_command(self, t): return t.lower()
    def _greeting_period(self): return "evening"
    def store_conversation(self, r, m): pass
    def interrupt_speech(self): self._interrupted.set()
    def shutdown(self): pass
    def wait_speech_done(self): pass
    def drain_events(self):
        while not self._events.empty():
            self.speak(self._events.get())
    def _stop_barge_monitor(self): pass
    def think_stream(self, t): self.speak("(llm)", wait=False); return "(llm)"

    def _listen_voice_input(self, max_duration=None, quick=False, keep_short=False):
        self.listen_calls += 1
        time.sleep(0.05)
        return self.script.pop(0) if self.script else ""

    def dispatch_command(self, c):
        s, a = self.router.route(c)
        return bool(s.execute(a, self).handled) if s else False


@pytest.fixture
def win(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(desktop, "Jupiter", FakeJ)
    w = desktop.JupiterWindow()
    w.show()
    w.pump = lambda secs=0.3: [app.processEvents() or time.sleep(0.02) for _ in range(int(secs / 0.02))]
    w.until = lambda cond, timeout=4.0: _until(w, cond, timeout)
    assert w.until(lambda: w.a is not None and w._state != "BOOTING"), "GUI never finished booting"
    yield w
    w._alive = False
    w.close()


def _until(w, cond, timeout):
    t = time.time()
    while time.time() - t < timeout:
        w.pump(0.05)
        if cond():
            return True
    return False


def test_always_on_hears_and_answers(win):
    win.a.script = ["what mode am i in"]
    assert win.until(lambda: "I am in voice mode" in win.chat.toPlainText())
    assert win.input_btns["voice"].isChecked() and win.listen_btns[LISTEN_ACTIVE].isChecked()


def test_text_mode_stops_the_mic_and_one_shot_returns_to_voice(win):
    win.input_btns["text"].click()
    assert win.until(lambda: win.a.input_mode == "text")
    win.pump(0.4); n = win.a.listen_calls; win.pump(0.8)
    assert win.a.listen_calls == n, "mic must be closed in text mode"
    win.submit("give me my briefing")                  # (a mode command itself must NOT trigger the revert)
    assert win.until(lambda: win.a.input_mode == "voice")                    # one-shot: back to voice
    assert win.until(lambda: win.input_btns["voice"].isChecked())            # ...and the button follows
    assert win.until(lambda: win.a.listen_calls > n)                         # ...and the mic is open again


def test_pinned_text_mode_stays_text(win):
    win.return_cb.setChecked(False)
    assert win.until(lambda: win.a.auto_return_to_voice is False)
    win.input_btns["text"].click()
    assert win.until(lambda: win.a.input_mode == "text")
    win.submit("what mode am i in"); win.submit("what mode am i in")
    assert win.until(lambda: win.chat.toPlainText().count("I am in text mode") >= 2)
    win.pump(0.3)
    assert win.a.input_mode == "text" and win.input_btns["text"].isChecked()


def test_push_to_talk_only_listens_when_asked(win):
    win.listen_btns[LISTEN_PTT].click()
    assert win.until(lambda: win.a.listen_mode == LISTEN_PTT)
    win.pump(0.5); n = win.a.listen_calls; win.pump(0.8)
    assert win.a.listen_calls == n, "push-to-talk must keep the mic closed"
    win.a.script = ["what mode am i in"]
    win.mic.click()
    assert win.until(lambda: "I am in voice mode" in win.chat.toPlainText())
    assert win.a.listen_calls == n + 1


def test_sleep_ignores_everything_but_the_wake_phrase(win):
    win.listen_btns[LISTEN_SLEEP].click()
    assert win.until(lambda: win.a.listen_mode == LISTEN_SLEEP and win._state == "SLEEPING")
    win.a.script = ["what mode am i in", "hey jupiter what mode am i in"]
    assert win.until(lambda: "I am in" in win.chat.toPlainText(), timeout=6)
    win.pump(0.5)
    assert win.chat.toPlainText().count("I am in") == 1                       # the un-prefixed utterance was ignored
    assert win.a.listen_mode == LISTEN_ACTIVE                                 # woke up


def test_typed_text_while_asleep_explains_itself(win):
    win.submit("sleep")
    assert win.until(lambda: win.a.listen_mode == LISTEN_SLEEP and win.listen_btns[LISTEN_SLEEP].isChecked())
    win.submit("what mode am i in")
    assert win.until(lambda: "asleep" in win.chat.toPlainText())
    win.mic.click()                                                           # mic button = explicit wake-up
    assert win.until(lambda: win.a.listen_mode == LISTEN_ACTIVE)


def test_spoken_mode_commands_update_the_controls(win):
    win.submit("walkie talkie")
    assert win.until(lambda: win.listen_btns[LISTEN_PTT].isChecked() and win.a.listen_mode == LISTEN_PTT)
    win.submit("always listening")
    assert win.until(lambda: win.listen_btns[LISTEN_ACTIVE].isChecked())
    win.submit("stay in text mode")
    assert win.until(lambda: win.input_btns["text"].isChecked() and win.a.auto_return_to_voice is False)
    win.submit("auto voice")
    assert win.until(lambda: win.input_btns["voice"].isChecked() and win.return_cb.isChecked())


def test_typing_is_never_blocked_by_listening(win):
    win.a.script = []                       # mic loop is spinning in the background
    t0 = time.time()
    win.submit("what mode am i in")
    assert win.until(lambda: "I am in" in win.chat.toPlainText(), timeout=2)
    assert time.time() - t0 < 2


def test_stop_button_interrupts_and_does_not_swallow_later_speech(win):
    win.stop_speech()
    assert win.a._interrupted.is_set()                       # works in any mode, like Esc
    win.a._events.put("Warning, sir. Memory is high.")       # e.g. a watchdog alert arriving after the interrupt
    assert win.until(lambda: "Memory is high" in win.chat.toPlainText()), "stale interrupt swallowed the alert"
    assert not win.a._interrupted.is_set()


def test_busy_flag_is_released_after_each_turn(win):
    win.submit("what mode am i in")
    assert win.until(lambda: "I am in" in win.chat.toPlainText())
    assert win.until(lambda: not win._busy.is_set())
