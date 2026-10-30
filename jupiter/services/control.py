"""Guarded desktop control. Every capability is an explicit, named entry below -
there is no 'do anything' action. Risky ones go through core/confirm.py first."""
import os
import sys
import time

from ..core import confirm
from ..core.hooks import emit

SAFE_KEYS = {"enter", "escape", "tab", "space", "backspace", "delete", "up", "down", "left", "right",
             "home", "end", "pageup", "pagedown", "f5"}
_KEY_ALIASES = {"esc": "escape", "return": "enter", "page up": "pageup", "page down": "pagedown"}

# op -> (hotkey tuple, spoken, needs_confirm)
HOTKEYS = {
    "show_desktop": (("winleft", "d"), "Showing the desktop", False),
    "switch_window": (("alt", "tab"), "Switching window", False),
    "snap_left": (("winleft", "left"), "Snapping the window left", False),
    "snap_right": (("winleft", "right"), "Snapping the window right", False),
    "maximize": (("winleft", "up"), "Maximizing the window", False),
    "new_tab": (("ctrl", "t"), "Opening a new tab", False),
    "close_tab": (("ctrl", "w"), "Closing the tab", False),
    "refresh": (("f5",), "Refreshing", False),
    "close_window": (("alt", "f4"), "close the active window", True),
}


class ControlService:
    def __init__(self, assistant):
        self.a = assistant

    def _pag(self):
        try:
            import pyautogui
        except ImportError:
            self.a.speak(f"Desktop control needs pyautogui, {self.a.user_name}. Run: pip install pyautogui")
            return None
        pyautogui.FAILSAFE = True         # slam the mouse into a screen corner to abort anything
        pyautogui.PAUSE = 0.05
        return pyautogui

    def hotkey(self, op: str):
        keys, said, needs = HOTKEYS[op]
        if needs:
            confirm.propose(self.a, said, lambda: self._press(keys, f"Done, {self.a.user_name}."),
                            prompt=f"I'm about to {said}. Unsaved work could be lost. Say confirm, or cancel.")
        else:
            self._press(keys, f"{said}, {self.a.user_name}.")

    def _press(self, keys, said):
        pag = self._pag()
        if pag is None:
            return
        pag.hotkey(*keys)
        emit(self.a, "log", f"Control: hotkey {'+'.join(keys)}")
        self.a.speak(said)

    def scroll(self, direction: str):
        pag = self._pag()
        if pag:
            pag.scroll(-700 if direction == "down" else 700)
            emit(self.a, "log", f"Control: scroll {direction}")

    def press_key(self, name: str):
        name = _KEY_ALIASES.get(name, name)
        if name not in SAFE_KEYS:
            self.a.speak(f"I'm only allowed to press navigation keys, {self.a.user_name}.")
            return
        pag = self._pag()
        if pag:
            pag.press(name)
            emit(self.a, "log", f"Control: key {name}")

    def type_text(self, text: str):
        """Types via the clipboard (supports any language), after a short countdown so you can focus the target."""
        pag = self._pag()
        if pag is None:
            return
        try:
            import pyperclip
        except ImportError:
            self.a.speak("I need pyperclip for typing."); return
        self.a.speak(f"Typing in three seconds. Click where you want it, {self.a.user_name}.")
        time.sleep(3)
        old = None
        try:
            old = pyperclip.paste()
        except Exception:
            pass
        pyperclip.copy(text)
        pag.hotkey("ctrl", "v")
        time.sleep(0.2)
        if old is not None:
            pyperclip.copy(old)
        emit(self.a, "log", f"Control: typed {len(text)} chars")


    def active_window_title(self):
        if sys.platform != "win32":
            self.a.speak("Active-window information is currently implemented for Windows.")
            return None
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                self.a.speak("I couldn't identify the active window.")
                return None
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip() or "Untitled window"
            emit(self.a, "log", f"Active window: {title}")
            self.a.speak(f"The active window is {title}, {self.a.user_name}.")
            return title
        except Exception:
            self.a.speak("I couldn't read the active window.")
            return None

    def _screenshot_folder(self) -> str:
        """The configured Screenshots folder; falls back to ~/Pictures/Screenshots
        (e.g. on another machine or if the folder can't be created)."""
        from ..config import SCREENSHOT_DIR
        candidates = []
        if sys.platform == "win32" or os.path.isabs(SCREENSHOT_DIR):
            candidates.append(SCREENSHOT_DIR)
        candidates.append(os.path.join(os.path.expanduser("~"), "Pictures", "Screenshots"))
        for folder in candidates:
            try:
                os.makedirs(folder, exist_ok=True)
                return folder
            except OSError:
                continue
        return os.path.expanduser("~")

    def screenshot(self):
        try:
            from PIL import ImageGrab
        except ImportError:
            self.a.speak("I need Pillow for screenshots.")
            return
        folder = self._screenshot_folder()
        path = os.path.join(folder, time.strftime("screenshot_%Y%m%d_%H%M%S.png"))
        try:
            ImageGrab.grab().save(path)
        except Exception as exc:
            self.a.speak(f"I couldn't save the screenshot: {exc}")
            return None
        if not os.path.isfile(path):
            self.a.speak("The screenshot didn't get saved, sorry.")
            return None
        print(f"[Screenshot] saved to {path}")
        emit(self.a, "log", f"Screenshot saved: {path}")
        self.a.speak(f"Screenshot saved in your Screenshots folder, {self.a.user_name}.")
        return path

    def lock(self):
        def do():
            if sys.platform == "win32":
                import ctypes
                ctypes.windll.user32.LockWorkStation()
            else:
                self.a.speak("Locking is only supported on Windows.")
        confirm.propose(self.a, "lock the computer", do, prompt="Shall I lock the computer? Say confirm, or cancel.")
