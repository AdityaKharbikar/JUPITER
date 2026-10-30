"""Tiny bridge so skills/services can tell the GUI what they are doing.

The GUI sets ``assistant.ui_hook = callback(kind, text)``. In console mode the
attribute does not exist and every call is a no-op, so nothing here can break
the voice loop.   kinds: "state", "log", "alert", "action"
"""


def emit(assistant, kind: str, text: str = ""):
    cb = getattr(assistant, "ui_hook", None)
    if cb:
        try:
            cb(kind, text)
        except Exception:
            pass
