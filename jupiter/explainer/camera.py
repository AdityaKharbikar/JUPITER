"""Webcam capture + object identification (no Qt here, so it is testable and also works from the console).

Privacy rule: a frame is only ever grabbed after an explicit user action (button / spoken command) and is kept in memory;
nothing is written to disk and nothing leaves the machine - identification goes to the LOCAL Ollama server.
"""
from __future__ import annotations

import base64
import io
import json
import re
import time

import requests

from .schema import SpecError, clean_text, extract_json

ID_SCHEMA = {
    "type": "object",
    "properties": {
        "object": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "category": {"type": "string"},
        "description": {"type": "string"},
    },
    "required": ["object", "confidence", "description"],
}

ID_PROMPT = ("Identify the single main object shown by the camera. Reply with JSON: object (a short common noun phrase such as "
             "'computer mouse' or 'water bottle', lower case), confidence (high, medium or low), category, description "
             "(one plain sentence). If nothing clear is visible or you are not sure what it is, use object 'unknown' and confidence 'low'. "
             "Do not guess brands or models that you cannot actually read.")


class CameraError(Exception):
    """Message is safe to show or speak."""


def jpeg_from_pil(img, max_width=960, quality=85) -> bytes:
    if img.width > max_width:
        img = img.resize((max_width, int(img.height * max_width / img.width)))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def capture_with_opencv(index=0, warmup=8) -> bytes:
    """One frame from the webcam via OpenCV (console path / fallback). Raises CameraError with a helpful message."""
    try:
        import cv2
    except ImportError as exc:
        raise CameraError("OpenCV is not installed. Run: pip install opencv-python") from exc
    import sys
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(index)
    try:
        if not cap.isOpened():
            raise CameraError("I couldn't open the webcam. Close other apps using it and check Windows camera privacy settings.")
        frame = None
        for _ in range(warmup):                 # first frames are often dark while auto-exposure settles
            ok, f = cap.read()
            if ok:
                frame = f
            time.sleep(0.03)
        if frame is None:
            raise CameraError("The webcam opened but gave no picture.")
        ok, enc = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            raise CameraError("I couldn't encode the webcam frame.")
        return enc.tobytes()
    finally:
        cap.release()


def parse_identification(text: str) -> dict:
    try:
        data = extract_json(text)
    except SpecError:
        raise CameraError("The vision model did not return a usable answer.")
    obj = clean_text(data.get("object"), 60).lower().strip(" .")
    conf = str(data.get("confidence", "low")).lower()
    if conf not in ("high", "medium", "low"):
        conf = "low"
    if not obj or obj in ("unknown", "none", "nothing", "n/a"):
        obj, conf = "unknown", "low"
    return {"object": obj, "confidence": conf, "category": clean_text(data.get("category"), 40),
            "description": clean_text(data.get("description"), 200)}


def identify(jpeg: bytes, ollama_url: str, model: str, http=None, timeout=(5, 120)) -> dict:
    """Ask the local vision-capable model what the object is. Honest about uncertainty; never invents a result on failure."""
    http = http or requests
    payload = {
        "model": model, "stream": False, "think": False, "keep_alive": "15m", "format": ID_SCHEMA,
        "messages": [{"role": "user", "content": ID_PROMPT, "images": [base64.b64encode(jpeg).decode("ascii")]}],
        "options": {"temperature": 0.1, "num_predict": 160, "num_ctx": 4096},
    }
    try:
        r = http.post(ollama_url, json=payload, timeout=timeout)
        if r.status_code == 400:               # older Ollama without schema support
            payload["format"] = "json"
            payload.pop("think", None)
            r = http.post(ollama_url, json=payload, timeout=timeout)
    except requests.exceptions.ConnectionError:
        raise CameraError("Ollama is not running, so I can't identify the object. You can type its name instead.")
    except requests.exceptions.Timeout:
        raise CameraError("The vision model took too long to answer.")
    if r.status_code == 404:
        raise CameraError(f"The model {model} is not installed. Run: ollama pull {model}")
    if r.status_code != 200:
        raise CameraError(f"Ollama returned error {r.status_code}.")
    text = r.json().get("message", {}).get("content", "")
    return parse_identification(re.sub(r"<think>.*?</think>", "", text, flags=re.S))


def search_url(query: str) -> str:
    from urllib.parse import quote_plus
    return "https://www.google.com/search?q=" + quote_plus(query)


if __name__ == "__main__":                       # python -m jupiter.explainer.camera   -> quick hardware check
    import sys
    try:
        data = capture_with_opencv()
        open("camera_test.jpg", "wb").write(data)
        print(f"OK: grabbed {len(data)} bytes, saved camera_test.jpg (delete it afterwards)")
    except CameraError as e:
        print("FAILED:", e)
        sys.exit(1)
