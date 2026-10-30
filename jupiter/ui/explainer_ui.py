"""GUI pieces for the 3D Explainer: viewer window, webcam panel and the progress card.

Design rule (same as desktop.py): no AI logic here. The window sends ordinary commands ("show me the internal structure of X")
through the normal command path, so everything works the same by voice, by typing, or by pressing a button.
"""
import json
import threading
import time
import webbrowser
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
                               QProgressBar, QPushButton, QVBoxLayout, QWidget)

try:                                     # embedded 3D view; if missing we fall back to the default browser (Chrome / Edge)
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:                        # pragma: no cover - depends on the installation
    QWebEngineView = None

import os

from ..explainer import camera as cam


# ------------------------------------------------------------------ 3D viewer
class ViewerWindow(QMainWindow):
    cmd_sig = Signal(str, str)          # name, JSON arg - lets the hand-tracking thread talk to the page safely
    hand_status = Signal(str)

    def __init__(self, path: str, title: str):
        super().__init__()
        self.path = path
        self.setWindowTitle(f"JUPITER 3D Explainer - {title}")
        self.resize(1280, 780)
        root = QWidget(); self.setCentralWidget(root)
        lay = QVBoxLayout(root); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        self.view = QWebEngineView()
        lay.addWidget(self.view, 1)
        bar = QHBoxLayout(); bar.setContentsMargins(8, 4, 8, 4)
        self.note = QLabel("Drag = rotate · wheel = zoom · right-drag = pan · click a part · Space = assembly · E = explode · or say 'JUPITER, rotate left'")
        btn = QPushButton("Open in browser"); btn.setFixedWidth(140); btn.clicked.connect(self.open_in_browser)
        self.hand_btn = QPushButton("✋ Hand control: OFF"); self.hand_btn.setCheckable(True); self.hand_btn.setFixedWidth(170)
        self.hand_btn.clicked.connect(self.toggle_hand)
        self.hand = None
        self.cmd_sig.connect(self.run_cmd); self.hand_status.connect(self._hand_status)
        bar.addWidget(self.note, 1); bar.addWidget(self.hand_btn); bar.addWidget(btn)
        lay.addLayout(bar)
        self.view.loadFinished.connect(self._loaded)
        self.view.load(QUrl.fromLocalFile(str(Path(path).resolve())))

    def open_in_browser(self):
        webbrowser.open(Path(self.path).resolve().as_uri())

    # ---- control (voice commands and hand gestures both end up here) ----
    def run_cmd(self, name, arg_json):
        if not name.replace("_", "").isalnum():          # name comes from our own code, but never splice anything odd into JS
            return
        try:
            json.loads(arg_json)
        except ValueError:
            arg_json = "null"
        self.view.page().runJavaScript(f"window.JUP && window.JUP.cmd({json.dumps(name)}, {arg_json})")

    def toggle_hand(self, on=None, announce=None):
        on = self.hand_btn.isChecked() if on is None else bool(on)
        self.hand_btn.setChecked(on)
        if on:
            from ..explainer.gestures import HandControl
            data = Path(os.environ.get("JUPITER_DATA", Path(self.path).parent.parent))
            self.hand = HandControl(lambda n, a=None: self.cmd_sig.emit(n, json.dumps(a)), data,
                                    status=lambda s: self.hand_status.emit(s), camera_index=int(os.environ.get("JUPITER_CAMERA", "0")))
            self.hand.start()
            self.hand_btn.setText("✋ Hand control: ON")
        else:
            if self.hand:
                self.hand.stop()
            self.hand = None
            self.hand_btn.setText("✋ Hand control: OFF")
            self.cmd_sig.emit("cursor", "null")

    def _hand_status(self, s):
        self.note.setText(s)
        if self.hand and self.hand.error:                # camera / model problem -> switch the button back off
            self.hand_btn.setChecked(False); self.hand_btn.setText("✋ Hand control: OFF"); self.hand = None

    def closeEvent(self, e):
        if self.hand:
            self.hand.stop()
        super().closeEvent(e)

    def _loaded(self, ok):
        if not ok:
            self.note.setText("Could not load the 3D page in this window - opened in your browser instead.")
            self.open_in_browser()
            return
        QTimer.singleShot(3500, self._check_webgl)

    def _check_webgl(self):
        def done(result):
            if not result:
                self.note.setText("WebGL is not available in this window - opening in your browser (Chrome/Edge) instead.")
                self.open_in_browser()
        try:
            self.view.page().runJavaScript("!!(window.JUP && window.JUP.glOK)", done)
        except Exception:
            pass


