"""Hand-gesture control for the 3D viewer: webcam -> MediaPipe hand landmarks -> viewer commands.

Pure-Python classifier (testable without a camera) + a worker thread. Privacy: frames stay in memory, nothing is saved or sent.
Gestures (right or left hand):
  OPEN PALM move      -> rotate model (move hand left/right/up/down)
  FIST (hold)         -> grab: drag hand to pan the model
  PINCH (thumb+index) -> click / select the part under the yellow pointer
  TWO HANDS apart/together -> zoom in / out
  POINT (index only)  -> pointer: hover & highlight parts
  PEACE (2 fingers) hold 0.8s -> toggle explode / assemble
  THUMBS UP hold      -> x-ray toggle         THUMB + PINKY ("call") hold -> labels toggle
  3 FINGERS hold      -> play assembly walkthrough    OPEN PALM held still 1.2s -> stop / pause
"""
from __future__ import annotations

import math
import os
import threading
import time
import urllib.request
from pathlib import Path

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
WRIST, T_TIP, T_IP, I_MCP, I_TIP, M_MCP, M_TIP, R_MCP, R_TIP, P_MCP, P_TIP = 0, 4, 3, 5, 8, 9, 12, 13, 16, 17, 20
FINGERS = ((8, 6), (12, 10), (16, 14), (20, 18))          # (tip, pip) for index, middle, ring, pinky


class GestureError(Exception):
    """Message is safe to show or speak."""


def _d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def classify(lm) -> str:
    """lm: 21 (x, y) points, image coords (y grows downward). Returns open|fist|pinch|point|peace|three|thumbs_up|call|unknown."""
    if lm is None or len(lm) < 21:
        return "unknown"
    size = _d(lm[WRIST], lm[M_MCP]) or 1e-6                 # hand scale = wrist -> middle knuckle
    ext = [(_d(lm[WRIST], lm[t]) > _d(lm[WRIST], lm[p]) * 1.08) for t, p in FINGERS]       # index, middle, ring, pinky extended?
    thumb_out = _d(lm[T_TIP], lm[P_MCP]) > _d(lm[T_IP], lm[P_MCP]) * 1.15 and _d(lm[T_TIP], lm[I_MCP]) > size * 0.55
    pinch = _d(lm[T_TIP], lm[I_TIP]) < size * 0.38
    n = sum(ext)
    if pinch and (ext[1] or ext[2] or ext[3] or n >= 1):
        return "pinch"
    if n == 4:
        return "open"
    if n == 0:
        up = lm[T_TIP][1] < min(lm[I_MCP][1], lm[M_MCP][1]) - size * 0.3
        return "thumbs_up" if thumb_out and up else "fist"
    if ext == [True, False, False, False]:
        return "point"
    if ext == [True, True, False, False]:
        return "peace"
    if ext == [True, True, True, False]:
        return "three"
    if ext == [False, False, False, True] and thumb_out:
        return "call"
    return "unknown"


def palm_center(lm):
    return ((lm[WRIST][0] + lm[M_MCP][0]) / 2, (lm[WRIST][1] + lm[M_MCP][1]) / 2)


class GestureController:
    """Turns a stream of per-frame hands into viewer commands. `send(name, arg)` is the only output (fully testable).

    Mirror: webcam images are mirrored so moving your hand right moves the model right.
    """
    HOLD = 0.8          # seconds a toggle gesture must be held
    COOLDOWN = 1.3      # seconds between toggles

    def __init__(self, send, now=time.monotonic):
        self.send, self.now = send, now
        self.prev = None            # last palm centre (rotate / pan)
        self.prev_two = None        # last distance between two hands (zoom)
        self.held, self.held_since, self.last_fire = None, 0.0, 0.0
        self.pinching = False
        self.still_since = None
        self.last_g = "none"

    # hands: list of 21-point lists already mirrored (x flipped). Returns the gesture name for the HUD.
    def update(self, hands) -> str:
        t = self.now()
        if not hands:
            self._reset()
            return "none"
        if len(hands) >= 2:
            a, b = palm_center(hands[0]), palm_center(hands[1])
            dist = _d(a, b)
            if self.prev_two:
                ratio = dist / self.prev_two
                if abs(ratio - 1) > 0.015:
                    self.send("zoom", 1 / max(0.8, min(1.25, ratio)))      # hands apart -> closer
            self.prev_two, self.prev = dist, None
            self.send("cursor", None)
            self.last_g = "zoom"
            return "zoom"
        self.prev_two = None
        lm = hands[0]
        g = classify(lm)
        c = palm_center(lm)
        # ---- continuous gestures
        if g == "open":
            if self.prev:
                dx, dy = c[0] - self.prev[0], c[1] - self.prev[1]
                if abs(dx) + abs(dy) > 0.004:
                    self.send("orbit", [-dx * 5.0, dy * 4.0])
                    self.still_since = None
                elif self.still_since is None:
                    self.still_since = t
                elif t - self.still_since > 1.2 and t - self.last_fire > self.COOLDOWN:
                    self.send("stop", None); self.last_fire = t; self.still_since = None
            self.send("cursor", None)
        elif g == "fist":
            if self.prev and self.last_g == "fist":
                self.send("pan", [(c[0] - self.prev[0]) * 1.2, (c[1] - self.prev[1]) * 1.2])
            self.send("cursor", None)
        elif g in ("point", "pinch"):
            tip = lm[I_TIP]
            self.send("cursor", [tip[0], tip[1]])
            if g == "pinch" and not self.pinching:
                self.send("click", None)
            self.pinching = g == "pinch"
        self.prev = c if g in ("open", "fist") else None
        if g != "pinch":
            self.pinching = False
        # ---- hold-to-toggle gestures
        action = {"peace": "toggle_explode", "thumbs_up": "xray", "call": "labels", "three": "play"}.get(g)
        if action:
            if self.held != g:
                self.held, self.held_since = g, t
            elif t - self.held_since >= self.HOLD and t - self.last_fire >= self.COOLDOWN:
                self.send(action, None)
                self.last_fire, self.held_since = t, t + 9e9       # fire once per hold
        else:
            self.held = None
        self.last_g = g
        return g

    def _reset(self):
        self.prev = self.prev_two = self.held = self.still_since = None
        self.pinching = False
        self.send("cursor", None)
        self.last_g = "none"


