"""JUPITER Command Center (PySide6).

Design rule: the GUI contains NO AI logic. It
  * sends text / mic jobs to ONE worker thread that owns the Jupiter object
    (UI never freezes; TTS, SQLite and Ollama are never touched from two threads),
  * shows what comes back, plus live telemetry, an activity timeline and a
    confirmation bar for risky actions.
"""
import html
import math
import os
import queue
import re
import subprocess
import sys
import threading
import time

import psutil
from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QRadialGradient, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QMainWindow, QProgressBar, QScrollArea, QPushButton, QTextBrowser,
                               QVBoxLayout, QWidget, QFileDialog)

from ..core.assistant import Jupiter
from ..core import confirm as confirm_state
from ..services import briefing
from ..common import LISTEN_ACTIVE, LISTEN_PTT, LISTEN_SLEEP
from . import explainer_ui

STATE_STYLE = {   # state -> (colour, caption, spin speed)
    "BOOTING": ("#7a8a99", "STARTING UP", 1.0), "IDLE": ("#2bd9ff", "STANDBY", 0.5),
    "LISTENING": ("#35e08a", "LISTENING", 1.6), "THINKING": ("#ffb020", "THINKING", 3.5),
    "ANALYZING": ("#d36bff", "ANALYZING SCREEN", 4.5), "SPEAKING": ("#6ee7ff", "SPEAKING", 2.2),
    "SLEEPING": ("#6b6f99", "SLEEPING - SAY 'HEY JUPITER'", 0.2), "PTT": ("#2bd9ff", "PUSH TO TALK - ENTER OR SPACE", 0.5),
    "TEXT": ("#2bd9ff", "TEXT MODE", 0.5),
}

QUICK = [("Briefing", "give me my briefing"), ("Look at screen", "look at my screen"),
         ("Fix my code", "what's wrong with my code"), ("Health", "health check"),
         ("Active app", "what app is active"), ("Run the fix", "run the fix"),
         ("Coding mode", "start coding mode"), ("Study mode", "start study mode"),
         ("Presentation", "start presentation mode"), ("System stats", "system stats")]

QUICK_3D = [("3D: Desktop PC", "show me how a desktop computer works"), ("3D: Car engine", "show me how a car engine works"),
            ("3D: Drone", "explain how a drone is assembled"), ("3D: Neural network", "visualize a neural network"),
            ("3D: TCP/IP", "visualize a TCP/IP network")]

QSS = """
QMainWindow, QWidget { background:#0b1220; color:#dbe7f3; font-family:'Segoe UI'; font-size:13px; }
QLabel, QCheckBox { background:transparent; }
QFrame#card { background:#111a2c; border:1px solid #1d2b45; border-radius:10px; }
QFrame#confirm { background:#2a1f08; border:1px solid #ffb020; border-radius:10px; }
QLabel#title { font-size:20px; font-weight:700; letter-spacing:4px; color:#2bd9ff; }
QLabel#h { color:#7f93ad; font-size:11px; letter-spacing:2px; }
QLabel#chip { background:#0d1627; border:1px solid #27406b; border-radius:9px; padding:2px 8px; color:#9fb3cc; font-size:11px; }
QTextBrowser, QListWidget { background:#0d1627; border:1px solid #1d2b45; border-radius:8px; padding:6px; }
QLineEdit { background:#0d1627; border:1px solid #27406b; border-radius:8px; padding:9px; }
QPushButton { background:#15233d; border:1px solid #27406b; border-radius:8px; padding:6px 10px; text-align:left; }
QPushButton:hover { background:#1c3256; border-color:#2bd9ff; }
QPushButton#mic { text-align:center; font-size:16px; }
QPushButton[seg="true"] { text-align:center; padding:6px 4px; }
QPushButton[seg="true"]:checked { background:#0f4c5c; border-color:#2bd9ff; color:#ffffff; }
QPushButton#ok { background:#14532d; border-color:#35e08a; text-align:center; }
QPushButton#no { background:#4a1d1d; border-color:#ff6b6b; text-align:center; }
QProgressBar { background:#0d1627; border:1px solid #1d2b45; border-radius:5px; height:12px; text-align:center; font-size:10px; }
QProgressBar::chunk { background:#2bd9ff; border-radius:4px; }
"""