def current_viewer(win):
    for v in reversed(getattr(win, "_viewers", None) or []):
        if v.isVisible():
            return v
    return None


def send_viewer_cmd(win, name: str, arg_json: str = "null"):
    """Voice/typed viewer command. Special names: hand_on / hand_off. Falls back gracefully when no viewer is open."""
    v = current_viewer(win)
    if v is None:
        win.add_log("No 3D viewer is open for that command"); return
    if name == "hand_on":
        v.toggle_hand(True)
    elif name == "hand_off":
        v.toggle_hand(False)
    else:
        v.run_cmd(name, arg_json)


def open_viewer(win, path: str, title: str):
    """Show the 3D page. Embedded window when QtWebEngine works, otherwise the default browser."""
    if QWebEngineView is None or os.environ.get("JUPITER_VIEWER", "").lower() == "browser":
        webbrowser.open(Path(path).resolve().as_uri())
        win.add_log("3D view opened in your browser")
        return
    try:
        w = ViewerWindow(path, title)
        keep = getattr(win, "_viewers", None)
        if keep is None:
            keep = win._viewers = []
        keep[:] = [v for v in keep if v.isVisible()][-3:]          # keep references so Qt does not garbage-collect the windows
        keep.append(w)
        w.show(); w.raise_()
        win.add_log(f"3D view: {title}")
    except Exception as exc:
        win.add_log(f"Embedded viewer failed ({exc}); using the browser")
        webbrowser.open(Path(path).resolve().as_uri())