def ensure_model(data_dir) -> str:
    """hand_landmarker.task for the MediaPipe Tasks API (downloaded once, ~7 MB)."""
    p = Path(data_dir) / "hand_landmarker.task"
    if p.exists() and p.stat().st_size > 1_000_000:
        return str(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(MODEL_URL, str(p) + ".part")
        os.replace(str(p) + ".part", p)
    except Exception as exc:
        raise GestureError("I need to download the hand-tracking model once (7 MB) but couldn't. Connect to the internet and try again, "
                           f"or save it manually as {p}.") from exc
    return str(p)


def _make_detector(data_dir):
    """Return detect(rgb_frame)->list of 21-point lists. Supports mediapipe<=0.10.21 (solutions) and the newer Tasks API."""
    try:
        import mediapipe as mp
    except ImportError as exc:
        raise GestureError("Hand tracking needs MediaPipe. Run: pip install mediapipe opencv-python") from exc
    if hasattr(mp, "solutions") and hasattr(mp.solutions, "hands"):
        hands = mp.solutions.hands.Hands(max_num_hands=2, model_complexity=0, min_detection_confidence=0.6, min_tracking_confidence=0.5)

        def detect(rgb):
            res = hands.process(rgb)
            return [[(l.x, l.y) for l in h.landmark] for h in (res.multi_hand_landmarks or [])]
        return detect, hands.close
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision
    opts = vision.HandLandmarkerOptions(base_options=mpt.BaseOptions(model_asset_path=ensure_model(data_dir)), num_hands=2,
                                        min_hand_detection_confidence=0.6, min_tracking_confidence=0.5)
    det = vision.HandLandmarker.create_from_options(opts)

    def detect(rgb):
        img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        return [[(l.x, l.y) for l in h] for h in det.detect(img).hand_landmarks]
    return detect, det.close


class HandControl:
    """Background thread: camera frames -> controller. start()/stop() are explicit user actions; nothing runs otherwise."""

    def __init__(self, send, data_dir, status=None, camera_index=0, show_preview=False):
        self.send, self.data_dir, self.status = send, data_dir, status or (lambda s: None)
        self.index, self.preview = camera_index, show_preview
        self._stop = threading.Event()
        self._thread = None
        self.error = ""

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def start(self):
        if self.running:
            return
        self._stop.clear()
        self.error = ""
        self._thread = threading.Thread(target=self._run, name="hand-control", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None

    def _run(self):
        try:
            import cv2
            detect, close = _make_detector(self.data_dir)
        except ImportError:
            self.error = "OpenCV is not installed. Run: pip install opencv-python"; self.status(self.error); return
        except GestureError as exc:
            self.error = str(exc); self.status(self.error); return
        except Exception as exc:
            self.error = f"Hand tracking failed to start: {exc}"; self.status(self.error); return
        cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(self.index)
        if not cap.isOpened():
            self.error = "I couldn't open the webcam. Close other apps using it and check camera privacy settings."
            self.status(self.error); close(); return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        ctl = GestureController(self.send)
        self.status("Hand control ON")
        misses = 0
        try:
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    misses += 1
                    if misses > 30:
                        self.error = "The webcam stopped giving pictures."; self.status(self.error); break
                    time.sleep(0.03); continue
                misses = 0
                frame = cv2.flip(frame, 1)                              # mirror
                hands = detect(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                g = ctl.update(hands)
                self.status(f"Hand: {g}")
                if self.preview:
                    for h in hands:
                        for x, y in h:
                            cv2.circle(frame, (int(x * frame.shape[1]), int(y * frame.shape[0])), 3, (0, 255, 255), -1)
                    cv2.putText(frame, g, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                    cv2.imshow("JUPITER hand control (q to close)", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                else:
                    time.sleep(0.005)
        finally:
            cap.release(); close()
            if self.preview:
                cv2.destroyAllWindows()
            self.send("cursor", None)
            self.status("Hand control OFF")