class ArcReactor(QWidget):
    """Animated Iron-Man-style core: spin speed and colour follow JUPITER's state."""
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(150)
        self.state, self.angle, self.phase = "BOOTING", 0.0, 0.0
        t = QTimer(self); t.timeout.connect(self._tick); t.start(40)

    def set_state(self, s):
        self.state = s

    def _tick(self):
        if not self.isVisible():
            return
        self.angle = (self.angle + STATE_STYLE.get(self.state, STATE_STYLE["IDLE"])[2]) % 360
        self.phase += 0.12
        self.update()

    def paintEvent(self, _):
        col = QColor(STATE_STYLE.get(self.state, STATE_STYLE["IDLE"])[0])
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        R = min(self.width(), self.height()) / 2 - 8
        pulse = 0.5 + 0.5 * math.sin(self.phase)
        glow = QRadialGradient(c, R)
        g0 = QColor(col); g0.setAlpha(int(70 + 60 * pulse)); glow.setColorAt(0, g0)
        g1 = QColor(col); g1.setAlpha(0); glow.setColorAt(1, g1)
        p.setBrush(glow); p.setPen(Qt.NoPen); p.drawEllipse(c, R, R)
        # rotating arc rings
        for i, (frac, width, span, direction) in enumerate(((1.0, 3, 80, 1), (0.82, 2, 120, -1), (0.64, 4, 60, 1))):
            pen = QPen(col, width); pen.setCapStyle(Qt.RoundCap); p.setPen(pen); p.setBrush(Qt.NoBrush)
            r = R * frac
            rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
            for k in range(3):
                start = (self.angle * direction * (1 + 0.4 * i) + k * 120) % 360
                p.drawArc(rect, int(start * 16), int(span * 16))
        # core
        core = R * (0.30 + 0.05 * pulse)
        cg = QRadialGradient(c, core)
        cg.setColorAt(0, QColor("#ffffff")); cg.setColorAt(0.35, col); cg.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(cg); p.setPen(Qt.NoPen); p.drawEllipse(c, core, core)
        p.end()


class Bridge(QObject):
    message = Signal(str, str)      # role, text
    stream = Signal(str)            # live text while JUPITER is speaking
    state = Signal(str)
    log = Signal(str)
    alert = Signal(str)
    action = Signal(str)
    confirm = Signal(str)
    snapshot = Signal(dict)
    models = Signal(str, str)
    modes = Signal(str, str, bool)   # input_mode, listen_mode, auto_return_to_voice
    booted = Signal()
    viewer = Signal(str, str)        # html path, title  (3D Explainer)
    camera = Signal()                # open the webcam panel
    viewer_cmd = Signal(str, str)    # voice -> 3D viewer command: name, JSON argument
    progress = Signal(float, str, str)  # fraction, stage, detail
    quit = Signal()                  # the assistant was told to quit ("goodbye", "quit", ...)


def _card(title):
    f = QFrame(); f.setObjectName("card")
    lay = QVBoxLayout(f); lay.setContentsMargins(12, 10, 12, 10)
    h = QLabel(title); h.setObjectName("h"); lay.addWidget(h)
    return f, lay


def render(text: str) -> str:
    """Plain text + ``` code fences -> small HTML."""
    out = []
    for i, part in enumerate(re.split(r"```[\w+-]*\n?", text)):
        if i % 2:
            out.append("<pre style='background:#08101d;border:1px solid #27406b;padding:8px;color:#9ef0c0;"
                       f"font-family:Consolas'>{html.escape(part.strip(chr(10)))}</pre>")
        else:
            out.append(html.escape(part).replace("\n", "<br>"))
    return "".join(out)


def _exclude_from_capture(win_id: int) -> bool:
    """Windows 10 2004+: make this window invisible to screenshots so 'look at my screen' never sees JUPITER itself."""
    if sys.platform != "win32" or os.environ.get("JUPITER_SHOW_IN_CAPTURE"):
        return False
    try:
        import ctypes
        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(int(win_id), 0x11))   # WDA_EXCLUDEFROMCAPTURE
    except Exception:
        return False


class JupiterWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JUPITER - Local AI Desktop Intelligence")
        self.resize(1320, 800)
        self.setStyleSheet(QSS)
        self.q: "queue.Queue" = queue.Queue()
        self.a = None
        self._alive = True
        self._busy = threading.Event()          # set while the worker is handling a turn (mic thread stays quiet)
        self._spoken: list[str] = []
        self._html: list[str] = []
        self._live = ""
        self._stick = True                      # keep the chat pinned to the newest message
        self._state = "BOOTING"
        self._gpu = (None, None, None)
        self._gpu_t = 0.0
        self.bridge = Bridge()
        self._build()
        b = self.bridge
        b.message.connect(self.add_message); b.stream.connect(self.on_stream); b.state.connect(self.set_state)
        b.log.connect(self.add_log); b.alert.connect(lambda t: self.add_log("ALERT: " + t))
        b.action.connect(lambda t: self.last_action.setText(f"Last: {t}")); b.snapshot.connect(self.update_memory)
        b.confirm.connect(self.on_confirm); b.models.connect(self.on_models); b.modes.connect(self.on_modes)
        b.booted.connect(lambda: (self.add_log("JUPITER online"), self.set_state("IDLE")))
        b.quit.connect(self._quit_app)
        b.viewer.connect(lambda path, title: explainer_ui.open_viewer(self, path, title))
        b.camera.connect(self.open_camera)
        b.viewer_cmd.connect(lambda n, a: explainer_ui.send_viewer_cmd(self, n, a))
        b.progress.connect(lambda f, st, d: explainer_ui.on_progress(self, f, st, d))
        for ms, fn in ((1500, self.update_telemetry),
                       (2000, self._maybe_drain), (10000, lambda: self._enqueue_once("snapshot"))):
            t = QTimer(self); t.timeout.connect(fn); t.start(ms)
        QShortcut(QKeySequence("Esc"), self, activated=self.stop_speech)
        # Push-to-talk: Enter OR Space starts listening (see eventFilter).
        QApplication.instance().installEventFilter(self)
        threading.Thread(target=self._worker, name="jupiter-gui-worker", daemon=True).start()
        threading.Thread(target=self._mic_loop, name="jupiter-gui-mic", daemon=True).start()

    def showEvent(self, e):
        super().showEvent(e)
        if _exclude_from_capture(self.winId()):
            self.add_log("Window hidden from screen capture")

    # ------------------------------------------------------------ UI build
    def _build(self):
        root = QWidget(); self.setCentralWidget(root)
        main = QHBoxLayout(root); main.setContentsMargins(14, 14, 14, 14); main.setSpacing(12)

        left = QVBoxLayout(); left.setSpacing(8)
        t = QLabel("JUPITER"); t.setObjectName("title"); left.addWidget(t)
        sub = QLabel("LOCAL AI SYSTEM"); sub.setObjectName("h"); left.addWidget(sub); left.addSpacing(10)
        for label, cmd in QUICK:
            btn = QPushButton(label); btn.clicked.connect(lambda _=False, c=cmd: self.submit(c)); left.addWidget(btn)
        for label, cmd in QUICK_3D:
            btn = QPushButton(label); btn.clicked.connect(lambda _=False, c=cmd: self.submit(c)); left.addWidget(btn)
        left.addWidget(explainer_ui.build_explainer_card(self, _card))
        img_btn = QPushButton("Analyze image file")
        img_btn.clicked.connect(self.pick_image)
        left.addWidget(img_btn)
        left.addStretch()
        mc, ml = _card("INPUT")
        self.input_btns = self._segment(ml, [("Voice", "voice"), ("Text", "text")], lambda v: self._enqueue("setmode", ("input", v)))
        ml.addWidget(self._tiny("LISTENING"))
        self.listen_btns = self._segment(ml, [("Always on", LISTEN_ACTIVE), ("Push-to-talk", LISTEN_PTT), ("Sleep", LISTEN_SLEEP)],
                                         lambda v: self._enqueue("setmode", ("listen", v)), vertical=True)
        self.return_cb = QCheckBox("Auto-return to voice")
        self.return_cb.setChecked(True)
        self.return_cb.setToolTip("After ONE typed command, switch back to the microphone. Untick to keep text mode pinned.")
        self.return_cb.toggled.connect(lambda on: self._enqueue("setmode", ("return", on)))
        ml.addWidget(self.return_cb)
        left.addWidget(mc)
        self.alerts_on = QCheckBox("Proactive alerts"); self.alerts_on.setChecked(True)
        self.alerts_on.toggled.connect(self._toggle_alerts); left.addWidget(self.alerts_on)
        hint = QLabel("Enter / Space = talk (push-to-talk)   Esc stop"); hint.setWordWrap(True); hint.setObjectName("h"); left.addWidget(hint)
        lw = QWidget(); lw.setLayout(left)
        sa = QScrollArea(); sa.setWidget(lw); sa.setWidgetResizable(True); sa.setFrameShape(QFrame.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); sa.setFixedWidth(232); main.addWidget(sa)

        centre = QVBoxLayout()
        chips = QHBoxLayout()
        self.chip_llm = QLabel("LLM: -"); self.chip_vis = QLabel("Vision: -"); self.chip_mode = QLabel("Mode: normal")
        for c in (self.chip_llm, self.chip_vis, self.chip_mode):
            c.setObjectName("chip"); chips.addWidget(c)
        chips.addStretch(); centre.addLayout(chips)
        self.chat = QTextBrowser(); self.chat.setOpenExternalLinks(True); centre.addWidget(self.chat, 1)
        sb = self.chat.verticalScrollBar()
        sb.rangeChanged.connect(self._on_chat_range)      # content grew/re-laid-out -> stay at the bottom
        sb.actionTriggered.connect(self._on_chat_user_scroll)   # drag / wheel / keys by the user
        sb.sliderMoved.connect(self._on_chat_user_scroll)
        self.confirm_bar = QFrame(); self.confirm_bar.setObjectName("confirm"); self.confirm_bar.hide()
        cb = QHBoxLayout(self.confirm_bar)
        self.confirm_lbl = QLabel(""); self.confirm_lbl.setWordWrap(True); cb.addWidget(self.confirm_lbl, 1)
        ok = QPushButton("Confirm"); ok.setObjectName("ok"); ok.clicked.connect(lambda: self.submit("confirm"))
        no = QPushButton("Cancel"); no.setObjectName("no"); no.clicked.connect(lambda: self.submit("cancel"))
        cb.addWidget(ok); cb.addWidget(no); centre.addWidget(self.confirm_bar)
        row = QHBoxLayout()
        self.mic = QPushButton("🎤"); self.mic.setObjectName("mic"); self.mic.setFixedWidth(52)
        self.mic.clicked.connect(lambda: self._enqueue("mic_once"))
        self.input = QLineEdit(); self.input.setPlaceholderText("Ask JUPITER...  (or press the mic)")
        self.input.returnPressed.connect(self.on_send)
        send = QPushButton("Send"); send.setFixedWidth(70); send.clicked.connect(self.on_send)
        stop = QPushButton("Stop"); stop.setFixedWidth(64); stop.clicked.connect(self.stop_speech)
        for w in (self.mic, self.input, send, stop):
            row.addWidget(w)
        centre.addLayout(row)
        cw = QWidget(); cw.setLayout(centre); main.addWidget(cw, 1)

        right = QVBoxLayout(); right.setSpacing(10)
        c, l = _card("JUPITER STATE")
        self.reactor = ArcReactor(); l.addWidget(self.reactor)
        self.orb_txt = QLabel("STARTING UP"); self.orb_txt.setAlignment(Qt.AlignCenter); l.addWidget(self.orb_txt)
        self.last_action = QLabel("Last: -"); self.last_action.setAlignment(Qt.AlignCenter); l.addWidget(self.last_action)
        right.addWidget(c)

        c, l = _card("SYSTEM")
        self.bars = {}
        for key in ("CPU", "RAM", "GPU", "VRAM"):
            r = QHBoxLayout(); lab = QLabel(key); lab.setFixedWidth(40)
            pb = QProgressBar(); pb.setRange(0, 100); r.addWidget(lab); r.addWidget(pb); l.addLayout(r)
            self.bars[key] = pb
        self.batt = QLabel("Battery: -"); l.addWidget(self.batt)
        self.focus = QLabel("Active: -"); self.focus.setWordWrap(True); l.addWidget(self.focus)
        right.addWidget(c)

        c, l = _card("MEMORY")
        self.mem = QLabel("-"); self.mem.setWordWrap(True); l.addWidget(self.mem)
        right.addWidget(c)

        c, l = _card("ACTIVITY")
        self.activity = QListWidget(); self.activity.setMinimumHeight(130); self.activity.setWordWrap(True); self.activity.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); l.addWidget(self.activity)
        right.addWidget(c, 1)
        rw = QWidget(); rw.setLayout(right); rw.setFixedWidth(320); main.addWidget(rw)

    # ------------------------------------------------------------ slots
    def _scroll_chat_bottom(self):
        sb = self.chat.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_chat_range(self, _lo, hi):
        """setHtml() resets the view to the top and the scroll range is only final
        after layout - which is why the chat used to jump up by itself. Whenever
        the range changes and we're following the conversation, go to the end."""
        if self._stick:
            self.chat.verticalScrollBar().setValue(hi)

    def _on_chat_user_scroll(self, *_):
        sb = self.chat.verticalScrollBar()
        self._stick = sb.value() >= sb.maximum() - 6    # scrolled up to read -> stop following; back at the end -> follow again

    def _refresh_chat(self):
        body = "".join(self._html)
        if self._live:
            body += (f"<p><b style='color:#2bd9ff'>JUPITER</b><br><span style='color:#9fb3cc'>{render(self._live)}</span></p>")
        self.chat.setHtml(body)
        if self._stick:
            self._scroll_chat_bottom()
            QTimer.singleShot(0, self._scroll_chat_bottom)     # again once layout has settled
            QTimer.singleShot(80, self._scroll_chat_bottom)

    def add_message(self, role, text):
        who, col = {"user": ("You", "#7f93ad"), "jupiter": ("JUPITER", "#2bd9ff")}.get(role, ("SYSTEM", "#ffb020"))
        self._live = ""
        self._stick = True                      # a new message always brings you to the newest chat
        self._html.append(f"<p><b style='color:{col}'>{who}</b><br>{render(text)}</p>")
        self._refresh_chat()

    def on_stream(self, text):
        self._live = (self._live + " " + text).strip()
        self._refresh_chat()

    def add_log(self, text):
        self.activity.addItem(f"{time.strftime('%H:%M:%S')}  {text}")
        self.activity.scrollToBottom()

    def set_state(self, s):
        self._state = s
        col, cap, _ = STATE_STYLE.get(s, STATE_STYLE["IDLE"])
        self.reactor.set_state(s)
        self.orb_txt.setText(cap); self.orb_txt.setStyleSheet(f"color:{col};letter-spacing:3px;")

    def on_confirm(self, desc):
        self.confirm_bar.setVisible(bool(desc))
        self.confirm_lbl.setText(f"⚠  Waiting for your approval: {desc}")

    def on_models(self, llm, vision):
        self.chip_llm.setText(f"LLM: {llm}")
        self.chip_vis.setText("Vision: same model" if vision == llm else f"Vision: {vision}")

    def update_telemetry(self):
        self.bars["CPU"].setValue(int(psutil.cpu_percent(interval=None)))
        self.bars["RAM"].setValue(int(psutil.virtual_memory().percent))
        if time.time() - self._gpu_t > 4:
            self._gpu_t = time.time()
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
                                      "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=1.5).stdout
                u, mu, mt = [float(x) for x in out.strip().split("\n")[0].split(",")]
                self._gpu = (u, mu, mt)
            except Exception:
                self._gpu = (None, None, None)
        u, mu, mt = self._gpu
        self.bars["GPU"].setValue(int(u or 0)); self.bars["VRAM"].setValue(int(100 * mu / mt) if mu and mt else 0)
        self.bars["VRAM"].setFormat(f"{mu/1024:.1f} / {mt/1024:.0f} GB" if mu else "n/a")
        b = psutil.sensors_battery()
        self.batt.setText(f"Battery: {int(b.percent)}%{' (charging)' if b.power_plugged else ''}" if b else "Battery: n/a")
        try:
            if sys.platform == "win32":
                import ctypes
                user32 = ctypes.windll.user32
                hwnd = user32.GetForegroundWindow()
                n = user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                self.focus.setText(f"Active: {buf.value.strip() or 'Untitled'}")
            else:
                self.focus.setText("Active: n/a")
        except Exception:
            self.focus.setText("Active: n/a")

    def update_memory(self, d):
        lines = [f"Open tasks: {d['task_count']}"]
        if d["next_reminder"]:
            lines.append(f"Next reminder: {d['next_reminder'][0]}")
        lines += [f"• {f}" for f in d["facts"][:3]] or ["No saved facts yet"]
        self.mem.setText("\n".join(lines)); self.chip_mode.setText(f"Mode: {d['mode']}")

    def _toggle_alerts(self, on):
        if self.a and getattr(self.a, "watchdog", None):
            self.a.watchdog.enabled = on

    def _tiny(self, text):
        l = QLabel(text); l.setObjectName("h"); return l

    def _segment(self, layout, items, on_pick, vertical=False):
        """Exclusive row/column of checkable buttons; returns {value: button}."""
        group = QButtonGroup(self); group.setExclusive(True)
        box = QVBoxLayout() if vertical else QHBoxLayout(); box.setSpacing(4)
        buttons = {}
        for label, value in items:
            b = QPushButton(label); b.setCheckable(True); b.setProperty("seg", "true")
            b.clicked.connect(lambda _=False, v=value: on_pick(v))
            group.addButton(b); box.addWidget(b); buttons[value] = b
        layout.addLayout(box)
        return buttons

    def on_modes(self, input_mode, listen_mode, auto_return):
        """Reflect the assistant's real mode (it may have been changed by voice) in the controls."""
        for v, b in self.input_btns.items():
            b.setChecked(v == input_mode)
        for v, b in self.listen_btns.items():
            b.setChecked(v == listen_mode)
        self.return_cb.blockSignals(True); self.return_cb.setChecked(bool(auto_return)); self.return_cb.blockSignals(False)
        self.mic.setToolTip("Push to talk: click or press Enter / Space, then speak" if listen_mode == LISTEN_PTT else "Listen once")

    def eventFilter(self, obj, ev):
        """Push-to-talk: Enter OR Space (either one) starts listening. Typing is
        untouched - once the box has text, Space/Enter behave normally."""
        try:
            if ev.type() == QEvent.KeyPress and self._is_ptt_key(ev):
                if not ev.isAutoRepeat() and not self._busy.is_set():
                    self._enqueue("mic_once")
                return True
        except Exception as exc:
            print(f"[GUI ptt key] {exc}")
        return super().eventFilter(obj, ev)

    def _is_ptt_key(self, ev) -> bool:
        a = self.a
        if a is None or a.listen_mode != LISTEN_PTT or a.input_mode != "voice":
            return False
        if ev.key() not in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            return False
        if ev.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        if not self.isActiveWindow() or QApplication.activeModalWidget() is not None:
            return False
        fw = QApplication.focusWidget()
        if isinstance(fw, QLineEdit) and fw.text().strip():
            return False                      # you're typing a command: let Space/Enter work normally
        return True

    def _quit_app(self):
        """A spoken/typed quit: close the window and make sure the process really ends."""
        # Failsafe: if anything (PortAudio read, CUDA teardown) keeps the process
        # alive after the window closes, end it a moment later. Only on a real
        # quit, so test runs that open/close windows are never killed by it.
        t = threading.Timer(4.0, lambda: os._exit(0)); t.daemon = True; t.start()
        if self._alive:
            self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def stop_speech(self):
        if self.a is not None:
            try:
                self.a.interrupt_speech()
            except Exception:
                pass

    def closeEvent(self, e):
        self._alive = False
        try:
            if self.a is not None:
                getattr(self.a, "watchdog", None) and self.a.watchdog.stop()
                self.a.is_running = False
                self.a.shutdown()
        except Exception:
            pass
        super().closeEvent(e)

    def open_camera(self):
        explainer_ui.open_camera(self)

    def pick_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if path:
            self.submit(f'analyze image "{path}"')

    # ------------------------------------------------------------ input
    def on_send(self):
        text = self.input.text().strip()
        if text:
            self.input.clear(); self.submit(text)

    def submit(self, text):
        self._enqueue("cmd", text)

    def _enqueue(self, kind, payload=None):
        self.q.put((kind, payload))

    def _maybe_drain(self):
        a = self.a
        if a is not None and self.q.empty() and not a._events.empty():
            self.q.put(("drain", None))

    def _enqueue_once(self, kind):
        if self.a is not None and self.q.empty():
            self.q.put((kind, None))

    # ------------------------------------------------------------ worker thread
    def _hook(self, kind, text):
        if kind == "viewer":
            path, _, title = text.partition("|")
            self.bridge.viewer.emit(path, title or "3D model")
            return
        if kind == "camera":
            self.bridge.camera.emit()
            return
        if kind == "viewer_cmd":
            name, _, arg = text.partition("|")
            self.bridge.viewer_cmd.emit(name, arg or "null")
            return
        if kind == "progress":
            frac, _, rest = text.partition("|")
            stage, _, detail = rest.partition("|")
            try:
                self.bridge.progress.emit(float(frac), stage, detail)
            except ValueError:
                pass
            return
        sig = {"state": self.bridge.state, "log": self.bridge.log, "alert": self.bridge.alert,
               "action": self.bridge.action, "confirm": self.bridge.confirm}.get(kind)
        if sig:
            sig.emit(text)

    def _preflight(self, a):
        """Tell the user early (in the activity log) if a model is missing, instead of failing mid-demo."""
        from ..config import LLM_MODEL
        from ..services.vision import VisionService
        b = self.bridge
        base = a.ollama_url.rsplit("/api/", 1)[0]
        try:
            names = {m["name"] for m in a.http.get(base + "/api/tags", timeout=3).json().get("models", [])}
        except Exception:
            b.log.emit("WARNING: Ollama is not reachable (start it with: ollama serve)")
            return
        have = lambda n: n in names or f"{n}:latest" in names
        if not have(LLM_MODEL):
            b.log.emit(f"WARNING: missing model - run: ollama pull {LLM_MODEL}")
        a.vision = VisionService(a)
        vm = a.vision.model
        if not have(vm):
            b.log.emit(f"WARNING: missing vision model - run: ollama pull {vm}")
        b.models.emit(LLM_MODEL, vm)

    # ------------------------------------------------------------ modes
    def _idle_state(self):
        a = self.a
        if a.listen_mode == LISTEN_SLEEP:
            return "SLEEPING"
        if a.input_mode == "text":
            return "TEXT"
        if a.listen_mode == LISTEN_PTT:
            return "PTT"
        return "IDLE"

    def _emit_modes(self):
        a = self.a
        self.bridge.modes.emit(a.input_mode, a.listen_mode, bool(a.auto_return_to_voice))

    def _apply_mode(self, kind, value):
        """Same effects as the spoken mode commands, without the spoken announcement."""
        a = self.a
        if kind == "input":
            a.set_input_mode(value, announce=False)
        elif kind == "listen":
            if value == LISTEN_SLEEP:
                a.enter_sleep_mode()
            else:
                if a.listen_mode == LISTEN_SLEEP:
                    a.wake_from_sleep(greet=False)
                a.set_listen_mode(value, announce=False)
        elif kind == "return":
            a.auto_return_to_voice = bool(value)
            a._save_setting("auto_return_to_voice", "1" if value else "0")

    def _mic_wanted(self):
        a = self.a
        return (self._alive and a is not None and getattr(a, "is_running", True) and a.input_mode == "voice"
                and a.listen_mode in (LISTEN_ACTIVE, LISTEN_SLEEP) and a._voice_possible())

    def _mic_loop(self):
        """Own thread: keeps the microphone open in 'Always on' / 'Sleep' mode so typing is never blocked by listening.
        Anything heard while the worker is busy (JUPITER talking / thinking) is discarded to avoid hearing itself."""
        b = self.bridge
        while self._alive:
            if self.a is None or self._busy.is_set() or not self._mic_wanted():
                time.sleep(0.25)
                continue
            a = self.a
            sleeping = a.listen_mode == LISTEN_SLEEP
            try:
                if not sleeping:
                    b.state.emit("LISTENING")
                heard = a._listen_voice_input(max_duration=8, quick=True) if sleeping else a._listen_voice_input()
            except Exception as exc:
                print(f"[GUI mic] {exc}")
                time.sleep(1.0)
                continue
            if self._busy.is_set() or not self._mic_wanted():
                continue                       # typed command / mode change arrived meanwhile
            if not heard:
                if not self._busy.is_set():
                    b.state.emit(self._idle_state())
                continue
            if sleeping:
                woke, _ = a._split_wake(heard, sleeping=True)
                if not woke:
                    b.log.emit(f"[standby] ignored: {heard[:40]}")
                    continue
            self._busy.set()                   # claim the turn before the worker even sees it
            self.q.put(("cmd", heard))

    # ------------------------------------------------------------ worker thread
    def _worker(self):
        b = self.bridge
        try:
            b.state.emit("BOOTING"); b.log.emit("Booting JUPITER core")
            self.a = a = Jupiter()
            a.ui_hook = self._hook
            # The GUI must never block on the console: neutralise keyboard prompts.
            a._read_text_input = lambda *args, **kw: ""
            a._pending_keyboard_input = lambda: None
            orig = a.speak

            def speak(text, wait=True):
                if text:
                    self._spoken.append(str(text))
                    b.stream.emit(str(text))
                    b.state.emit("SPEAKING")
                return orig(text, wait)
            a.speak = speak
            self._preflight(a)
            self._emit_modes()
            b.booted.emit()
            b.state.emit(self._idle_state())
        except Exception as exc:
            b.message.emit("system", f"JUPITER failed to start: {exc}")
            return
        while True:
            job = self.q.get()
            kind, payload = job[0], job[1]
            turn = kind in ("cmd", "mic_once", "drain", "setmode")
            if turn:
                self._busy.set()
                a._interrupted.clear()          # a stale Stop/Esc must not silence the NEXT thing JUPITER says (same as run())
            try:
                if kind == "cmd":
                    self._process(payload, typed=True if len(job) < 3 else job[2])
                elif kind == "mic_once":
                    if not a._voice_possible():
                        b.message.emit("system", "No microphone/voice input is available. Type instead.")
                    else:
                        if a.listen_mode == LISTEN_SLEEP:
                            a.wake_from_sleep(greet=False)       # pressing the mic button is an explicit wake-up
                        b.state.emit("LISTENING")
                        text = a._listen_voice_input()
                        if text:
                            self._process(text, typed=False)
                elif kind == "setmode":
                    self._apply_mode(*payload)
                elif kind == "drain":
                    self._spoken.clear()
                    a.drain_events()
                    if self._spoken:
                        b.message.emit("system", " ".join(self._spoken))
                elif kind == "snapshot":
                    b.snapshot.emit(briefing.snapshot(a))
            except Exception as exc:
                print(f"[GUI worker] {exc}")
                b.log.emit(f"Error: {exc}")
            if turn:
                try:
                    a.wait_speech_done()        # never reopen the mic while JUPITER is still talking
                except Exception:
                    pass
                self._emit_modes()
                if confirm_state.current() is None:
                    b.confirm.emit("")
                b.state.emit(self._idle_state())
                if not getattr(a, "is_running", True):            # "quit" / "goodbye" / "shut down": sign-off has been spoken
                    b.quit.emit()
                    return                      # keep _busy set so the mic thread stays quiet
                self._busy.clear()

    def _process(self, text, typed=True):
        """Mirror of Jupiter.run() for one turn. `typed` = came from the keyboard/buttons rather than the mic."""
        a, b = self.a, self.bridge
        from ..common import WAKE_ACKS
        a._interrupted.clear()
        sleeping = a.listen_mode == LISTEN_SLEEP
        woke, rest = a._split_wake(text, sleeping=sleeping)
        if sleeping:
            if not woke:
                b.message.emit("system", "JUPITER is asleep. Say or type 'Jupiter, wake up' (or press the mic) to wake it.")
                return
            a.wake_from_sleep(greet=not rest)
            if not rest:
                return
            text = rest
        elif woke:
            if not rest:
                a.speak(a._pick(WAKE_ACKS)); return
            text = rest

        b.message.emit("user", text)
        b.state.emit("THINKING")
        t0 = time.perf_counter()
        self._spoken.clear()
        a._last_full_text = None
        a.store_conversation("user", text)
        a._previous_response = getattr(a, "_last_response", "")
        a._last_response = None
        cmd = a._normalise_command(text)
        a._pending_router_command = cmd
        skill, _ = a.router.route(cmd)
        b.log.emit(f"Intent -> {skill.name if skill else 'conversation / legacy'}")
        handled = a.dispatch_command(cmd)
        if handled:
            reply = a._last_full_text or a._last_response or " ".join(self._spoken)
            if a._last_response:
                a.store_conversation("jupiter", a._last_response)
        else:
            b.log.emit("Asking the language model")
            reply = a.think_stream(text)
            a.store_conversation("jupiter", reply)
        if reply:
            b.message.emit("jupiter", reply)
        elif self._live:
            b.message.emit("jupiter", self._live)
        # One-shot typing (same rule as the console): after a typed command in text mode, go back to the mic.
        if typed and a.input_mode == "text" and a.auto_return_to_voice and a._voice_possible() and not (skill and skill.name == "modes"):
            a._revert_to_voice()
        b.action.emit(f"{skill.name if skill else 'chat'} / {time.perf_counter() - t0:.1f}s")
        b.snapshot.emit(briefing.snapshot(a))


def launch():
    # QtWebEngine (embedded 3D viewer) must be configured before the QApplication exists.
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--ignore-gpu-blocklist --enable-webgl")
    try:
        from PySide6.QtCore import QCoreApplication
        QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    except Exception:
        pass
    app = QApplication.instance() or QApplication([])
    w = JupiterWindow(); w.show()
    return app.exec()