# ------------------------------------------------------------------ webcam panel
class CameraDialog(QDialog):
    identified = Signal(dict)
    failed = Signal(str)

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("JUPITER - Webcam object identification")
        self.resize(720, 640)
        self._camera = self._session = self._sink = None
        self._last = None            # last QImage from the live preview
        self._jpeg = None
        self._qt_ok = False
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.status = QLabel("Camera OFF"); self.status.setObjectName("chip")
        top.addWidget(self.status); top.addStretch(); lay.addLayout(top)
        self.preview = QLabel("The camera is off.\nPress 'Start camera', hold an object up, then 'Capture & identify'.")
        self.preview.setAlignment(Qt.AlignCenter); self.preview.setMinimumSize(640, 360)
        self.preview.setStyleSheet("background:#000; border:1px solid #27406b; border-radius:8px; color:#7f93ad;")
        lay.addWidget(self.preview, 1)
        row = QHBoxLayout()
        self.b_start = QPushButton("Start camera"); self.b_start.clicked.connect(self.start_camera)
        self.b_cap = QPushButton("Capture & identify"); self.b_cap.clicked.connect(self.capture)
        self.b_file = QPushButton("Identify an image file…"); self.b_file.clicked.connect(self.pick_file)
        for b in (self.b_start, self.b_cap, self.b_file):
            row.addWidget(b)
        lay.addLayout(row)
        self.result = QLabel(""); self.result.setWordWrap(True); lay.addWidget(self.result)
        edit = QHBoxLayout()
        edit.addWidget(QLabel("Object:"))
        self.obj = QLineEdit(); self.obj.setPlaceholderText("identified (or type it yourself)")
        edit.addWidget(self.obj, 1); lay.addLayout(edit)
        acts = QHBoxLayout()
        self.b_explain = QPushButton("Explain this object"); self.b_explain.clicked.connect(lambda: self._act("explain"))
        self.b_inside = QPushButton("Show internal components"); self.b_inside.clicked.connect(lambda: self._act("inside"))
        self.b_web = QPushButton("Find info online"); self.b_web.clicked.connect(lambda: self._act("web"))
        self.b_retake = QPushButton("Retake"); self.b_retake.clicked.connect(self.retake)
        for b in (self.b_explain, self.b_inside, self.b_web, self.b_retake):
            acts.addWidget(b)
        lay.addLayout(acts)
        self.identified.connect(self._on_identified); self.failed.connect(self._on_failed)
        self._set_actions(False)

    # ---- camera control (nothing starts until the user presses the button) ----
    def start_camera(self):
        self._jpeg = None
        try:
            from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices, QVideoSink
            devices = QMediaDevices.videoInputs()
            if not devices:
                raise RuntimeError("no camera found")
            idx = min(int(os.environ.get("JUPITER_CAMERA", "0")), len(devices) - 1)
            self._camera = QCamera(devices[idx])
            self._session = QMediaCaptureSession()
            self._session.setCamera(self._camera)
            self._sink = QVideoSink()
            self._session.setVideoSink(self._sink)
            self._sink.videoFrameChanged.connect(self._on_frame)
            self._camera.start()
            self._qt_ok = True
            self.status.setText("● CAMERA LIVE")
            self.status.setStyleSheet("color:#ff5a6e; border:1px solid #ff5a6e;")
            self.b_start.setEnabled(False)
        except Exception as exc:
            self._qt_ok = False
            self.status.setText("Camera preview unavailable")
            self.preview.setText(f"Live preview is not available ({exc}).\n'Capture & identify' will still try to grab one frame with OpenCV,\n"
                                 "or use 'Identify an image file…'.")

    def stop_camera(self):
        try:
            if self._camera is not None:
                self._camera.stop()
        except Exception:
            pass
        self._camera = self._session = self._sink = None
        self.status.setText("Camera OFF"); self.status.setStyleSheet("")
        self.b_start.setEnabled(True)

    def _on_frame(self, frame):
        try:
            img = frame.toImage()
            if img.isNull():
                return
            self._last = img
            self.preview.setPixmap(QPixmap.fromImage(img).scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception:
            pass

    # ---- capture + identify (explicit user action) -------------------------------
    def capture(self):
        if self._qt_ok and self._last is not None:
            img = self._last.copy()
            self.stop_camera()                                  # the camera is switched off right after the shot
            self.preview.setPixmap(QPixmap.fromImage(img).scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            if img.width() > 960:
                img = img.scaledToWidth(960, Qt.SmoothTransformation)
            buf = QBuffer(); buf.open(QIODevice.WriteOnly); img.save(buf, "JPEG", 85)
            self._identify_async(bytes(buf.data()))
        elif not self._qt_ok:
            self._identify_async(None)                         # OpenCV fallback grabs one frame inside the worker thread
        else:
            self.result.setText("No frame yet - wait a second for the camera to warm up, then try again.")

    def pick_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        pm = QPixmap(path)
        if not pm.isNull():
            self.preview.setPixmap(pm.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        try:
            from PIL import Image
            self._identify_async(cam.jpeg_from_pil(Image.open(path)))
        except Exception as exc:
            self.failed.emit(f"I couldn't read that image: {exc}")

    def _identify_async(self, jpeg):
        self.result.setText("Identifying… (the local vision model is looking at the frame)")
        self._set_actions(False)
        a = self.win.a
        if a is None:
            self.failed.emit("JUPITER is still starting up.")
            return

        def work():
            try:
                data = jpeg if jpeg is not None else cam.capture_with_opencv(int(os.environ.get("JUPITER_CAMERA", "0")))
                from ..skills.explainer import ExplainerSkill
                svc = ExplainerSkill.service(a)
                model = svc._vision_model()
                t0 = time.perf_counter()
                info = cam.identify(data, a.ollama_url, model)
                svc.metrics.record("vision.identify", model=model, cache_hit=False, total_s=time.perf_counter() - t0,
                                   ok=info["object"] != "unknown", detail=info["object"])
                self.identified.emit(info)
            except cam.CameraError as exc:
                self.failed.emit(str(exc))
            except Exception as exc:
                self.failed.emit(f"Something went wrong: {exc}")
        threading.Thread(target=work, name="camera-identify", daemon=True).start()

    def _on_identified(self, info):
        obj = info["object"]
        if obj == "unknown":
            self.result.setText("I can't tell what this is. Try better light or a closer view - or type the name below.")
            self.obj.setText("")
        else:
            warn = "" if info["confidence"] == "high" else "  (not certain - correct me below if needed)"
            self.result.setText(f"<b>{obj}</b> - confidence: {info['confidence']}{warn}<br>{info['description']}")
            self.obj.setText(obj)
        self._set_actions(bool(obj != "unknown"))

    def _on_failed(self, msg):
        self.result.setText(msg)
        self._set_actions(bool(self.obj.text().strip()))
        self.obj.setFocus()

    def _set_actions(self, on):
        for b in (self.b_explain, self.b_inside, self.b_web):
            b.setEnabled(on)

    def retake(self):
        self.result.setText(""); self.obj.clear(); self._last = None
        self.preview.setPixmap(QPixmap()); self.preview.setText("Press 'Start camera'.")
        self._set_actions(False)
        self.start_camera()

    def _act(self, what):
        obj = self.obj.text().strip().lower()
        if not obj:
            self.result.setText("Type or identify an object first.")
            return
        if what == "explain":
            self.win.submit(f"explain what a {obj} is and how it works in simple terms")
        elif what == "inside":
            self.win.submit(f"show me the internal structure of a {obj}")
        else:
            webbrowser.open(cam.search_url(obj))

    def closeEvent(self, e):
        self.stop_camera()
        super().closeEvent(e)

    def done(self, r):
        self.stop_camera()
        super().done(r)


def open_camera(win):
    dlg = getattr(win, "_cam_dialog", None)
    if dlg is None or not dlg.isVisible():
        dlg = win._cam_dialog = CameraDialog(win)
    dlg.show(); dlg.raise_(); dlg.activateWindow()


# ------------------------------------------------------------------ progress card (left column)
def build_explainer_card(win, card_factory):
    """Returns the card frame; win gets .ex_bar / .ex_status / .ex_list used by on_progress()."""
    f, lay = card_factory("3D EXPLAINER")
    win.ex_status = QLabel("Idle - ask for any topic"); win.ex_status.setWordWrap(True)
    win.ex_bar = QProgressBar(); win.ex_bar.setRange(0, 100); win.ex_bar.setValue(0)
    win.ex_list = QListWidget(); win.ex_list.setFixedHeight(96); win.ex_list.setWordWrap(True)
    win.ex_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    lay.addWidget(win.ex_status); lay.addWidget(win.ex_bar); lay.addWidget(win.ex_list)
    for label, handler in (("Webcam identify", win.open_camera), ("Re-open last 3D view", lambda: win.submit("explode it")),
                           ("Performance report", lambda: win.submit("performance report"))):
        b = QPushButton(label); b.clicked.connect(lambda _=False, h=handler: h()); lay.addWidget(b)
    return f


def on_progress(win, frac: float, stage: str, detail: str):
    if stage == "start":
        win.ex_list.clear()
    win.ex_bar.setValue(int(max(0.0, min(1.0, frac)) * 100))
    if stage == "failed":
        win.ex_status.setText("Failed - see message"); win.ex_list.addItem("✗ " + detail)
    elif stage == "done":
        win.ex_status.setText("Ready"); win.ex_list.addItem("✓ " + detail)
    elif stage == "component":
        win.ex_status.setText("Receiving components…"); win.ex_list.addItem("• " + detail)
    else:
        win.ex_status.setText(detail[:60]); win.ex_list.addItem("· " + detail)
    win.ex_list.scrollToBottom()
